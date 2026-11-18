#!/usr/bin/env python3
"""Turn a gene's Markdown summary (<ID>_summary.md) into an infographic image.

Uses Gemini 3 Pro Image ("Nano Banana Pro") via Vertex AI (see
scripts/docs/setup_gemini_vertex_ai.md). The full summary Markdown is handed to the
model together with a fixed style-guide prompt; the model draws a 16:9 infographic
from it directly (no layout logic here — that's the model's job). One shot here; the
check-and-retry rounds are in check_image.py and docs/batch_pipeline.md.

Usage
  python scripts/visualize_gene.py output/ENSG00000254647_summary.md
  python scripts/visualize_gene.py output/ENSG00000254647_summary.md --outdir output
  python scripts/visualize_gene.py output/ENSG00000254647_summary.md --style lineart
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from google import genai
from google.genai import types

VERTEX_PROJECT = "scilifelab-hpa-proj-1"
VERTEX_LOCATION = "global"  # regional locations 404 on these models
DEFAULT_MODEL = "gemini-3-pro-image"
ASPECT_RATIO = "16:9"
# JPEG q90: ~0.28 MB vs ~1.5 MB PNG per infographic, text stays sharp
OUTPUT_MIME = "image/jpeg"
JPEG_QUALITY = 90

_client: genai.Client | None = None


def get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(vertexai=True, project=VERTEX_PROJECT, location=VERTEX_LOCATION)
    return _client


# Two image styles. "rich" is the default; "lineart" is the fallback for genes whose
# rich image still fails the image check after two attempts (see docs/batch_pipeline.md).
RICH_STYLE = """STYLE:
- Title: the TITLE in bold, left-aligned, with a short subtitle on the protein's role.
- Layout: one central illustration of a single thing: the organ, tissue or cell where this
  protein matters most, or the protein itself in its setting (e.g. a receptor in a
  membrane, or a signalling protein), drawn as a simple schematic shape. The sections sit
  around it as separate labelled zones, each with its own small drawing if useful. Don't
  connect the sections with vessels, streams or pathways; use thin callout lines only where
  they point at something in a drawing.
- Look: rich, polished scientific illustration with soft shading and depth, in a colour
  palette chosen to suit this protein's role, on a clean off-white background (hex F8F9FA)
  with at most a subtle glow behind the central illustration.
- Text: short, in a clean, high-contrast sans-serif font."""

RICH_RULES = """RULES:
- Spell every word correctly, and show each fact and heading only once.
- Draw organs and cells correctly and separately; never merge them into one structure or
  place one inside another.
- Never draw 3D protein structures (ribbon or surface models) or chemical structures and
  formulas. No real data plots and no paper or document icons.
- No markdown symbols such as #, - or * in the image."""

LINEART_STYLE = """STYLE:
- Title: the TITLE in bold, left-aligned, with a short subtitle on the protein's role.
- Layout: one central illustration of a single thing (one organ, one cell, or the protein in
  its setting drawn as a simple schematic shape). The sections sit around it as separate labelled
  zones, each with its own small drawing if useful. Use thin callout lines only where they point at something in a drawing.
- Look: flat 2D scientific line art. Thin, even charcoal outlines and flat fills in 3-4 soft,
  muted colours picked to suit this protein, so different genes get different palettes (e.g.
  sage, slate blue, sand, dusty rose, lavender, terracotta, ochre, teal, plum) on a plain
  off-white background (hex F8F9FA). No gradients, glows, shadows or 3D.
- Text: short, in a clean dark sans-serif font."""

LINEART_RULES = """RULES:
- Spell every word correctly, and show each fact and heading only once.
- Draw organs and cells correctly and separately; never merge them into one structure.
- Never draw protein structures (ribbon or surface models) or chemical structures and
  formulas, not even as small icons. No real data plots and no paper or document icons.
- No markdown symbols such as #, - or * in the image."""

# "simple" is the last fallback (round 4): a plainer drawing, so the model's effort goes
# into following the rules.
SIMPLE_STYLE = """STYLE:
- Title: the TITLE in bold, left-aligned, with a short subtitle.
- Layout: one simple central drawing (one organ, one cell, or the protein as a simple
  shape in its setting). Each section sits in its own labelled zone around it.
- Look: flat 2D line art with thin charcoal outlines and 3-4 soft colours on a plain
  off-white background (hex F8F9FA). Use few small icons, or none.
- Text: short, in a clean dark sans-serif font."""

SIMPLE_RULES = """RULES (most important):
- Copy every word exactly as given, spelled correctly. Show each fact and heading once.
- No chemical structures, formulas or molecules, and no protein structures (ribbons or
  surfaces), not even as small icons.
- No paper, document or clipboard icons, and no charts or plots.
- Draw anatomy correctly: each organ or cell on its own, in the right place, never merged.
- No markdown symbols such as #, - or * in the image."""

STYLES = {"rich": (RICH_STYLE, RICH_RULES), "lineart": (LINEART_STYLE, LINEART_RULES),
          "simple": (SIMPLE_STYLE, SIMPLE_RULES)}
DEFAULT_STYLE = "rich"

_NUM = r"\d+|One|Two|Three|Four|Five|Six|Seven|Eight|Nine|Ten"


def rna_transcripts(text: str) -> str:
    """'6 transcripts' -> '6 RNA transcripts' (and 'Transcript count of 6' likewise), so the
    image model reads them as RNA molecules rather than documents."""
    text = re.sub(r"\bTranscript count of (\d+)", lambda m: f"{m[1]} RNA transcript" + ("" if m[1] == "1" else "s"), text)
    return re.sub(rf"\b({_NUM}) (transcripts?)\b", r"\1 RNA \2", text)


def strip_markdown(summary_md: str) -> str:
    """Convert '# Title' / '## SECTION' / '- bullet' into plain structural labels,
    so the model never sees literal '#'/'-' characters to (mis)render as glyphs."""
    lines = []
    for line in summary_md.splitlines():
        if line.startswith("## "):
            lines.append(f"SECTION LABEL: {line[3:].strip()}")
        elif line.startswith("# "):
            lines.append(f"TITLE: {line[2:].strip()}")
        elif line.startswith("- "):
            lines.append(f"FACT: {line[2:].strip()}")
        elif line.strip():
            lines.append(line.strip())
    return "\n".join(lines)


def build_prompt(summary_md: str, style: str = DEFAULT_STYLE) -> str:
    style_guide, rules = STYLES[style]
    structured = rna_transcripts(strip_markdown(summary_md))
    return (
        f"Create a single infographic image ({ASPECT_RATIO} aspect ratio) summarizing this gene, "
        "using ONLY the facts below. Do not invent facts not present here. The labels "
        "below (TITLE, SECTION LABEL, FACT) describe each line's ROLE only — render its "
        "content as clean designed typography, never the label word itself. Give every "
        "SECTION LABEL its own clearly labelled zone in the artwork — do not skip or "
        "merge sections.\n\n"
        f"{style_guide}\n\n"
        f"{rules}\n\n"
        f"GENE SUMMARY:\n{structured}"
    )


def call_gemini_image(model: str, prompt: str) -> bytes:
    resp = get_client().models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_modalities=["IMAGE", "TEXT"],
            image_config=types.ImageConfig(
                aspect_ratio=ASPECT_RATIO,
                output_mime_type=OUTPUT_MIME,
                output_compression_quality=JPEG_QUALITY,
            ),
        ),
    )
    for part in resp.candidates[0].content.parts:
        if part.inline_data:
            return part.inline_data.data
    raise RuntimeError("model returned no image")


def batch_request_image(prompt: str) -> dict:
    """The same call as call_gemini_image, as a Vertex batch GenerateContentRequest
    (REST/camelCase). Keep the two in sync."""
    return {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseModalities": ["IMAGE", "TEXT"],
            "imageConfig": {
                "aspectRatio": ASPECT_RATIO,
                "imageOutputOptions": {"mimeType": OUTPUT_MIME, "compressionQuality": JPEG_QUALITY},
            },
        },
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("summary_md", help="path to <ID>_summary.md")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--outdir", default=None)
    ap.add_argument("--style", default=DEFAULT_STYLE, choices=sorted(STYLES))
    args = ap.parse_args(argv)

    path = Path(args.summary_md)
    summary_md = path.read_text(encoding="utf-8")
    ensembl_id = path.name.split("_")[0]

    prompt = build_prompt(summary_md, args.style)
    print("call  gemini-3-pro-image ...", flush=True)
    image_bytes = call_gemini_image(args.model, prompt)

    outdir = Path(args.outdir) if args.outdir else path.parent
    outdir.mkdir(parents=True, exist_ok=True)
    out_path = outdir / f"{ensembl_id}_visual.jpg"
    out_path.write_bytes(image_bytes)
    print(f"wrote {out_path}  ({out_path.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
