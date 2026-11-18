#!/usr/bin/env python3
"""Manual corrections to v26 summaries whose bullet came from a truncated or garbled HPA
Entrez text (found when their images kept failing, round 6, Nov 2026).

Each fix is (section title, exact old bullet, new bullet | None to delete). Run from the
repo root: python3 scripts/fixes/summary_fixes_r6.py. Originals go to
data/batch/summary_backup_r6/ first; safe to rerun.
"""
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, "scripts")
import summarize_gene  # noqa: E402

DIS = "DISEASE & CLINICAL RELEVANCE"
FIXES = {
    "ENSG00000129951": [("IDENTITY & FUNCTION", "The proteins in the lipid phosphate phosphatase [supplied by OMIM, Mar 2008]", None)],  # PLPPR3
    "ENSG00000178685": [(DIS, "Listed with phenotype record Poly().[supplied by OMIM, Mar 2008] in Entrez", None)],  # PARP10
    "ENSG00000241360": [(DIS, "Associated with Pyridoxal 5-prime-phosphate ()", None)],                         # PDXP
    "ENSG00000186815": [(DIS, "Associated with Voltage-gated Ca() in OMIM records", None)],                      # TPCN1
    "ENSG00000116745": [(DIS, "Mutations are associated with early-onset severe blinding disorders such as Leber congenital",
                         "Mutations are associated with early-onset severe blinding disorders")],            # RPE65
    "ENSG00000131944": [(DIS, "Component of the Fanconi anemia", None)],                                         # FAAP24
    "ENSG00000275395": [(DIS, "Located in extracellular exosome", None)],                                        # FCGBP
    "ENSG00000165685": [(DIS, "Located in extracellular exosome", None)],                                        # TMEM52B
    "ENSG00000170396": [("IDENTITY & FUNCTION", "Zinc finger binding protein with polymorphisms, especially rs1344706, thought to confer increased susceptibility to schizophrenia, bipolar disorder, and heroin addiction",
                         "Zinc finger binding protein")],                                                          # ZNF804A (repeated the disease bullet)
}


def main() -> int:
    out, backup = Path("output"), Path("data/batch/summary_backup_r6")
    backup.mkdir(parents=True, exist_ok=True)
    changed, misses = 0, []
    for ensg, fixes in FIXES.items():
        jp = out / f"{ensg}_summary.json"
        for p in (jp, out / f"{ensg}_summary.md"):
            if not (backup / p.name).exists():
                shutil.copy2(p, backup / p.name)
        d = json.loads(jp.read_text(encoding="utf-8"))
        applied = []
        for title, old, new in fixes:
            sec = next((s for s in d["sections"] if s["title"] == title), None)
            if sec and old in sec["bullets"]:
                i = sec["bullets"].index(old)
                sec["bullets"][i:i + 1] = [] if new is None else [new]
                applied.append({"section": title, "old": old, "new": new})
            else:
                misses.append((ensg, old))
        if not applied:
            continue
        d["sections"] = [s for s in d["sections"] if s["bullets"]]
        d.setdefault("manual_fixes", []).extend(applied)
        jp.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")
        md = summarize_gene.render(d["gene"], ensg, [(s["title"], s["bullets"]) for s in d["sections"]])
        (out / f"{ensg}_summary.md").write_text(md, encoding="utf-8")
        changed += 1
    print(f"fixed {changed} summaries (originals in {backup}/)")
    for ensg, old in misses:
        print(f"  not found in {ensg}: {old[:90]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
