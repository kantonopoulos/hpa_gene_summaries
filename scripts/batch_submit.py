#!/usr/bin/env python3
"""Submit / check Vertex AI batch prediction jobs that read from and write to BigQuery.

Submitted jobs are appended to data/batch/jobs.jsonl so they can be looked up later.

Usage
  python scripts/batch_submit.py text                 # text_in  -> text_out  (gemini-3.8-flash)
  python scripts/batch_submit.py image                # image_in -> image_out (gemini-3-pro-image)
  python scripts/batch_submit.py check --src check_r1_in --dest check_r1_out   # Claude Opus image check
  python scripts/batch_submit.py text --src text_retry_in --dest text_retry_out
  python scripts/batch_submit.py --status             # state of every recorded job
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from google import genai
from google.genai import types

sys.path.insert(0, str(Path(__file__).resolve().parent))
import summarize_gene  # noqa: E402
import visualize_gene  # noqa: E402
import bq  # noqa: E402
import check_image  # noqa: E402

JOBS_LOG = Path("data/batch/jobs.jsonl")
KINDS = {
    "text": (summarize_gene.DEFAULT_MODEL, "text_in", "text_out"),
    "image": (visualize_gene.DEFAULT_MODEL, "image_in", "image_out"),
    "check": (f"publishers/anthropic/models/{check_image.DEFAULT_MODEL}", "check_in", "check_out"),
}
# Gemini jobs run on the global endpoint against the US dataset; Claude batch jobs need a
# regional endpoint and a dataset in that same region.
LOCATIONS = {"check": "us-east5"}
DATASETS = {"check": bq.CHECK_DATASET}
_clients: dict[str, genai.Client] = {}


def client(location: str = "global") -> genai.Client:
    if location not in _clients:
        _clients[location] = genai.Client(vertexai=True, project=summarize_gene.VERTEX_PROJECT,
                                          location=location)
    return _clients[location]


def submit(kind: str, src: str | None = None, dest: str | None = None) -> None:
    model, default_src, default_dest = KINDS[kind]
    src, dest = src or default_src, dest or default_dest
    location = LOCATIONS.get(kind, "global")
    dataset = DATASETS.get(kind, bq.DATASET)
    job = client(location).batches.create(
        model=model,
        src=bq.table_uri(src, dataset),
        config=types.CreateBatchJobConfig(
            dest=bq.table_uri(dest, dataset),
            display_name=f"gene-summaries-{kind}-{dt.date.today()}",
        ),
    )
    rec = {"kind": kind, "name": job.name, "model": model, "location": location, "src": src, "dest": dest,
           "submitted": dt.datetime.now(dt.timezone.utc).isoformat()}
    JOBS_LOG.parent.mkdir(parents=True, exist_ok=True)
    with JOBS_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
    print(f"submitted {kind}: {job.name}  state={job.state.name}")


def status() -> None:
    if not JOBS_LOG.exists():
        print("no jobs recorded")
        return
    for line in JOBS_LOG.read_text(encoding="utf-8").splitlines():
        rec = json.loads(line)
        j = client(rec.get("location", "global")).batches.get(name=rec["name"])
        stats = j.completion_stats
        counts = (f"ok={stats.successful_count} failed={stats.failed_count} "
                  f"incomplete={stats.incomplete_count}") if stats else ""
        print(f"{rec['kind']:6} {rec['submitted'][:16]}  {j.state.name:22} {counts}  {rec['name']}")
        if j.error:
            print(f"       error: {j.error}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("kind", nargs="?", choices=sorted(KINDS))
    ap.add_argument("--src", help="input table (default text_in / image_in)")
    ap.add_argument("--dest", help="output table (default text_out / image_out)")
    ap.add_argument("--status", action="store_true")
    args = ap.parse_args(argv)
    if args.status or not args.kind:
        status()
    else:
        submit(args.kind, args.src, args.dest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
