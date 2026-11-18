#!/usr/bin/env python3
"""Automated QC of gene infographics with Claude on Vertex AI.

For each gene, Claude gets the infographic and the cleaned HPA data and answers three
yes/no checks:

  hpa_accurate       Text on the image contains no misinformation versus the HPA data
  text_clean         Text on the image has no misspellings, garbled words, duplicates or cut-off sentences
  illustration_ok    Illustrations are not misleading, wrong or weird

Each check carries a short list of the problems found (empty when it passes). A gene is
flagged for a rerun when any check fails.

Usage (live spot check of one or a few genes)
  python scripts/check_image.py HSD17B1 PEG10 ABCA13
  python scripts/check_image.py ENSG00000108786 --images-dir output/images_r4

The full runs check images as Vertex batch jobs (batch_check_prepare.py ->
batch_submit.py check -> batch_check_collect.py, see docs/batch_pipeline.md), which use
the prompt and parser defined here. Calling this script directly checks images live, at
full price: only for spot checks of single genes.
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

from anthropic import AnthropicVertex
from pydantic import BaseModel, Field

VERTEX_PROJECT = "scilifelab-hpa-proj-1"
VERTEX_REGION = "global"
DEFAULT_MODEL = "claude-opus-5-5"
ROOT = Path(__file__).resolve().parent.parent
IMAGES_DIR = ROOT / "output" / "images"
CLEAN_DIR = ROOT / "output"

SYSTEM_PROMPT = """You check infographics about human genes before they are published on the
Human Protein Atlas (HPA). You get one infographic and the HPA data it was made from. Answer
three yes/no checks. Judge only the image: its text and its illustrations.

The goal is to catch images that need to be redrawn, not to polish good ones. Most images
are fine. Fail a check only for a clear error that a scientist reading the image would
notice and object to. When in doubt, pass.

1. hpa_accurate: Does the image's text avoid misinformation?
   Fail only when the text clearly contradicts the HPA data: a wrong tissue, cell type,
   location, disease, number or function, or a fact stated as the opposite of the data.
   The text was written by a model that combines and interprets the HPA data, so these are
   fine and must not fail: short connecting or theme labels (e.g. "Signaling", "Pathways"),
   reasonable summaries or inferences drawn from the data, rephrasing, simplification,
   facts left out, and the subtitle's general framing.

2. text_clean: Is the text free of clear rendering problems? Fail for misspelled or garbled
   words, letters that do not form words, a label or section heading repeated by mistake,
   sentences that stop mid-way, and text that is cut off or overlaps so it can't be read.
   Do not fail for style, capitalisation, or awkward but readable wording.

3. illustration_ok: Are the illustrations free of misleading or clearly wrong content? Fail
   when an illustration shows the wrong organ, tissue, cell type or compartment for the label
   it is attached to, when anatomy is badly wrong, when a symbol clearly implies something
   false, or when something looks broken or nonsensical. Absurd combinations always fail,
   for example a male symbol drawn over or merged with female reproductive organs, organs
   fused into anatomy that cannot exist, or a body part placed inside a structure where it
   cannot be (such as a bone inside a blood vessel). Also fail for any 3D protein structure
   rendering (ribbon or surface model), chemical structure or formula, a real data plot
   with axes or values, or a paper or document icon. A protein drawn as a simple schematic
   shape (e.g. a receptor in a membrane) is fine. Small biologically related icons are fine
   too, including petri dishes, test tubes, simple decorative bar icons and gel or blot
   symbols; only fail an icon if it is unrelated to biology or clearly misleading.
   Do not fail for stylisation, artistic simplification, decorative elements, or drawings
   that are loosely related.

Read all text in the image carefully. For each check, list each clear problem as a short
phrase that quotes the text or names the visual element. A check passes only when its list
is empty."""


class Check(BaseModel):
    problems: list[str] = Field(description="Short phrases, one per problem; empty when the check passes")
    passed: bool


class ImageQC(BaseModel):
    hpa_accurate: Check
    text_clean: Check
    illustration_ok: Check


def find_gene(key: str, images_dir: Path = IMAGES_DIR,
              clean_dir: Path = CLEAN_DIR) -> tuple[str, str, Path, Path]:
    """Resolve an Ensembl ID or gene symbol to (ensg, symbol, image, clean_json).

    Images are <ENSG>_<SYMBOL>.jpg, or <ENSG>.jpg for genes without a symbol."""
    if key.startswith("ENSG"):
        matches = sorted(images_dir.glob(f"{key}_*.jpg")) + sorted(images_dir.glob(f"{key}.jpg"))
    else:
        matches = sorted(images_dir.glob(f"*_{key}.jpg"))
    if len(matches) != 1:
        raise SystemExit(f"{key}: expected one image in {images_dir}, found {len(matches)}")
    image = matches[0]
    ensg, _, symbol = image.stem.partition("_")
    symbol = symbol or ensg
    clean = clean_dir / f"{ensg}_hpa_clean.json"
    if not clean.exists():
        raise SystemExit(f"{key}: missing {clean}")
    return ensg, symbol, image, clean


def user_text(symbol: str, ensg: str, hpa: str) -> str:
    return f"HPA data for {symbol} ({ensg}):\n<hpa_data>\n{hpa}\n</hpa_data>"


def claude_request(ensg: str, symbol: str, image: Path, clean: Path) -> dict:
    """The Claude Messages body for one check (without "model"). Used both for a live call
    and, with "anthropic_version" added, as a row of a Vertex batch job (batch_check_prepare.py).

    Our Vertex org policy blocks Claude's structured-outputs feature, so the reply format is
    asked for in the prompt and validated by parse_reply()."""
    image_b64 = base64.standard_b64encode(image.read_bytes()).decode()
    schema = json.dumps(ImageQC.model_json_schema())
    return {
        "max_tokens": 16000,
        "system": [{"type": "text", "text": SYSTEM_PROMPT}],
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": user_text(symbol, ensg, clean.read_text())},
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image_b64}},
                {"type": "text", "text": "Run the three checks on this infographic. Reply with only a JSON "
                                         f"object that matches this schema, and nothing else:\n{schema}"},
            ],
        }],
    }


def parse_reply(text: str) -> ImageQC | None:
    """Validate Claude's JSON reply (fences stripped); None when it doesn't match the schema."""
    text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        return ImageQC.model_validate_json(text)
    except ValueError:
        return None


def finish_row(row: dict, qc: ImageQC) -> dict:
    checks = qc.model_dump()
    # A check passes only with no problems listed, whatever the model's bool says.
    for c in checks.values():
        c["passed"] = c["passed"] and not c["problems"]
    row.update(checks)
    row["flag"] = not all(c["passed"] for c in checks.values())
    return row


def check_gene(client: AnthropicVertex, model: str, ensg: str, symbol: str,
               image: Path, clean: Path) -> dict:
    """One live check (full price): for spot checks only; full runs use the batch scripts."""
    response = client.messages.create(model=model, **claude_request(ensg, symbol, image, clean))
    row = {"ensg": ensg, "symbol": symbol, "model": model,
           "input_tokens": response.usage.input_tokens,
           "output_tokens": response.usage.output_tokens}
    qc = parse_reply("".join(b.text for b in response.content if b.type == "text"))
    if qc is None:
        row.update(error=f"stop_reason={response.stop_reason}; unparsable reply", flag=True)
        return row
    return finish_row(row, qc)


def print_row(row: dict) -> None:
    status = "FLAG" if row["flag"] else "ok"
    print(f"{status:4}  {row['symbol']} ({row['ensg']})", file=sys.stderr)
    for name in ("hpa_accurate", "text_clean", "illustration_ok"):
        for p in row.get(name, {}).get("problems", []):
            print(f"      {name}: {p}", file=sys.stderr)
    if "error" in row:
        print(f"      error: {row['error']}", file=sys.stderr)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("genes", nargs="+", help="Gene symbols or Ensembl IDs")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--out", type=Path, help="also append the result rows to this JSONL file")
    ap.add_argument("--clean-dir", type=Path, default=CLEAN_DIR,
                    help="Folder of <ENSG>_hpa_clean.json files (the HPA data to check against)")
    ap.add_argument("--images-dir", type=Path, default=IMAGES_DIR,
                    help="Folder of <ENSG>_<SYMBOL>.jpg infographics")
    args = ap.parse_args()

    client = AnthropicVertex(project_id=VERTEX_PROJECT, region=VERTEX_REGION)
    for key in args.genes:
        ensg, symbol, image, clean = find_gene(key, args.images_dir, args.clean_dir)
        row = check_gene(client, args.model, ensg, symbol, image, clean)
        print_row(row)
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            with args.out.open("a") as f:
                f.write(json.dumps(row) + "\n")


if __name__ == "__main__":
    main()
