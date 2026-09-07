#!/usr/bin/env python3
"""Title/abstract screen for candidate novel-ARG papers.

A candidate is not a novel ARG and not experimental validation.
This step only decides whether a hit is worth naming genes for date-gate review.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import SKILL_VERSION, exit_code_for_run, new_run_id, provenance, rotate_existing, utc_now, write_json, write_tsv

ARG = re.compile(
    r"antibiotic|antimicrobial|antibacterial|multidrug|beta.lactam|β.lactam|carbapenem|"
    r"cephalosporin|penicillin|monobactam|avibactam|cefiderocol|"
    r"colistin|polymyxin|aminoglycoside|gentamicin|apramycin|plazomicin|"
    r"fosfomycin|macrolide|azithromycin|erythromycin|tetracycline|"
    r"tigecycline|eravacycline|chloramphenicol|phenicol|florfenicol|"
    r"linezolid|oxazolidinone|vancomycin|glycopeptide|teicoplanin|"
    r"daptomycin|lipopeptide|bacitracin|quinolone|fluoroquinolone|ciprofloxacin|"
    r"rifampi[cn]in|sulfonamide|sulfamethoxazole|trimethoprim|nitrofurantoin|"
    r"mupirocin|fusidic acid|novobiocin|aminocoumarin|fidaxomicin|bleomycin|"
    r"spectinomycin|streptomycin|lincosamide|streptogramin|pleuromutilin|"
    r"efflux pump|ribosomal protection|"
    # Gene tokens need a family suffix or number. Bare stems match author names
    # ("van Dijk") and unrelated acronyms ("Ugi MCR").
    r"\bbla(?:KPC|NDM|OXA|IMP|VIM|SHV|TEM|CTX|CMY|GES|PER|VEB|SPM|ADC|HMB|BAS|GUA|CAE|Z)\b|"
    r"\b(?:mcr|kpc|ndm|oxa|shv|tem|ctx-m|cmy|ges|imp|vim|hmb|qnr|arr)-\d|"
    r"\b(?:qepA|oqxAB|optrA|poxtA|armA|npmA|apmA|tmexCD|floR|fexA|fexB|estT|sat4)\b|"
    r"\b(?:erm|mef|msr|mph|ere|lsa|vga|vgb|sal|cfr|tet|fos|qac)\([A-Z]\d*\)|"
    r"\b(?:van[ABCDGMN]|sul[1-4]|dfrA|rmt[A-H]|aadA|catA|catB|Ngt)\b|"
    r"\b(?:aph|aac|ant)\(\d",
    re.I,
)
NOVEL = re.compile(
    r"\bnovel\b|\bnew\b|newly|uncharacteri[sz]ed|undescribed|unreported|unrecognized|"
    r"first.{0,35}(?:characteri[sz]|identif|report|descri)|discovery|"
    r"variant|allele|family member|designated|herein named|we named",
    re.I,
)
FUNCTION = re.compile(
    r"functional|characteri[sz]|susceptibility|\bMICs?\b|minimum inhibitory|"
    r"complementation|deletion|knockout|knock-out|heterolog|clon(?:e|ed|ing)|"
    r"express(?:ed|ion)|transform(?:ed|ant)|conjugation|transconjugant|"
    r"biochemical|kinetic|hydroly|confer|inactivat|purified (?:enzyme|protein)",
    re.I,
)
REVIEW = re.compile(
    r"\b(review|meta-analysis|systematic review|research progress|perspective|"
    r"scoping review|narrative review|mini-review)\b|"
    r"\b(?:advances|progress|frontiers|insights) (?:in|on)\b|"
    r"\bstate of the art\b|\bwhat we know\b",
    re.I,
)
OFFTOPIC = re.compile(
    r"sp\.\s*nov\.|\bphage\b|endolysin|drug discovery|antibacterial activity|"
    r"antimicrobial activity|antimicrobial efficacy|\binhibitor\b|synthesis of|"
    r"antimicrobial peptide|anti-?cancer|antitumor|antitumour|antifungal|"
    r"ferroptosis|\bapoptot|essential oil|plant extract|nanoparticle|"
    r"machine learning|deep learning|probiotic",
    re.I,
)
KNOWN_REPORT = re.compile(
    r"first (?:report|detection|identification|isolation|description) of .{0,80}"
    r"(?:in |from )|new plasmid|new sequence type|first .{0,40}(?:prevalence|detection)",
    re.I,
)
NOVEL_GENE = re.compile(
    r"novel.{0,65}(?:resistance gene|resistance determinant|lactamase|carbapenemase|"
    r"transferase|hydrolase|esterase|efflux pump|allele|variant|enzyme)|"
    r"designated|herein named|we named|"
    r"previously uncharacteri[sz]ed.{0,35}(?:gene|resistan)",
    re.I,
)

PASSTHROUGH = [
    "key",
    "id",
    "source",
    "source_db",
    "journal",
    "first_publication_date",
    "date_precision",
    "in_window",
    "is_preprint",
    "queries",
    "url",
]

OUTPUT_FIELDS = [
    "title",
    "abstract",
    "publication_types",
    "pmid",
    "doi",
    *PASSTHROUGH,
    "screen_status",
    "screen_score",
    "screen_reasons",
    "evidence_hint",
    "arg_keyword",
    "novelty_keyword",
    "function_keyword",
    "promoted",
    "skill_version",
    "run_id",
]


GENE_NAME = re.compile(
    r"\b(?:bla)?(?:KPC|NDM|OXA|IMP|VIM|SHV|TEM|CTX-M|CMY|GES|PER|VEB|HMB|BAS|GUA|CAE)-\d+\b|"
    r"\b(?:mcr|fosA|fosB|fosL|sul|dfr|van|erm|mef|msr|mph|arr|rmt|tet|lsa|vga|sal|"
    r"optrA|poxtA|cfr|aad|estT|ngt)[-(]?[A-Za-z0-9.)]*-?\d+(?:\.\d+)?\b|"
    r"\b(?:ant|aph|aac)\(\d+[^)]*\)-[A-Za-z]+\b|"
    r"\btet\([A-Z]\d*\)|\blsa\([A-Z]\)|\bvga\([A-Z]\)",
    re.I,
)


GENE_LEVEL = re.compile(
    r"heterolog|complementation|knock(?:out|-out)|deletion mutant|"
    r"clon(?:e|ed|ing) into|transform(?:ed|ant)|transconjugant|"
    r"expressed in (?:E\.? ?coli|Escherichia)|recombinant plasmid",
    re.I,
)


def screen_text(title: str, abstract: str = "", publication_types: str = "") -> dict:
    title = title or ""
    abstract = abstract or ""
    types = publication_types or ""
    corpus = f"{title} {abstract}"
    reasons: list[str] = []
    arg_hit = bool(ARG.search(corpus))
    novel_hit = bool(NOVEL.search(corpus))
    function_hit = bool(FUNCTION.search(corpus))

    if REVIEW.search(title) or "review" in types.lower() or "meta-analysis" in types.lower():
        reasons.append("review_or_meta")
        status = "exclude_review"
    elif OFFTOPIC.search(title):
        reasons.append("offtopic_title")
        status = "exclude_offtopic"
    elif KNOWN_REPORT.search(title) and not NOVEL_GENE.search(corpus):
        reasons.append("known_gene_or_local_first_report")
        status = "exclude_known_report"
    elif arg_hit and (novel_hit or NOVEL_GENE.search(corpus)) and function_hit:
        reasons.append("arg_novelty_and_function_language")
        status = "review_candidate"
    elif arg_hit and NOVEL_GENE.search(corpus):
        reasons.append("novel_gene_language_without_function_words")
        status = "review_candidate_weak"
    elif arg_hit and novel_hit and GENE_NAME.search(corpus):
        reasons.append("named_gene_with_novelty_language")
        status = "review_candidate_weak"
    elif arg_hit or novel_hit:
        reasons.append("keywords_without_full_screen")
        status = "not_candidate"
    else:
        reasons.append("no_arg_or_novelty_language")
        status = "not_candidate"

    named_gene = bool(GENE_NAME.search(corpus))
    novel_gene = bool(NOVEL_GENE.search(corpus))
    gene_level = bool(GENE_LEVEL.search(corpus))

    score = 0
    if status in {"review_candidate", "review_candidate_weak"}:
        score += 20
        score += 30 if named_gene else 0
        score += 20 if novel_gene else 0
        score += 15 if gene_level else 0
        score += 10 if function_hit else 0
        score += 5 if NOVEL_GENE.search(title) or GENE_NAME.search(title) else 0

    return {
        "screen_status": status,
        "screen_score": score,
        "screen_reasons": ";".join(reasons),
        "evidence_hint": "gene_level_language" if gene_level else ("function_language" if function_hit else ""),
        "arg_keyword": arg_hit,
        "novelty_keyword": novel_hit,
        "function_keyword": function_hit,
        "promoted": status == "review_candidate",
    }


def parse_rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if not reader.fieldnames or "title" not in reader.fieldnames:
            raise SystemExit(f"{path} must be a TSV with a title column")
        return [row for row in reader]


def main() -> None:
    ap = argparse.ArgumentParser(description="Screen literature hits for novel-ARG review candidates")
    ap.add_argument("--input", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    run_id = new_run_id()
    meta_path = args.output.with_name(args.output.stem + ".run.json")
    rotated = [p for p in (rotate_existing(args.output, run_id), rotate_existing(meta_path, run_id)) if p]

    try:
        incoming = parse_rows(args.input)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"failed to read {args.input}: {exc}") from exc

    results = []
    errors = []
    for row in incoming:
        title = (row.get("title") or "").strip()
        if not title:
            errors.append({"error": "missing_title"})
            out = {field: "" for field in OUTPUT_FIELDS}
            out.update(row)
            out["screen_status"] = "insufficient_evidence"
            out["screen_score"] = 0
            out["screen_reasons"] = "missing_title"
            out["evidence_hint"] = ""
            out["promoted"] = False
            out["skill_version"] = SKILL_VERSION
            out["run_id"] = run_id
            results.append(out)
            continue
        verdict = screen_text(title, row.get("abstract", ""), row.get("publication_types", ""))
        out = {field: row.get(field, "") for field in OUTPUT_FIELDS}
        for field in PASSTHROUGH:
            out[field] = row.get(field, "")
        out.update(verdict)
        out["title"] = title
        out["abstract"] = row.get("abstract", "")
        out["publication_types"] = row.get("publication_types", "")
        out["pmid"] = row.get("pmid", "")
        out["doi"] = row.get("doi", "")
        out["skill_version"] = SKILL_VERSION
        out["run_id"] = run_id
        results.append(out)

    # Best-looking candidates first, so a wide sweep stays readable.
    results.sort(
        key=lambda row: (
            -int(row.get("screen_score") or 0),
            str(row.get("first_publication_date") or "9999"),
        )
    )
    write_tsv(args.output, results, OUTPUT_FIELDS)
    code = exit_code_for_run(errors=errors, incomplete=False)
    meta = provenance("screen_candidates.py")
    meta.update(
        {
            "run_id": run_id,
            "finished_at": utc_now(),
            "n_input": len(incoming),
            "n_written": len(results),
            "n_promoted": sum(1 for row in results if row.get("promoted") in {True, "True"}),
            "n_weak": sum(1 for row in results if row.get("screen_status") == "review_candidate_weak"),
            "n_with_abstract": sum(1 for row in results if row.get("abstract")),
            "status_counts": {
                status: sum(1 for row in results if row.get("screen_status") == status)
                for status in sorted({row.get("screen_status", "") for row in results})
            },
            "errors": errors,
            "rotated_previous": rotated,
            "exit_code": code,
        }
    )
    write_json(meta_path, meta)
    promoted = sum(1 for r in results if r.get("promoted") in {True, "True"})
    weak = sum(1 for r in results if r.get("screen_status") == "review_candidate_weak")
    print(f"wrote {args.output} ({len(results)} rows, {promoted} promoted, {weak} weak)")
    if code:
        print(f"PROCESS_FAILED: exit {code}", file=sys.stderr)
        raise SystemExit(code)


if __name__ == "__main__":
    main()
