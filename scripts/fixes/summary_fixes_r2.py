#!/usr/bin/env python3
"""Manual corrections to v26 text summaries, from the round-2 image check (Nov 2026).

Opus flagged 133 round-2 images for wrong facts (hpa_accurate). Each flag was checked
against the gene's summary and its HPA data. Where the error was already in the summary,
the bullet is fixed here. (Flags whose error was only in the image need no summary change.)
Each fix is (exact old bullet, new bullet | None to delete | [several bullets]).

Run from the repo root:  python3 scripts/fixes/summary_fixes_r2.py
Originals are copied to data/batch/summary_backup_r2/ first. Safe to rerun: a fix whose
old bullet is no longer there is reported and skipped.
"""
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, "scripts")
import summarize_gene  # noqa: E402

PRAMEF_FIX = ("Predicted to be involved in negative regulation of apoptosis and transcription and in "
              "positive regulation of cell proliferation, and active in cytoplasm")

FIXES = {
    # --- family- or other-gene statements from the Entrez text, given as this gene's own ---
    "ENSG00000168515": [("Associated with prostate cancer", None)],                       # SCGB1D1
    "ENSG00000010932": [("Reduced TMA N-oxidation capacity results in fish odor syndrome Trimethylaminuria", None)],  # FMO1
    "ENSG00000131781": [("Associated with fish odor syndrome Trimethylaminuria", None)],   # FMO5
    "ENSG00000076258": [("Implicated in reduced TMA N-oxidation capacity and fish odor syndrome (Trimethylaminuria)", None)],  # FMO4
    "ENSG00000106299": [("Associated with Wiskott-Aldrich syndrome", None)],              # WASL
    "ENSG00000112290": [("Associated with Wiskott-Aldrich syndrome, a disease of the immune system", None)],  # WASF1
    "ENSG00000171786": [("Implicated in tumorigenesis through chromosomal translocations in lymphoid tumors within the helix-loop-helix family", None)],  # NHLH1
    "ENSG00000140682": [("Has a key role in male sexual differentiation", None)],         # TGFB1I1
    "ENSG00000137168": [("Associated with immunosuppression by cyclosporin A", None),
                        ("Involved in infection of HIV-1 virions", None)],               # PPIL1
    "ENSG00000197140": [("Plays a role in tumor development", None), ("Plays a role in inflammation", None),
                        ("Plays a role in brain development", None), ("Plays a role in fertilization", None)],  # ADAM32
    "ENSG00000110841": [("Important for axon guidance and mammary gland development", None)],  # PPFIBP1
    "ENSG00000149480": [("Correlated with the metastatic potential of certain carcinomas", None)],  # MTA2
    "ENSG00000142606": [("Plays roles in pain perception, arterial pressure regulation, phosphate metabolism and homeostasis", None)],  # MMEL1
    "ENSG00000077274": [("Implicated in neurodegenerative processes", None)],             # CAPN6
    "ENSG00000173542": [("Involved in spindle pole body duplication and mitotic checkpoint regulation", None)],  # MOB1B
    "ENSG00000136878": [("Linked to von Hippel-Lindau disease", None)],                   # USP20
    "ENSG00000089558": [("Associated with regulating neurotransmitter release, heart rate, and insulin secretion", None),
                        ("Implicated in regulating neuronal excitability, epithelial electrolyte transport, smooth muscle contraction, and cell volume", None)],  # KCNH4
    "ENSG00000183763": [("Associated with cylindromatosis", None)],                       # TRAIP
    "ENSG00000171206": [("E3 ubiquitin-protein ligase that participates in innate immune response, cell survival, and early-onset epileptic encephalopathy",
                         "E3 ubiquitin-protein ligase that participates in innate immune response and cell survival")],  # TRIM8
    "ENSG00000215186": [("Golgin family member located in chromosome 15 duplicons whose protein products localize to the Golgi apparatus",
                         "Golgin family member located in chromosome 15 duplicons")],   # GOLGA6B
    # --- garbled Entrez/OMIM fragments presented as diseases ---
    "ENSG00000173559": [("Single-stranded DNA is listed under named diseases and phenotypes", None)],  # NABP1
    "ENSG00000139579": [("Associated with Single-stranded DNA () supplied by OMIM, Jun 2008", None)],  # NABP2
    "ENSG00000172113": [("Associated with Nucleoside diphosphate reported in OMIM", None)],  # NME6
    "ENSG00000165309": [("Phenotype records list Armadillo/beta-catenin ().[supplied by OMIM, Mar 2008]", None)],  # ARMC3
    "ENSG00000165682": [("Associated with Natural killer ()", None)],                     # CLEC1B
    "ENSG00000054392": [("Associated with 'Skinny hedgehog'", None)],                     # HHAT
    "ENSG00000172367": [("Phenotypic associations include Guanylyl cyclase C", None)],   # PDZD3
    # --- function stated wrongly ---
    "ENSG00000279804": [("Predicted to be involved in negative regulation of apoptotic process, transcription, and cell proliferation, and active in cytoplasm", PRAMEF_FIX)],  # PRAMEF18
    "ENSG00000204505": [("Predicted to be involved in negative regulation of apoptotic process, transcription, and cell population proliferation, active in cytoplasm", PRAMEF_FIX)],  # PRAMEF9
    "ENSG00000239810": [("Predicted to be involved in negative regulation of apoptotic process, DNA-templated transcription, and positive regulation of cell population proliferation",
                         "Predicted to be involved in negative regulation of apoptosis and transcription and in positive regulation of cell proliferation")],  # PRAMEF11
    "ENSG00000164463": [("Negatively regulates the endoplasmic reticulum unfolded protein response and regulates transport and transcription by RNA polymerase II",
                         "Negatively regulates the endoplasmic reticulum unfolded protein response, positively regulates transport, and regulates transcription by RNA polymerase II")],  # CREBRF
    "ENSG00000128951": [("Leads to DNA fragmentation and cell death",
                         "Without its activity, uracil is misincorporated into DNA, leading to DNA fragmentation and cell death")],  # DUT
    "ENSG00000145113": [("Transcript variants are found only in tumor tissues", "Some transcript variants are found only in tumor tissues")],  # MUC4
    "ENSG00000182902": [("Metabolic and plasma membrane transporter protein", "Metabolic and plasma protein, and transporter")],  # SLC25A18
    "ENSG00000196449": [("Threonylcarbamoyl-AMP synthase required for forming threonylcarbamoyl groups on tRNAs that may regulate transporter activity",
                         "Threonylcarbamoyl-AMP synthase required for threonylcarbamoyl modification of tRNAs, and may regulate transporter activity")],  # YRDC
    # --- ligand merged with the transcript count ---
    "ENSG00000196187": [("Calcium, with 3 transcripts", ["Calcium-binding", "3 transcripts"])],  # TMEM63A
    "ENSG00000162623": [("S-adenosyl-L-methionine with 4 transcripts", ["S-adenosyl-L-methionine ligand", "4 transcripts"])],  # TYW3
    "ENSG00000145681": [("Hyaluronic acid with 7 transcripts", ["Hyaluronic acid ligand", "7 transcripts"])],  # HAPLN1
    # --- expression: wrong data type, wrong direction, or inverted specificity comparison ---
    "ENSG00000033122": [("Bulk RNA and single-cell RNA classifications consistently show enrichment across Brain cell types", None)],  # LRRC7
    "ENSG00000139697": [("Bulk RNA expression is Tissue enhanced in testis, showing greater specificity than Group enriched mass spectrometry in Bone marrow, Intestine",
                         "Bulk RNA expression is Tissue enhanced in testis, while mass spectrometry shows Group enriched expression in Bone marrow and Intestine")],  # SBNO1
    "ENSG00000128917": [("Expression is low in Lymphatic endothelial cells, Colonocytes, and Enteroendocrine cells",
                         "Cell type enhanced expression also in Lymphatic endothelial cells, Colonocytes, and Enteroendocrine cells")],  # DLL4
    "ENSG00000111206": [("Both RNA and protein agree on highest expression in Testis, with mainly nuclear expression in most tissues",
                         "Protein shows mainly nuclear expression in most tissues, highest in testis")],  # FOXM1
    "ENSG00000266524": [("Low RNA expression occurs in Fibroblasts, Rod photoreceptor cells, Schwann cells, Bone marrow MSCs, Retinal bipolar cells",
                         "Cell type enhanced RNA also in Fibroblasts, Rod photoreceptor cells, Schwann cells, Bone marrow MSCs, and Retinal bipolar cells")],  # GDF10
    "ENSG00000211899": [("Protein detection is Tissue enhanced in Lung, which is more specific than RNA",
                         "Mass spectrometry shows Tissue enhanced protein in Lung")],   # IGHM
    "ENSG00000136715": [("RNA expression is Tissue enhanced in Testis, showing more tissue specificity than Group enriched protein in Fallopian tube, Intestine",
                         "RNA expression is Tissue enhanced in Testis, while protein is Group enriched in Fallopian tube and Intestine")],  # SAP130
    "ENSG00000250799": [("Single-cell RNA and proteomics both demonstrate enriched expression in proximal tubule cells, hepatocytes, and glomeruli",
                         "Single-cell RNA is Group enriched in proximal tubule cells and hepatocytes, and proteomics in glomeruli and proximal tubules")],  # PRODH2
    "ENSG00000250821": [("Group enriched RNA expression is high in Early spermatids and low in Adipocytes, Retinal pigment epithelial cells, and Late spermatids",
                         "Group enriched RNA expression in Early spermatids, Adipocytes, Retinal pigment epithelial cells, and Late spermatids")],  # EXOC1L
    "ENSG00000114115": [("RNA and mass spectrometry agree on Group enriched status in Ovary and Fallopian tube, including Granulosa cells",
                         "Mass spectrometry shows Group enriched protein in Ovary and Fallopian tube, and proteomics is Cell type enhanced in Granulosa cells")],  # RBP1
    "ENSG00000125430": [("Tissue enhanced with high expression in liver and low expression in retina",
                         "RNA is Tissue enhanced in liver and retina")],                 # HS3ST3B1
    "ENSG00000140386": [("RNA is more specific than protein, which is Group enriched in Cerebral cortex, Lymphoid tissue",
                         "Protein is Group enriched in Cerebral cortex and Lymphoid tissue")],  # SCAPER
    "ENSG00000179008": [("RNA is more tissue-specific than protein, which is Group enriched in Intestine, Lung, Lymphoid tissue",
                         "Protein is Group enriched in Intestine, Lung, and Lymphoid tissue")],  # C14orf39
    "ENSG00000213420": [("RNA is also Tissue enhanced in Skin, with low expression in Lymphoid tissue",
                         "RNA is also Tissue enhanced in Skin and Lymphoid tissue")],    # GPC2
    "ENSG00000100324": [("Protein and RNA evidence agree on Low tissue specificity and Low cell type specificity",
                         "RNA shows Low tissue specificity, and RNA and proteomics show Low cell type specificity")],  # TAB1
    "ENSG00000148795": [("RNA and protein agree on Tissue enriched expression in Adrenal gland and Cell type enriched expression in Adrenal cortex cells",
                         "RNA is Tissue enriched in Adrenal gland and Cell type enriched in Adrenal cortex cells")],  # CYP17A1
    "ENSG00000167210": [("RNA appears more specific than protein, which is Tissue enriched (Lymphoid tissue) and Cell type enriched (Fallopian tube cells)",
                         "Protein is Tissue enriched (Lymphoid tissue) and Cell type enriched (Fallopian tube cells)")],  # LOXHD1
    "ENSG00000100425": [("Bulk RNA and deep visual proteomics agree on low cell type specificity alongside low tissue specificity",
                         "RNA shows low tissue specificity, and single-cell RNA and deep visual proteomics show low cell type specificity")],  # BRD1
    "ENSG00000275832": [("Cell type enhanced RNA expression is high in oligodendrocytes, and low in podocytes, papillary tip epithelial cells",
                         "Cell type enhanced RNA expression in oligodendrocytes, podocytes, and papillary tip epithelial cells")],  # ARHGAP23
    "ENSG00000197641": [("Protein is Tissue enhanced in Intestine, showing higher tissue specificity than the Group enriched RNA",
                         "Protein is Tissue enhanced in Intestine")],                    # SERPINB13
    "ENSG00000146674": [("Protein detection is Group enriched in Intestine, Lymphoid tissue, Ovary, appearing less specific than RNA",
                         "Protein detection is Group enriched in Intestine, Lymphoid tissue, and Ovary")],  # IGFBP3
    "ENSG00000179855": [("Protein detection is Tissue enriched in Lymphoid tissue, contrasting with RNA tissue specificity, showing Low cell type specificity",
                         "Mass spectrometry shows Tissue enriched protein in Lymphoid tissue")],  # GIPC3
    # --- cancer fields mixed up ---
    "ENSG00000175497": [("Exhibits Group enriched protein expression in Gastrointestinal stromal tumor and Glioblastoma multiforme, plus Group enriched in Lung cancer and Rhabdoid",
                         "Protein is Group enriched in Gastrointestinal stromal tumor and Glioblastoma multiforme, and cell lines in Lung cancer and Rhabdoid")],  # DPP10
    "ENSG00000130598": [("Protein specificity is Cancer enriched (Tongue carcinoma) with Low cancer specificity",
                         "Protein specificity is Cancer enriched (Tongue carcinoma), while cell lines show Low cancer specificity")],  # TNNI2
    # --- blood signal: several prediction models, not one ---
    "ENSG00000175065": [("Blood signal detection has low confidence because support is limited to a single prediction model",
                         "Blood signal has low confidence, as only disease prediction models flag it")],  # DSG4
    "ENSG00000105664": [("Blood signal detection has low confidence as it is supported only by a single prediction model feature",
                         "Blood signal has low confidence, as only disease prediction models flag it"),
                        ("Calcium, with 3 transcripts", ["Calcium-binding", "3 transcripts"])],  # COMP
}


def main() -> int:
    out, backup = Path("output"), Path("data/batch/summary_backup_r2")
    backup.mkdir(parents=True, exist_ok=True)
    changed, misses = 0, []
    for ensg, fixes in FIXES.items():
        jp = out / f"{ensg}_summary.json"
        for p in (jp, out / f"{ensg}_summary.md"):
            if not (backup / p.name).exists():
                shutil.copy2(p, backup / p.name)
        d = json.loads(jp.read_text(encoding="utf-8"))
        applied = []
        for old, new in fixes:
            hit = False
            for sec in d["sections"]:
                if old in sec["bullets"]:
                    i = sec["bullets"].index(old)
                    repl = [] if new is None else ([new] if isinstance(new, str) else new)
                    sec["bullets"][i:i + 1] = repl
                    hit = True
                    applied.append({"old": old, "new": new})
            if not hit:
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
