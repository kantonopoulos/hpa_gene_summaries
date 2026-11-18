#!/usr/bin/env python3
"""Read a finished Claude image-check batch and write the round's QC results.

Reads the output table of a `batch_submit.py check` job, validates each reply against the
check schema (check_image.ImageQC) and writes one row per gene to --out, in the same format
as check_image.py. Genes whose image failed any check go to --flagged-out, for the next
round.

A request that failed or whose reply can't be parsed is NOT flagged: its id goes to
--failures, and those genes are checked again in a small retry batch (re-checking is far
cheaper than redrawing the image).

Usage
  python scripts/batch_check_collect.py --table check_r1_out \\
      --out data/batch/qc_r1.jsonl --flagged-out data/batch/r1_flagged.txt \\
      --failures data/batch/check_r1_failures.txt
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bq  # noqa: E402
import check_image  # noqa: E402

PAGE = 500


def as_json(v):
    return json.loads(v) if isinstance(v, str) and v else v


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--table", required=True, help="the job's BigQuery output table, e.g. check_r1_out")
    ap.add_argument("--out", type=Path, required=True, help="QC JSONL (appended to)")
    ap.add_argument("--flagged-out", type=Path, required=True)
    ap.add_argument("--failures", type=Path, required=True)
    args = ap.parse_args(argv)

    model = f"{check_image.DEFAULT_MODEL} (batch)"
    rows, failures = [], []
    start = 0
    while True:
        page = bq.list_rows(args.table, start, PAGE, dataset=bq.CHECK_DATASET)
        if not page:
            break
        start += len(page)
        for r in page:
            ensg, _, symbol = r["custom_id"].partition("_")  # custom_id = <ENSG>_<SYMBOL>
            symbol = symbol or ensg
            response = as_json(r.get("response"))
            if not response or r.get("status"):
                failures.append((ensg, f"status: {str(r.get('status'))[:200]}"))
                continue
            text = "".join(b.get("text", "") for b in response.get("content", []) if b.get("type") == "text")
            qc = check_image.parse_reply(text)
            if qc is None:
                failures.append((ensg, f"unparsable reply, stop_reason={response.get('stop_reason')}"))
                continue
            usage = response.get("usage", {})
            rows.append(check_image.finish_row(
                {"ensg": ensg, "symbol": symbol, "model": model,
                 "input_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens")},
                qc))
        print(f"  read {start} rows", flush=True)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")

    # Flagged = every gene whose LATEST row in --out is flagged (so a retry batch appended
    # later replaces the earlier result for that gene).
    latest: dict[str, dict] = {}
    for line in args.out.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            latest[row["ensg"]] = row
    flagged = sorted(e for e, row in latest.items() if row.get("flag"))
    args.flagged_out.write_text("".join(f"{e}\n" for e in flagged))
    args.failures.write_text("".join(f"{e}\n" for e, _ in failures))

    tin = sum(r["input_tokens"] or 0 for r in rows)
    tout = sum(r["output_tokens"] or 0 for r in rows)
    print(f"{len(rows)} checked ({sum(r['flag'] for r in rows)} flagged) -> {args.out}")
    print(f"{len(flagged)} flagged in total -> {args.flagged_out}")
    print(f"{len(failures)} failed requests -> {args.failures}")
    for e, why in failures[:5]:
        print(f"    {e}: {why}")
    print(f"tokens: input {tin:,}  output {tout:,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
