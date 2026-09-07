#!/usr/bin/env python3
"""Decide whether a named ARG was experimentally validated at the gene level.

The rule this script enforces: a gene counts as functionally validated only if
the paper's own text contains a sentence where **that gene name** and a
gene-level experiment and a susceptibility outcome appear together.

- an abstract claim is not validation
- an isolate MIC plus PCR/WGS detection is co-occurrence, not causation
- purified-enzyme kinetics without a cell phenotype is biochemical only
- no full text means `insufficient_evidence`, never `validated`

Every positive call carries the quoted sentence and its section, so a human can
check the claim instead of trusting a keyword count.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import (
    SKILL_VERSION,
    clean,
    epmc_fulltext,
    epmc_search,
    exit_code_for_run,
    mention_re,
    mentions,
    new_run_id,
    provenance,
    rotate_existing,
    split_sentences,
    utc_now,
    write_json,
    write_tsv,
)
from queries import expand_aliases

# A gene-level manipulation: the gene is moved, removed, or put back.
HOST_EXPRESSION = re.compile(
    r"clon(?:e|ed|ing)\s+(?:in|into)|ligat(?:ed|ion)\s+(?:in|into)|"
    r"transform(?:ed|ation|ants?)\b|introduc(?:ed|tion)\s+into|"
    r"heterolog(?:ous|ously)\s+(?:express|expressed|expression)|"
    r"express(?:ed|ing|ion)\s+(?:of\s+\S+\s+)?in\s+(?:E\.\s?coli|Escherichia|"
    r"K\.\s?pneumoniae|Klebsiella|P\.\s?aeruginosa|Pseudomonas|S\.\s?aureus|"
    r"Staphylococcus|Enterococcus|BL21|DH5|TOP10|J53|PAO1|M129)|"
    r"recombinant\s+(?:plasmid|strain|clone|construct|derivative|E\.\s?coli|vector)|"
    r"over-?express(?:ed|ing|ion)|(?:empty|control)\s+vector|vector[- ]only control|"
    r"harbo(?:u?r)(?:ing|ed)\s+(?:the\s+)?(?:recombinant\s+)?plasmid",
    re.I,
)
# Plasmid names are case sensitive on purpose: a case-insensitive `pCR` also
# matches the word `PCR`, which turned prevalence screening into fake evidence.
PLASMID_NAME = re.compile(r"\bp[A-Z][A-Za-z0-9]{1,10}(?:[.\-]\d+)?\b")
# Cloning and expression hosts only. AST quality-control strains such as
# ATCC 25922 are deliberately absent: they appear in surveillance papers that
# never manipulate the gene.
LAB_HOST = re.compile(
    r"\b(?:DH5\s?[a\u03b1]?|DH10B|BL21|TOP10|JM10[79]|XL1|HB101|C600|EC600|MG1655|"
    r"J53|JH2-2|RN4220|M129|NEB\s?5-?alpha|K-?12)\b",
    re.I,
)
KNOCKOUT = re.compile(
    r"knock(?:out|ed out|-out)|deletion mutant|in-frame deletion|markerless deletion|"
    r"gene disruption|disrupt(?:ed|ion) (?:of|the)|\bΔ\s?\w|allelic exchange|"
    r"CRISPR(?:i|-Cas)?[^.]{0,40}(?:silenc|knock|repress)",
    re.I,
)
COMPLEMENTATION = re.compile(
    r"complement(?:ed|ation)|trans-?complement|restor(?:ed|ation)\s+(?:the\s+)?"
    r"(?:resistance|susceptibility|phenotype|MIC)",
    re.I,
)
# The measured consequence.
OUTCOME = re.compile(
    r"\bMICs?\b|minimum inhibitory concentration|"
    r"\d+\s*-?\s*fold\s+(?:increase|decrease|higher|lower|reduction|rise)|"
    r"increas(?:ed|e)\s+(?:the\s+)?(?:MIC|resistance)|"
    r"decreas(?:ed|e)\s+(?:the\s+)?(?:MIC|susceptibilit)|"
    r"(?:conferr(?:ed|ing)|confers|showed|exhibit(?:ed|s)|displayed|demonstrated)"
    r"\s+(?:\w+\s+){0,2}resistance|"
    r"became\s+resistant|render(?:ed|ing)\s+\S+\s+resistant|"
    r"reduced\s+(?:sensitivity|susceptibility)|elevated\s+MIC|no longer susceptible|"
    r"zone of inhibition|susceptibilit(?:y|ies)\s+(?:test|restored|was restored)|"
    r"resistant to \S+ \(MIC",
    re.I,
)
BIOCHEMICAL = re.compile(
    r"purified (?:enzyme|protein|recombinant)|steady-state kinetic|kinetic parameter|"
    r"\bk\s?cat\b|\bKm\b|\bkcat/Km\b|catalytic efficiency|specific activity|"
    r"hydroly(?:sis|zed|sed|tic activity)|spectrophotometric assay|"
    r"nitrocefin|mass spectrometry[^.]{0,60}product",
    re.I,
)
TRANSFER = re.compile(
    r"conjugation|transconjugant|filter mating|mobiliz(?:ed|ation)|"
    r"transferab(?:le|ility)|electroporat(?:ed|ion) of the plasmid",
    re.I,
)
DETECTION_ONLY = re.compile(
    r"\bPCR\b|whole[- ]genome sequencing|\bWGS\b|screen(?:ed|ing) of|"
    r"prevalence|was detected in|were detected in|surveillance|isolate collection",
    re.I,
)
COMPUTATIONAL = re.compile(
    r"in silico|predicted|homology model|AlphaFold|molecular docking|"
    r"phylogenetic analysis|sequence similarity|database search|BLAST",
    re.I,
)

FOLD_CHANGE = re.compile(r"\d+\s*-?\s*fold|\bfrom\s+[\d.]+\s*(?:mg/L|µg/mL|μg/mL|mg/l)\s+to\b", re.I)
ABSTRACT_SECTIONS = {"abstract", "figure/table caption"}


def is_body(section: str) -> bool:
    return section.strip().lower() not in ABSTRACT_SECTIONS


def quote_strength(section: str, text: str) -> int:
    """Rank quotes so the clearest sentence is the one a reviewer reads first."""
    score = 0
    if is_body(section):
        score += 4
    if FOLD_CHANGE.search(text):
        score += 3
    if OUTCOME.search(text):
        score += 2
    if HOST_EXPRESSION.search(text) or KNOCKOUT.search(text) or COMPLEMENTATION.search(text):
        score += 2
    if LAB_HOST.search(text):
        score += 1
    if DETECTION_ONLY.search(text):
        score -= 2
    return score


EVIDENCE_ORDER = [
    "gene_level_causal",
    "biochemical_only",
    "mobilization_only",
    "cooccurrence_only",
    "computational_only",
    "no_evidence_found",
]

VALIDATION_BY_CLASS = {
    "gene_level_causal": "validated_gene_level",
    "biochemical_only": "not_validated_biochemical_only",
    "mobilization_only": "not_validated_transfer_only",
    "cooccurrence_only": "not_validated_cooccurrence",
    "computational_only": "not_validated_computational",
    "no_evidence_found": "not_validated_no_evidence",
}

OUTPUT_FIELDS = [
    "gene",
    "aliases",
    "pmcid",
    "full_text_available",
    "full_text_sections",
    "alias_sentences",
    "evidence_class",
    "validation_status",
    "evidence_in_body",
    "quote",
    "quote_section",
    "supporting_quotes",
    "evidence_counts",
    "date_gate",
    "novel_arg_call",
    "review_status",
    "novel_for_cutoff",
    "notes",
    "skill_version",
    "run_id",
    "error",
]


def classify_windows(windows: list[tuple[str, str]], pattern) -> tuple[str, list[dict], dict, bool]:
    """Score every alias window and return the strongest evidence class.

    A window is one or two consecutive sentences, so `The gene was cloned into
    E. coli. MICs rose 64-fold.` still counts as one piece of evidence.
    Returns the class, its best quotes, per-class counts, and whether the
    winning evidence appears anywhere outside the abstract.
    """
    counts = {name: 0 for name in EVIDENCE_ORDER}
    found: dict[str, list[dict]] = {name: [] for name in EVIDENCE_ORDER}

    for section, text in windows:
        if not mentions(text, pattern):
            continue
        manipulated = bool(
            HOST_EXPRESSION.search(text)
            or KNOCKOUT.search(text)
            or COMPLEMENTATION.search(text)
            or PLASMID_NAME.search(text)
        )
        outcome = bool(OUTCOME.search(text))
        if manipulated and outcome:
            label = "gene_level_causal"
        elif TRANSFER.search(text) and outcome:
            # Moving a whole plasmid carries other genes too, so this is weaker.
            label = "mobilization_only"
        elif LAB_HOST.search(text) and outcome:
            # `DH5a carrying the gene showed resistance` is a construct, not an isolate.
            label = "gene_level_causal"
        elif BIOCHEMICAL.search(text):
            label = "biochemical_only"
        elif DETECTION_ONLY.search(text):
            label = "cooccurrence_only"
        elif COMPUTATIONAL.search(text):
            label = "computational_only"
        else:
            continue
        counts[label] += 1
        found[label].append(
            {"section": section, "quote": text[:600], "strength": quote_strength(section, text)}
        )

    for label in EVIDENCE_ORDER:
        if not counts[label]:
            continue
        hits = sorted(found[label], key=lambda q: -q["strength"])
        in_body = any(is_body(q["section"]) for q in hits)
        return label, hits[:3], counts, in_body
    return "no_evidence_found", [], counts, False


def build_windows(sections: list[tuple[str, str]]) -> list[tuple[str, str]]:
    windows: list[tuple[str, str]] = []
    for section, text in sections:
        sentences = split_sentences(text)
        for i, sentence in enumerate(sentences):
            windows.append((section, sentence))
            if i + 1 < len(sentences):
                windows.append((section, f"{sentence} {sentences[i + 1]}"))
    return windows


def find_pmcid(aliases: list[str]) -> str:
    """Locate an open-access record that names the gene in title or abstract."""
    query = "(" + " OR ".join(f'TITLE:"{a}" OR ABSTRACT:"{a}"' for a in aliases[:6]) + ")"
    page = epmc_search(f"{query} AND (HAS_FT:Y OR OPEN_ACCESS:Y)", page_size=25, max_pages=2)
    pattern = mention_re(aliases)
    for row in page.rows:
        if not row.get("pmcid"):
            continue
        if mentions(clean(row.get("title", "")), pattern) or mentions(clean(row.get("abstractText", "")), pattern):
            return row["pmcid"]
    return ""


def novel_call(date_gate: str, validation_status: str) -> str:
    """Both gates must pass, and only with a quoted sentence on file."""
    if date_gate in {"formal_before_since", "preprint_before_since", "article_before_since"}:
        return "drop_earlier_public_record"
    if validation_status == "insufficient_evidence":
        return "hold_no_full_text"
    if validation_status in {"validated_gene_level_abstract_only", "abstract_claim_only"}:
        return "hold_abstract_only_evidence"
    if validation_status != "validated_gene_level":
        return "hold_not_gene_level_evidence"
    if date_gate == "no_earlier_record_found":
        return "pass_date_gate_and_gene_level_evidence"
    if date_gate:
        return "hold_date_gate_unresolved"
    return "hold_date_gate_not_run"


def review_one(gene: str, aliases: list[str], pmcid: str, date_gate: str, allow_abstract: bool, run_id: str) -> dict:
    variants = expand_aliases(aliases)
    pattern = mention_re(variants)
    notes: list[str] = []

    if not pmcid:
        pmcid = find_pmcid(variants)
        if pmcid:
            notes.append(f"pmcid resolved by search: {pmcid}")
        else:
            notes.append("no open-access PMC record found for this name")

    sections: list[tuple[str, str]] = []
    available = False
    if pmcid:
        full = epmc_fulltext(pmcid)
        available = full.available
        sections = full.sections
        pmcid = full.pmcid
        if full.error:
            notes.append(f"full text error: {full.error}")

    if not available:
        if not allow_abstract:
            return {
                "gene": gene,
                "aliases": ";".join(aliases),
                "pmcid": pmcid,
                "full_text_available": False,
                "full_text_sections": 0,
                "alias_sentences": 0,
                "evidence_class": "no_full_text",
                "validation_status": "insufficient_evidence",
                "evidence_in_body": False,
                "quote": "",
                "quote_section": "",
                "supporting_quotes": "[]",
                "evidence_counts": "{}",
                "date_gate": date_gate,
                "novel_arg_call": novel_call(date_gate, "insufficient_evidence"),
                "review_status": "machine_screen",
                "novel_for_cutoff": False,
                "notes": "; ".join(notes) or "full text not available",
                "skill_version": SKILL_VERSION,
                "run_id": run_id,
                "error": "",
            }
        notes.append("no full text; --allow-abstract was set so the abstract was used")

    windows = build_windows(sections)
    alias_windows = [w for w in windows if mentions(w[1], pattern)]
    evidence_class, quotes, counts, in_body = classify_windows(windows, pattern)
    validation_status = VALIDATION_BY_CLASS[evidence_class]

    if validation_status == "validated_gene_level" and not in_body:
        # The paper claims it in the summary but the body never repeats it.
        validation_status = "validated_gene_level_abstract_only"
        notes.append("gene-level wording appears only in the abstract or a caption")
    if not available and allow_abstract and validation_status.startswith("validated"):
        validation_status = "abstract_claim_only"
        notes.append("no full text; claim comes from the abstract alone")

    top = quotes[0] if quotes else {"section": "", "quote": ""}
    return {
        "gene": gene,
        "aliases": ";".join(aliases),
        "pmcid": pmcid,
        "full_text_available": available,
        "full_text_sections": len(sections),
        "alias_sentences": len(alias_windows),
        "evidence_class": evidence_class,
        "validation_status": validation_status,
        "evidence_in_body": in_body,
        "quote": top["quote"],
        "quote_section": top["section"],
        "supporting_quotes": json.dumps(quotes, ensure_ascii=False),
        "evidence_counts": json.dumps(counts, ensure_ascii=False),
        "date_gate": date_gate,
        "novel_arg_call": novel_call(date_gate, validation_status),
        "review_status": "machine_screen",
        "novel_for_cutoff": False,
        "notes": "; ".join(notes),
        "skill_version": SKILL_VERSION,
        "run_id": run_id,
        "error": "",
    }


def parse_genes(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if not reader.fieldnames or "gene" not in reader.fieldnames:
            raise SystemExit(f"{path} must be a TSV with a gene column")
        for row in reader:
            gene = (row.get("gene") or "").strip()
            if not gene:
                continue
            rows.append(
                {
                    "gene": gene,
                    "aliases": [a.strip() for a in (row.get("aliases") or gene).split(";") if a.strip()],
                    "pmcid": (row.get("pmcid") or "").strip(),
                }
            )
    return rows


def load_date_gates(path: Path | None) -> dict[str, str]:
    if not path:
        return {}
    with path.open(encoding="utf-8", newline="") as handle:
        return {
            (row.get("gene") or "").strip(): (row.get("date_gate") or "").strip()
            for row in csv.DictReader(handle, delimiter="\t")
            if (row.get("gene") or "").strip()
        }


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Check whether each named ARG has gene-level experimental validation in the paper text"
    )
    ap.add_argument("--genes", type=Path, required=True, help="TSV with gene, aliases, optional pmcid")
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--crossvalidate", type=Path, help="crossvalidate.tsv, to join the date gate")
    ap.add_argument(
        "--allow-abstract",
        action="store_true",
        help="Classify from the abstract when no full text exists. Caps the call at abstract_claim_only.",
    )
    args = ap.parse_args()

    run_id = new_run_id()
    meta_path = args.output.with_name(args.output.stem + ".run.json")
    rotated = [p for p in (rotate_existing(args.output, run_id), rotate_existing(meta_path, run_id)) if p]

    items = parse_genes(args.genes)
    gates = load_date_gates(args.crossvalidate)
    meta = provenance("validate_evidence.py")
    meta.update(
        {
            "run_id": run_id,
            "started_at": utc_now(),
            "finished_at": "",
            "genes_file": str(args.genes),
            "crossvalidate_file": str(args.crossvalidate) if args.crossvalidate else "",
            "allow_abstract": args.allow_abstract,
            "rotated_previous": rotated,
            "n_input": len(items),
            "n_written": 0,
            "errors": [],
        }
    )
    write_json(meta_path, meta)
    write_tsv(args.output, [], OUTPUT_FIELDS)

    results: list[dict] = []
    for item in items:
        try:
            row = review_one(
                item["gene"],
                item["aliases"],
                item["pmcid"],
                gates.get(item["gene"], ""),
                args.allow_abstract,
                run_id,
            )
        except Exception as exc:  # noqa: BLE001 — keep the rest of the run
            row = {field: "" for field in OUTPUT_FIELDS}
            row.update(
                {
                    "gene": item["gene"],
                    "aliases": ";".join(item["aliases"]),
                    "pmcid": item["pmcid"],
                    "full_text_available": False,
                    "evidence_class": "error",
                    "validation_status": "insufficient_evidence",
                    "date_gate": gates.get(item["gene"], ""),
                    "novel_arg_call": "hold_no_full_text",
                    "review_status": "machine_screen",
                    "novel_for_cutoff": False,
                    "skill_version": SKILL_VERSION,
                    "run_id": run_id,
                    "error": str(exc),
                }
            )
            meta["errors"].append({"gene": item["gene"], "error": str(exc)})
        results.append(row)
        write_tsv(args.output, results, OUTPUT_FIELDS)
        meta["n_written"] = len(results)
        write_json(meta_path, meta)
        print(
            f"{row['validation_status']:32} {row['gene']:12} "
            f"{row['evidence_class']:20} {row['novel_arg_call']}"
        )
        if row["quote"]:
            print(f"    [{row['quote_section']}] {row['quote'][:160]}")

    code = exit_code_for_run(errors=meta["errors"], incomplete=False)
    meta["finished_at"] = utc_now()
    meta["exit_code"] = code
    meta["validation_counts"] = {
        status: sum(1 for row in results if row["validation_status"] == status)
        for status in sorted({row["validation_status"] for row in results})
    }
    write_json(meta_path, meta)
    passed = sum(1 for row in results if row["novel_arg_call"] == "pass_date_gate_and_gene_level_evidence")
    print(f"wrote {args.output} ({len(results)} rows, {passed} passed both gates)")
    print("A pass means a quoted sentence exists. Read the quote before reporting the gene.")
    print(f"run metadata: {meta_path}")
    if rotated:
        print("rotated previous: " + "; ".join(rotated))
    if code:
        print(f"PROCESS_FAILED: {len(meta['errors'])} gene(s) raised; exit {code}", file=sys.stderr)
        raise SystemExit(code)


if __name__ == "__main__":
    main()
