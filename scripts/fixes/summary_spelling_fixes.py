#!/usr/bin/env python3
"""Fix spelling mistakes that HPA's own text carries into the v26 summaries.

Found in Nov 2026: the last images that kept failing were faithfully copying typos from
their summaries, which the summary model in turn copied from HPA text (e.g. "lymhoid",
"ctyoplasmic"). This corrects them in every summary (.json bullets, then the .md is
re-rendered). The HPA data files are left as they are.

Run from the repo root: python3 scripts/fixes/summary_spelling_fixes.py
Originals go to data/batch/summary_backup_spelling/; safe to rerun.
"""
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, "scripts")
import summarize_gene  # noqa: E402

TYPOS = {
    "syncronizes": "synchronizes", "syncronize": "synchronize", "tisssues": "tissues",
    "olidogdendrogliomas": "oligodendrogliomas", "ctyoplasmic": "cytoplasmic",
    "resistence": "resistance", "extracelullar": "extracellular", "decarboyxlase": "decarboxylase",
    "autosoml": "autosomal", "additonal": "additional", "incluidng": "including",
    "angiogensis": "angiogenesis", "lymhoid": "lymphoid", "inmusculocontractural": "musculocontractural", "cause in musculocontractural": "cause musculocontractural",
    "itssues": "tissues", "dentritic": "dendritic", "choromosomal": "chromosomal",
    "anemiasyndrome": "anemia syndrome", "nonsymdromic": "nonsyndromic", "in inesophageal": "in esophageal", "inesophageal": "in esophageal", "detected in in esophageal": "detected in esophageal",
    "hematopietic": "hematopoietic", "pseudohermaphtoditism": "pseudohermaphroditism",
    "aboundant": "abundant", "expresion": "expression", "schizophernia": "schizophrenia",
    "abundently": "abundantly", "metastatis": "metastasis", "syntesase": "synthetase",
    "autosomoal": "autosomal", "mucopolysaccaridosis": "mucopolysaccharidosis",
    "celldifferentiation": "cell differentiation", "adrenocrotical": "adrenocortical",
    "mascular dystrophy": "macular dystrophy", "dyskensia": "dyskinesia", "cytoplsmic": "cytoplasmic",
    "addiciton": "addiction", "prostrate cancer": "prostate cancer", "tocolocalize": "to colocalize",
    "transcriptionby": "transcription by", "genome-wideassociation": "genome-wide association",
    "hyroxyisobutyryl": "hydroxyisobutyryl", "cerebal": "cerebral",
    "phosphatidyetanolamline": "phosphatidylethanolamine", "Wolf-Hirschom": "Wolf-Hirschhorn",
    "dysmorhphism": "dysmorphism", "Joubert Syndrom 18": "Joubert Syndrome 18",
    "SPRYD domain containing 7": "SPRY domain containing 7", "nuclear och cytoplasmic": "nuclear and cytoplasmic",
}
PATTERN = re.compile("|".join(re.escape(k) for k in sorted(TYPOS, key=len, reverse=True)))


def main() -> int:
    out, backup = Path("output"), Path("data/batch/summary_backup_spelling")
    backup.mkdir(parents=True, exist_ok=True)
    changed = 0
    for jp in sorted(out.glob("ENSG*_summary.json")):
        d = json.loads(jp.read_text(encoding="utf-8"))
        hits = []
        for sec in d["sections"]:
            for i, b in enumerate(sec["bullets"]):
                nb = PATTERN.sub(lambda m: TYPOS[m[0]], b)
                if nb != b:
                    hits.append({"old": b, "new": nb})
                    sec["bullets"][i] = nb
        if not hits:
            continue
        ensg = d["ensembl_id"]
        for p in (jp, out / f"{ensg}_summary.md"):
            if not (backup / p.name).exists():
                shutil.copy2(p, backup / p.name)
        d.setdefault("manual_fixes", []).extend(hits)
        jp.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")
        md = summarize_gene.render(d["gene"], ensg, [(s["title"], s["bullets"]) for s in d["sections"]])
        (out / f"{ensg}_summary.md").write_text(md, encoding="utf-8")
        changed += 1
    print(f"corrected spelling in {changed} summaries (originals in {backup}/)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
