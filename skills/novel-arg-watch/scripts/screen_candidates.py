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
    r"antibiotic|antimicrobial|antibacterial|beta.lactam|β.lactam|carbapenem|"
    r"colistin|polymyxin|aminoglycoside|fosfomycin|macrolide|tetracycline|"
    r"tigecycline|chloramphenicol|linezolid|fluoroquinolone|spectinomycin|"
    r"streptomycin|lincosamide|streptogramin|pleuromutilin|"
    r"\b(?:mcr|bla|kpc|ndm|oxa|shv|ctx-m|qnr|erm|tet|fos|lsa|aad|aph|aac|ant|cfr)\b",
    re.I,
)
NOVEL = re.compile(
    r"\bnovel\b|\bnew\b|newly|uncharacteri[sz]ed|undescribed|unrecognized|"
    r"first.{0,35}(?:characteri[sz]|identif|report)|discovery|variant|allele|designated",
    re.I,
)
FUNCTION = re.compile(
    r"functional|characteri[sz]|susceptibility|\bMICs?\b|minimum inhibitory|"
    r"complementation|deletion|knockout|heterolog|clon(?:e|ed|ing)|"
    r"biochemical|kinetic|hydroly|conferr",
    re.I,
)
REVIEW = re.compile(r"\b(review|meta-analysis|systematic review|research progress)\b", re.I)
OFFTOPIC = re.compile(
    r"sp\.\s*nov\.|\bphage\b|drug discovery|antibacterial activity|"
    r"antimicrobial activity|antimicrobial efficacy|\binhibitor\b|synthesis of",
    re.I,
)
KNOWN_REPORT = re.compile(
    r"first (?:report|detection|identification|isolation|description) of .{0,80}"
    r"(?:in |from )|new plasmid|new sequence type|first .{0,40}(?:prevalence|detection)",
    re.I,
)
NOVEL_GENE = re.compile(
    r"novel.{0,65}(?:resistance gene|resistance determinant|lactamase|transferase|allele)|"
    r"designated|previously uncharacteri[sz]ed.{0,35}(?:gene|resistan)",
    re.I,
)

OUTPUT_FIELDS = [
    "title",
    "abstract",
    "publication_types",
    "pmid",
    "doi",
    "screen_status",
    "screen_reasons",
    "arg_keyword",
    "novelty_keyword",
    "function_keyword",
    "promoted",
    "skill_version",
    "run_id",
]


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
    elif arg_hit or novel_hit:
        reasons.append("keywords_without_full_screen")
        status = "not_candidate"
    else:
        reasons.append("no_arg_or_novelty_language")
        status = "not_candidate"

    return {
        "screen_status": status,
        "screen_reasons": ";".join(reasons),
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
            out["screen_reasons"] = "missing_title"
            out["promoted"] = False
            out["skill_version"] = SKILL_VERSION
            out["run_id"] = run_id
            results.append(out)
            continue
        verdict = screen_text(title, row.get("abstract", ""), row.get("publication_types", ""))
        out = {field: row.get(field, "") for field in OUTPUT_FIELDS}
        out.update(verdict)
        out["title"] = title
        out["abstract"] = row.get("abstract", "")
        out["publication_types"] = row.get("publication_types", "")
        out["pmid"] = row.get("pmid", "")
        out["doi"] = row.get("doi", "")
        out["skill_version"] = SKILL_VERSION
        out["run_id"] = run_id
        results.append(out)

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
            "errors": errors,
            "rotated_previous": rotated,
            "exit_code": code,
        }
    )
    write_json(meta_path, meta)
    print(f"wrote {args.output} ({len(results)} rows, {sum(1 for r in results if r.get('promoted') in {True, 'True'})} promoted)")
    if code:
        print(f"PROCESS_FAILED: exit {code}", file=sys.stderr)
        raise SystemExit(code)


if __name__ == "__main__":
    main()
