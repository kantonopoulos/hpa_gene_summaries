#!/usr/bin/env python3
"""Build the Claude image-check requests for one round and load them into BigQuery.

One request per image in --images-dir (the round's exported images): the infographic
(base64) plus the gene's cleaned HPA data, with the same prompt as check_image.py. The rows
go into a BigQuery table (custom_id = <ENSG>_<SYMBOL>, request = Claude Messages body) that a
Vertex batch job reads (batch_submit.py check). Images make the requests large (~0.4 MB
each), so the JSONL is written and loaded in chunks.

Usage
  python scripts/batch_check_prepare.py --images-dir output/images_r1 --table check_r1_in
  python scripts/batch_check_prepare.py --images-dir output/images_r2 --table check_r2_in \\
      --only-keys data/batch/some_genes.txt
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bq  # noqa: E402
import check_image  # noqa: E402

CHECK_SCHEMA = [
    {"name": "custom_id", "type": "STRING", "mode": "REQUIRED"},
    {"name": "request", "type": "JSON", "mode": "REQUIRED"},
]
ANTHROPIC_VERSION = "vertex-2023-10-16"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--images-dir", type=Path, required=True, help="folder of <ENSG>_<SYMBOL>.jpg")
    ap.add_argument("--clean-dir", type=Path, default=Path("output"))
    ap.add_argument("--table", required=True, help="BigQuery input table, e.g. check_r1_in")
    ap.add_argument("--only-keys", type=Path, help="only these Ensembl ids (one per line)")
    ap.add_argument("--out-dir", type=Path, default=Path("data/batch/check_chunks"),
                    help="where the JSONL chunks are written (deleted after loading)")
    ap.add_argument("--chunk-mb", type=int, default=1000)
    ap.add_argument("--no-load", action="store_true", help="only write the JSONL chunks")
    args = ap.parse_args(argv)

    images = sorted(args.images_dir.glob("ENSG*.jpg"))
    if args.only_keys:
        keep = set(args.only_keys.read_text().split())
        images = [p for p in images if p.name[:15] in keep]
    if not images:
        sys.exit(f"no images in {args.images_dir}")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    for old in args.out_dir.glob(f"{args.table}_*.jsonl"):
        old.unlink()
    chunks, f, size, missing = [], None, 0, []
    for img in images:
        ensg, _, symbol = img.stem.partition("_")
        clean = args.clean_dir / f"{ensg}_hpa_clean.json"
        if not clean.exists():
            missing.append(ensg)
            continue
        body = check_image.claude_request(ensg, symbol or ensg, img, clean)
        # custom_id is the image name (<ENSG>_<SYMBOL>): the job's output table has only
        # custom_id and the response, so this is how the symbol gets back to the results
        line = json.dumps({"custom_id": img.stem,
                           "request": {"anthropic_version": ANTHROPIC_VERSION, **body}}) + "\n"
        if f is None or size + len(line) > args.chunk_mb * 1e6:
            if f:
                f.close()
            chunks.append(args.out_dir / f"{args.table}_{len(chunks):03d}.jsonl")
            f, size = chunks[-1].open("w", encoding="utf-8"), 0
        f.write(line)
        size += len(line)
    f.close()
    n = len(images) - len(missing)
    total = sum(c.stat().st_size for c in chunks) / 1e6
    print(f"wrote {n} check requests in {len(chunks)} chunk(s), {total:,.0f} MB")
    if missing:
        print(f"skipped {len(missing)} images without clean data: {', '.join(missing[:10])}")

    if not args.no_load:
        rows = 0
        for i, c in enumerate(chunks):
            rows += bq.load_jsonl(c, args.table, CHECK_SCHEMA, append=i > 0, dataset=bq.CHECK_DATASET)
            c.unlink()
        print(f"{rows} rows in {bq.table_uri(args.table, bq.CHECK_DATASET)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
