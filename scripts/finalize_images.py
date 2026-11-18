#!/usr/bin/env python3
"""Pick each gene's final infographic after the check-and-retry rounds.

Every round writes its images to its own folder and its checks to its own JSONL (see
docs/batch_pipeline.md). For each gene this takes the image from the LATEST round that has
one, copies it to the final folder, and lists the genes whose final image still failed the
check in a review file, with the problems the checker reported.

Usage
  python scripts/finalize_images.py \\
      --rounds output/images_r1 output/images_r2 output/images_r3 \\
      --checks data/batch/qc_r1.jsonl data/batch/qc_r2.jsonl data/batch/qc_r3.jsonl
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

CHECKS = ("hpa_accurate", "text_clean", "illustration_ok")


def latest_rows(path: Path) -> dict[str, dict]:
    """Last check row per gene in a QC JSONL (a later row for a gene replaces an earlier one)."""
    rows: dict[str, dict] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                rows[row["ensg"]] = row
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rounds", nargs="+", type=Path, required=True, help="image folders, round 1 first")
    ap.add_argument("--checks", nargs="+", type=Path, required=True, help="QC JSONL per round, same order")
    ap.add_argument("--outdir", type=Path, default=Path("output/images"))
    ap.add_argument("--review", type=Path, default=Path("data/batch/manual_review.tsv"))
    args = ap.parse_args(argv)
    if len(args.rounds) != len(args.checks):
        ap.error("--rounds and --checks need the same number of entries")

    final: dict[str, tuple[int, Path]] = {}  # ensg -> (round index, image path)
    for i, folder in enumerate(args.rounds):
        for img in folder.glob("ENSG*.jpg"):
            final[img.name[:15]] = (i, img)
    checks = [latest_rows(p) for p in args.checks]

    args.outdir.mkdir(parents=True, exist_ok=True)
    review, per_round = [], [0] * len(args.rounds)
    for ensg, (i, img) in sorted(final.items()):
        shutil.copy2(img, args.outdir / img.name)
        per_round[i] += 1
        row = checks[i].get(ensg)
        if row is None or row.get("flag"):
            problems = "not checked" if row is None else "; ".join(
                p for k in CHECKS for p in row.get(k, {}).get("problems", [])) or row.get("error", "")
            review.append(f"{ensg}\t{row.get('symbol', '') if row else ''}\tround {i + 1}\t{problems}")

    args.review.parent.mkdir(parents=True, exist_ok=True)
    args.review.write_text("ensg\tsymbol\tfinal_round\tproblems\n" + "".join(r + "\n" for r in review),
                           encoding="utf-8")
    print(f"{len(final)} images -> {args.outdir}/ "
          f"({', '.join(f'round {i + 1}: {n}' for i, n in enumerate(per_round))})")
    print(f"{len(review)} still flagged or unchecked -> {args.review}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
