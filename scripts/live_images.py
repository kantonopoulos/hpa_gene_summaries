#!/usr/bin/env python3
"""Generate infographics live (not as a batch) for a short list of genes.

For the last few genes that keep failing: each image is written to --outdir as
<ENSG>_<SYMBOL>.jpg, replacing any earlier one, so the folder only ever holds the latest
version. Review the images and rerun with the genes that are still wrong.

Usage
  python scripts/live_images.py data/batch/r7_todo.txt --outdir output/images_r7 --style simple
  python scripts/live_images.py ENSG00000116745 ENSG00000131944 --outdir output/images_r7
"""
from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import batch_image_export as bie  # noqa: E402
import visualize_gene as vg  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("genes", nargs="+", help="Ensembl ids, or a file with one id per line")
    ap.add_argument("--outdir", type=Path, required=True)
    ap.add_argument("--style", default="simple", choices=sorted(vg.STYLES))
    ap.add_argument("--summary-dir", type=Path, default=Path("output"))
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args(argv)

    ids: list[str] = []
    for g in args.genes:
        ids += Path(g).read_text().split() if Path(g).is_file() else [g]
    symbols = bie.gene_symbols(args.summary_dir)
    args.outdir.mkdir(parents=True, exist_ok=True)
    vg.get_client()  # one shared client before the threads start

    def one(ensg: str) -> str:
        md = (args.summary_dir / f"{ensg}_summary.md").read_text(encoding="utf-8")
        prompt = vg.build_prompt(md, args.style)
        for attempt in range(4):
            try:
                data = vg.call_gemini_image(vg.DEFAULT_MODEL, prompt)
                break
            except Exception as exc:  # disconnects, 429, 5xx, no image returned
                if attempt == 3:
                    return f"FAILED {ensg}: {type(exc).__name__}"
                time.sleep(10 * (attempt + 1))
        for old in args.outdir.glob(f"{ensg}*.jpg"):  # keep only the newest version
            old.unlink()
        (args.outdir / bie.filename(ensg, symbols.get(ensg))).write_bytes(data)
        return f"ok {ensg}"

    with ThreadPoolExecutor(args.workers) as pool:
        results = list(pool.map(one, ids))
    failed = [r for r in results if r.startswith("FAILED")]
    print(f"{len(ids) - len(failed)} images written to {args.outdir}/")
    for r in failed:
        print(r)
    return 0


if __name__ == "__main__":
    sys.exit(main())
