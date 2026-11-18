# Running the full pipeline with Vertex AI batches

Generates a text summary and an infographic JPEG for every gene in the Human Protein
Atlas (HPA version 26), using Vertex AI batch jobs: one for text, then rounds of images,
each followed by an automatic image check with Claude Opus 5.5. Genes whose image fails go
into the next round. The jobs run on Google's side, so the laptop can be closed while they
run. **Everything runs as batch jobs** (half the standard price); only the last handful of
images are drawn live and reviewed by eye. Run all commands from the repo root.

```
proteinatlas.tsv ──fetch_all──▶ data/*_hpa.json + output/*_hpa_clean.json
                 ──text batch──▶ output/*_summary.md / .json   (+ fact check, spelling fixes)
                 ──image rounds (batch + Opus check batch)──▶ output/images/*.jpg
```

## Prerequisites

- Vertex AI access is already set up (see [setup_gemini_vertex_ai.md](setup_gemini_vertex_ai.md)).
  Everything runs under those credentials and is billed to `scilifelab-hpa-proj-1`.
- Batch input/output lives in BigQuery in that project: dataset `gene_summaries_batch`
  (location US) for the Gemini jobs and `gene_summaries_check` (us-east5) for the Claude
  check jobs. Both are created automatically on first use.
- Python packages: `google-genai`, `google-auth`, `requests`, `beautifulsoup4`, `Pillow`,
  `anthropic[vertex]`, `pydantic`. Claude Opus 5.5 must be enabled in Vertex AI Model Garden.

## Reference: the v26 run (20,162 genes, Nov 2026)

| Step | Where | Time |
|---|---|---|
| 1. Fetch + clean | laptop | ~4 h |
| 2–4. Text batch (80,648 requests) + collect | Google + laptop | ~2.5 h |
| Image round 1: batch (20,162 requests) | Google | a few hours (max 24 h) |
| &nbsp;&nbsp;download JPEGs (~4.2 GB) | laptop | ~45 min |
| &nbsp;&nbsp;Opus check: upload (~7 GB) + batch | laptop + Google | ~1 h + ~1.5 h |
| Later rounds | Google + laptop | same steps, smaller |

| Round | Style | Genes in | Still failing after |
|---|---|---|---|
| 1 | rich | 20,162 | 6,649 (33%) |
| 2 | rich | 6,649 | 2,509 → 2,302 after a manual look |
| 3 | line art | 2,302 | 818 |
| 4 | simple | 818 | 235 |
| 5 | simple | 235 | 94 |
| 6 | simple | 94 | 64 |
| final | simple, live + reviewed by eye | 61 | 0 |

Cost: about $2,030 for ~30,000 images and ~$400 for the Opus checks (batch prices).

---

## 1. Get the gene list and fetch + clean the HPA data

Download `proteinatlas.tsv` from the HPA *Downloads* page (`proteinatlas.tsv.zip`), unzip it,
and put it at `data/proteinatlas.tsv`. Then:

```bash
python3 scripts/fetch_all.py
```

- For each gene it fetches the HPA page + JSON to `data/<ID>_hpa.json`, then runs the clean
  step to write `output/<ID>_hpa_clean.json`.
- It is rate-limited (3 requests/s to HPA) and **resumable**. If it is interrupted, rerun the
  same command and genes already on disk are skipped. Failed genes go to
  `output/fetch_failures.tsv`, and a rerun retries them.
- To keep the Mac awake during the run: `caffeinate -i python3 scripts/fetch_all.py`
- Smoke test first: `python3 scripts/fetch_all.py --limit 20`

**Progress:** a status line every 100 genes with an ETA. To log to a file and follow it:
```bash
python3 -u scripts/fetch_all.py > data/fetch_all.log 2>&1 &
tail -f data/fetch_all.log
```

## 2. Build the text batch input (batch 1)

```bash
python3 scripts/batch_text_prepare.py --load
```

- Builds one request per gene × section (4 per gene). It uses the same prompts and settings
  as `summarize_gene.py`.
- Writes `data/batch/text_requests.jsonl` and loads it into BigQuery table `text_in`,
  replacing that table if it already exists.
- Without `--load`, it only builds the local file.

## 3. Run the text batch

```bash
python3 scripts/batch_submit.py text
```

Submits `text_in` → `text_out` with `gemini-3.8-flash`. The job is recorded in
`data/batch/jobs.jsonl`.

> **New run?** Use a fresh output table so old results are not mixed in, e.g.
> `--dest text_out_2027`, and pass the same name to the collect step (`--table text_out_2027`).

**Progress:**
```bash
python3 scripts/batch_submit.py --status
```
`JOB_STATE_PENDING` → `RUNNING` → `SUCCEEDED`, with ok/failed counts.

## 4. Collect the text summaries

```bash
python3 scripts/batch_text_collect.py
```

- Reads `text_out` and writes `output/<ID>_summary.md` + `output/<ID>_summary.json` per gene.
  The output is identical in format to a local `summarize_gene.py` run.
- A gene is only written if **all** its sections succeeded. Failed request keys go to
  `data/batch/text_failures.txt`, and the script prints the retry command.

**Retry failures** (usually 0–few; transient Google errors):
```bash
python3 scripts/batch_text_prepare.py --only-keys data/batch/text_failures.txt \
    --out data/batch/text_retry.jsonl --load --table text_retry_in
python3 scripts/batch_submit.py text --src text_retry_in --dest text_retry_out
python3 scripts/batch_text_collect.py --table text_out --table text_retry_out
```
For a handful of genes it is faster to run them locally instead:
`python3 scripts/summarize_gene.py output/<ID>_hpa_clean.json --outdir output`

## 4b. Fact check the summaries (grounding)

Optional, but recommended before generating images. It checks that every named entity in a
summary (disease, tissue, cell type, organ, gene, number) appears in that gene's HPA data,
i.e. the model did not invent facts.

```bash
python3 scripts/check_grounding.py output/ENSG*_summary.json --clean-dir output \
    > data/batch/grounding_report.txt
tail -1 data/batch/grounding_report.txt          # TOTAL FLAGS: …
```

- The report lists each flagged bullet with the term that was not found
  (`NOT IN DATA: …`). A capitalised verb at the start of a bullet ("Displays Low cancer
  specificity") is ignored, so the report holds only real candidates. In the v26 run
  (Nov 2026) that was 18 bullets, all valid: "Protein IHC" / "Human IHC" (method names),
  "kidney" for a list of kidney cell types, "leukocyte" for neutrophils and monocytes.
- If a flag is a real invented fact, fix that gene by rerunning it locally:
  `python3 scripts/summarize_gene.py output/<ID>_hpa_clean.json --outdir output`.
  Then rebuild its image request in step 5.

## 4c. Correct known errors in the summaries

Some summaries copy typos or garbled fragments from HPA's own text (e.g. "lymhoid",
"ctyoplasmic", "Poly().[supplied by OMIM…]"), and the image model then draws them
faithfully. These scripts hold the corrections found in the v26 run. Run them after
collecting the summaries, before the image rounds. Each backs up the originals to
`data/batch/summary_backup_*/`, records every change under `manual_fixes` in the summary
JSON, and is safe to rerun:

```bash
python3 scripts/fixes/summary_spelling_fixes.py   # HPA typos, in every summary
python3 scripts/fixes/summary_fixes_r2.py         # wrong facts found by the image check
python3 scripts/fixes/summary_fixes_r6.py         # truncated / garbled Entrez bullets
```

## 5. Images: generate, check, retry (rounds)

Each image is checked by Claude Opus 5.5 against the gene's HPA data, as a Vertex batch
job (the prompt is in `check_image.py`). Genes whose image fails go into the next round.
The rounds have to run **one after another**: round N+1 only contains the genes that
round N's check flagged. Within a round, all genes go into one batch.

Styles (in `visualize_gene.py`, `STYLES`): **rich** for rounds 1–2, **lineart** for round 3,
then **simple** (plainest drawing, rules first) from round 4 on. In the image prompt,
transcript counts read "N RNA transcripts" so the model doesn't draw documents for them.

The checker accepts biologically related icons. It fails misspellings, repeated labels,
wrong or merged anatomy, wrong facts, 3D protein models, chemical structures, real data
plots and paper/document icons. It is strict: before redrawing, look at a sample of the
flagged images. In the v26 run, small chemical/document icons and two kinds of intended
wording (the blood-signal verdict, the predicted location stated as fact) were accepted by
hand. Accepted genes get a row with `"flag": false` appended to that round's
`qc_rN.jsonl` and are removed from `rN_flagged.txt`.

**Claude batch setup:** our org policy blocks Claude's structured-output feature, so the
checker asks for JSON in the prompt and validates it itself. Claude batch jobs can't use
the `global` endpoint: `batch_submit.py check` runs them in `us-east5`, and their tables
live in `gene_summaries_check` in that same region (a job can't read a table from another
region).

Each round is: build image requests → image batch → export JPEGs → build check requests
(the JPEGs go inline) → check batch → collect. A check request that fails is **not**
counted as flagged: its gene goes to `check_rN_failures.txt` and is re-checked in a small
retry batch, because re-checking costs far less than redrawing.

### Round 1 (all genes, rich)

```bash
python3 scripts/batch_image_prepare.py \
    --load --table image_r1_in --out data/batch/image_r1.jsonl
python3 scripts/batch_submit.py image --src image_r1_in --dest image_r1_out
python3 scripts/batch_submit.py --status                       # wait for SUCCEEDED
caffeinate -i python3 scripts/batch_image_export.py --table image_r1_out \
    --outdir output/images_r1 --failures data/batch/image_r1_failures.txt
caffeinate -i python3 scripts/batch_check_prepare.py --images-dir output/images_r1 --table check_r1_in
python3 scripts/batch_submit.py check --src check_r1_in --dest check_r1_out
python3 scripts/batch_submit.py --status                       # wait for SUCCEEDED
python3 scripts/batch_check_collect.py --table check_r1_out \
    --out data/batch/qc_r1.jsonl --flagged-out data/batch/r1_flagged.txt \
    --failures data/batch/check_r1_failures.txt
```

- The export writes `output/images_r1/<ENSG>_<SYMBOL>.jpg` and is resumable.
- `batch_check_prepare.py` uploads in ~1 GB chunks (~8 GB for 20k images).
- **Check failures:** if `check_r1_failures.txt` is not empty, re-check just those genes and
  collect again (the new results are appended and replace the old ones):
  ```bash
  python3 scripts/batch_check_prepare.py --images-dir output/images_r1 \
      --only-keys data/batch/check_r1_failures.txt --table check_r1_retry_in
  python3 scripts/batch_submit.py check --src check_r1_retry_in --dest check_r1_retry_out
  python3 scripts/batch_check_collect.py --table check_r1_retry_out \
      --out data/batch/qc_r1.jsonl --flagged-out data/batch/r1_flagged.txt \
      --failures data/batch/check_r1_failures.txt
  ```
- **Image failures:** genes with no image at all (`image_r1_failures.txt`) go into the next
  round: `cat data/batch/image_r1_failures.txt >> data/batch/r1_flagged.txt`.
  The same retry steps apply to every round.

### Round N (the genes still flagged)

Same steps, with N and N−1 filled in and the style for that round:

```bash
python3 scripts/batch_image_prepare.py --only-keys data/batch/r1_flagged.txt --style rich \
    --load --table image_r2_in --out data/batch/image_r2.jsonl
python3 scripts/batch_submit.py image --src image_r2_in --dest image_r2_out
python3 scripts/batch_submit.py --status                       # wait for SUCCEEDED
caffeinate -i python3 scripts/batch_image_export.py --table image_r2_out \
    --outdir output/images_r2 --failures data/batch/image_r2_failures.txt
caffeinate -i python3 scripts/batch_check_prepare.py --images-dir output/images_r2 --table check_r2_in
python3 scripts/batch_submit.py check --src check_r2_in --dest check_r2_out
python3 scripts/batch_submit.py --status                       # wait for SUCCEEDED
python3 scripts/batch_check_collect.py --table check_r2_out \
    --out data/batch/qc_r2.jsonl --flagged-out data/batch/r2_flagged.txt \
    --failures data/batch/check_r2_failures.txt
cat data/batch/image_r2_failures.txt >> data/batch/r2_flagged.txt
```

Use `--style lineart` for round 3 and `--style simple` from round 4. Stop when only a few
dozen genes are left: each round fixes a smaller share of them.

### Last few genes: live, reviewed by eye

For the last genes, first check whether the error is in the summary itself (a typo or
garbled fragment copied from HPA): redrawing can't fix those, so correct the summary
(step 4c). Then draw the images live into one folder and look at each one:

```bash
python3 scripts/live_images.py data/batch/rN_flagged.txt --outdir output/images_rM --style simple
python3 scripts/live_images.py ENSG00000133119 --outdir output/images_rM   # redraw one that is still wrong
```

`live_images.py` replaces a gene's earlier image, so the folder only holds the latest
version. Record the accepted genes in `data/batch/qc_rM.jsonl` (one row per gene with
`"flag": false`) so the final step counts them as passed.

### Collect the final images

```bash
python3 scripts/finalize_images.py --outdir output/images \
    --rounds output/images_r1 output/images_r2 ... output/images_r7 \
    --checks data/batch/qc_r1.jsonl data/batch/qc_r2.jsonl ... data/batch/qc_r7.jsonl
```

- Copies each gene's image from its **latest** round into `output/images/` (one per gene).
  Build into an empty folder: files from an older run with other names are not removed.
- Writes `data/batch/manual_review.tsv`: genes whose final image still failed the check,
  with the problems the checker reported. It should be empty before you share the set.
- Afterwards the `output/images_rN/` folders can be deleted.

## 6. Package for sharing

```bash
cd output
zip -r -9 gene_summaries_json.zip *_summary.json      # ~19 MB
zip -r -0 gene_images_jpg.zip images                  # ~4.2 GB; JPEGs don't compress further
```

## Where things live

| What | Location |
|---|---|
| Raw / clean HPA data | `data/<ID>_hpa.json`, `output/<ID>_hpa_clean.json` |
| Batch inputs (local copies) | `data/batch/*_requests.jsonl`, `data/batch/image_rN.jsonl` |
| Submitted jobs log | `data/batch/jobs.jsonl` |
| Batch tables | BigQuery `scilifelab-hpa-proj-1`: `gene_summaries_batch` (text and image jobs, US), `gene_summaries_check` (Claude check jobs, us-east5) |
| Summaries | `output/<ID>_summary.md`, `output/<ID>_summary.json` |
| Summary corrections | `scripts/fixes/`; originals in `data/batch/summary_backup_*/` |
| Images per round | `output/images_rN/` (working folders) |
| Image checks per round | `data/batch/qc_rN.jsonl`, `data/batch/rN_flagged.txt`, `data/batch/check_rN_failures.txt` |
| Final images | `output/images/<ENSG>_<SYMBOL>.jpg` |
| Genes still failing | `data/batch/manual_review.tsv` |
| Failures to retry | `data/batch/text_failures.txt`, `data/batch/image_rN_failures.txt` |
