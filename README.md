# HPA gene summaries

Generates a short, fact-grounded summary and an infographic for every gene in the
[Human Protein Atlas](https://www.proteinatlas.org) (version 26). It uses Gemini and Claude
on Vertex AI.

For each gene:

1. **Fetch** its HPA page and JSON.
2. **Clean** the data down to the fields the summaries use.
3. **Summarize** it with `gemini-3.8-flash`, one call per section:
   - Identity & function
   - Expression
   - Protein localization
   - Disease & clinical relevance

   The model may only state what is in the HPA data. `check_grounding.py` flags summary
   terms that are not in the data.
4. **Visualize** the summary as a 16:9 JPEG with `gemini-3-pro-image`.
5. **Check** each image with Claude Opus 5.5 against the HPA data: wrong facts, text errors
   (misspellings, repeated labels) and misleading illustrations (wrong anatomy, chemical or
   3D protein structures, document icons). Images that fail are redrawn, with a simpler
   style in later rounds, until they pass.

## Setup

- Python 3 with `google-genai`, `google-auth`, `requests`, `beautifulsoup4`, `Pillow`,
  `anthropic[vertex]`, `pydantic`
- Vertex AI credentials for project `scilifelab-hpa-proj-1`; see
  [docs/setup_gemini_vertex_ai.md](docs/setup_gemini_vertex_ai.md). Claude Opus 5.5 must be
  enabled in Vertex AI Model Garden.

## One gene (local)

```bash
python3 scripts/fetch_hpa.py ENSG00000146648 --outdir data
python3 scripts/clean_hpa.py data/ENSG00000146648_hpa.json --outdir output
python3 scripts/summarize_gene.py output/ENSG00000146648_hpa_clean.json
python3 scripts/visualize_gene.py output/ENSG00000146648_summary.md
```

`visualize_gene.py --style rich|lineart|simple` picks the image style (rich by default).

## All genes (batch)

The full run of about 20k genes uses Vertex AI batch jobs (half the standard price) that
run on Google's side: one text batch, then rounds of image batches, each followed by a
Claude check batch. Genes whose image fails go into the next round. Step-by-step commands,
progress checks, retries, timings and costs are in
**[docs/batch_pipeline.md](docs/batch_pipeline.md)**.

## Scripts

| Script | Purpose |
|---|---|
| `fetch_hpa.py` / `clean_hpa.py` | Fetch / clean one gene |
| `fetch_all.py` | Fetch + clean every gene in `data/proteinatlas.tsv` (resumable) |
| `summarize_gene.py` | Summary prompts and formatting rules; summarizes one gene |
| `visualize_gene.py` | Infographic prompt and the three styles; draws one gene |
| `check_grounding.py` | Flags summary terms that are not in the source data |
| `check_image.py` | Image-check prompt, schema and parser; live spot check of a few genes |
| `batch_text_prepare.py` → `batch_submit.py text` → `batch_text_collect.py` | Text batch: build input, submit, collect summaries |
| `batch_image_prepare.py` → `batch_submit.py image` → `batch_image_export.py` | Image batch: build input, submit, download JPEGs |
| `batch_check_prepare.py` → `batch_submit.py check` → `batch_check_collect.py` | Image-check batch (Claude, us-east5): build input, submit, collect results |
| `live_images.py` | Draws a few images live (last round, reviewed by eye) |
| `finalize_images.py` | Picks each gene's latest passing image into `output/images/` |
| `fixes/` | Corrections to known errors in the summaries (HPA typos, garbled Entrez text) |
| `bq.py` | BigQuery helpers for the batch scripts |

Prompts live in `summarize_gene.py`, `visualize_gene.py` and `check_image.py`. Local runs
and batches both use them, so a change there applies to both.

## Outputs

`data/` and `output/` are gitignored.

| Path | Content |
|---|---|
| `data/<ID>_hpa.json` | Raw HPA page + JSON |
| `output/<ID>_hpa_clean.json` | Cleaned input to the summarizer |
| `output/<ID>_summary.md` / `.json` | Summary (Markdown) / structured version with token usage and any manual fixes |
| `output/images/<ID>_<SYMBOL>.jpg` | Final infographic, one per gene |
| `output/<ID>_visual.jpg` | Infographic from a local `visualize_gene.py` run |
