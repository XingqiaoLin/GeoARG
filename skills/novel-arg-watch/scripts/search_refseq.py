#!/usr/bin/env python3
"""Search NCBI RefSeq protein and nucleotide records for named ARGs.

The search is restricted with ``srcdb_refseq[PROP]``. It returns record
metadata for review; it does not use a RefSeq record date as proof that a gene
name existed on that date and it does not make a novelty call.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import (
    SKILL_VERSION,
    clean,
    eutils_esearch,
    eutils_esummary,
    exit_code_for_run,
    new_run_id,
    provenance,
    rotate_existing,
    utc_now,
    write_json,
    write_tsv,
)

REFSEQ_FILTER = "srcdb_refseq[PROP]"
DATABASES = ("protein", "nuccore")

OUTPUT_FIELDS = [
    "input_gene",
    "matched_terms",
    "query_sources",
    "database",
    "uid",
    "accession",
    "title",
    "organism",
    "taxid",
    "length",
    "molecule_type",
    "completeness",
    "create_date",
    "update_date",
    "refseq_source",
    "skill_version",
    "run_id",
    "error",
]


def split_values(value: str) -> list[str]:
    """Split the semicolon/comma-separated values used by the genes TSV."""
    values: list[str] = []
    for part in (value or "").replace(",", ";").split(";"):
        item = clean(part)
        if item and item not in values:
            values.append(item)
    return values


def refseq_query(term: str, *, accession: bool = False) -> str:
    """Build an exact Entrez query restricted to RefSeq records."""
    value = clean(term)
    if not value:
        raise ValueError("empty RefSeq search term")
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    field = "Accession" if accession else "All Fields"
    return f'"{escaped}"[{field}] AND {REFSEQ_FILTER}'


def add_spec(
    specs: list[dict],
    seen: set[tuple[str, str, bool]],
    *,
    gene: str,
    term: str,
    source: str,
    accession: bool,
) -> None:
    value = clean(term)
    key = (clean(gene), value.casefold(), accession)
    if not value or key in seen:
        return
    seen.add(key)
    specs.append(
        {
            "input_gene": clean(gene) or value,
            "term": value,
            "query_source": source,
            "query": refseq_query(value, accession=accession),
        }
    )


def load_specs(
    terms: list[str], accessions: list[str], genes_path: Path | None
) -> list[dict]:
    """Load repeatable CLI terms plus aliases/accessions from a genes TSV."""
    specs: list[dict] = []
    seen: set[tuple[str, str, bool]] = set()
    for term in terms:
        add_spec(specs, seen, gene=term, term=term, source="term", accession=False)
    for accession in accessions:
        add_spec(
            specs,
            seen,
            gene=accession,
            term=accession,
            source="accession",
            accession=True,
        )

    if genes_path is not None:
        with genes_path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            if not reader.fieldnames or "gene" not in reader.fieldnames:
                raise SystemExit("--genes TSV needs a gene column")
            for row in reader:
                gene = clean(row.get("gene", ""))
                if not gene:
                    continue
                for accession in split_values(row.get("accessions", "")):
                    add_spec(
                        specs,
                        seen,
                        gene=gene,
                        term=accession,
                        source="accession",
                        accession=True,
                    )
                aliases = split_values(row.get("aliases", ""))
                for alias in [gene] + aliases:
                    add_spec(
                        specs,
                        seen,
                        gene=gene,
                        term=alias,
                        source="gene_or_alias",
                        accession=False,
                    )
    return specs


def summary_row(item: dict, spec: dict, database: str, run_id: str) -> dict:
    return {
        "input_gene": spec["input_gene"],
        "matched_terms": spec["term"],
        "query_sources": spec["query_source"],
        "database": database,
        "uid": clean(str(item.get("uid") or "")),
        "accession": clean(
            str(item.get("accessionversion") or item.get("caption") or "")
        ),
        "title": clean(str(item.get("title") or "")),
        "organism": clean(str(item.get("organism") or "")),
        "taxid": clean(str(item.get("taxid") or "")),
        "length": clean(str(item.get("slen") or item.get("length") or "")),
        "molecule_type": clean(
            str(item.get("moltype") or item.get("biomol") or "")
        ),
        "completeness": clean(str(item.get("completeness") or "")),
        "create_date": clean(str(item.get("createdate") or "")),
        "update_date": clean(str(item.get("updatedate") or "")),
        "refseq_source": clean(str(item.get("sourcedb") or "")),
        "skill_version": SKILL_VERSION,
        "run_id": run_id,
        "error": "",
    }


def merge_rows(rows: list[dict]) -> list[dict]:
    """Collapse the same RefSeq record reached through several aliases."""
    merged: dict[tuple[str, str, str], dict] = {}
    for row in rows:
        key = (row["input_gene"], row["database"], row["accession"] or row["uid"])
        if key not in merged:
            merged[key] = dict(row)
            continue
        current = merged[key]
        for field in ("matched_terms", "query_sources"):
            values = [v for v in current[field].split(";") if v]
            for value in row[field].split(";"):
                if value and value not in values:
                    values.append(value)
            current[field] = ";".join(values)
    return sorted(
        merged.values(),
        key=lambda row: (row["input_gene"].casefold(), row["database"], row["accession"]),
    )


def error_row(spec: dict, database: str, run_id: str, error: str) -> dict:
    row = {field: "" for field in OUTPUT_FIELDS}
    row.update(
        {
            "input_gene": spec["input_gene"],
            "matched_terms": spec["term"],
            "query_sources": spec["query_source"],
            "database": database,
            "skill_version": SKILL_VERSION,
            "run_id": run_id,
            "error": error,
        }
    )
    return row


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Search NCBI RefSeq protein and nucleotide records by gene, alias, or accession"
    )
    ap.add_argument("--term", action="append", default=[], help="gene name or phrase; repeatable")
    ap.add_argument("--accession", action="append", default=[], help="exact RefSeq accession; repeatable")
    ap.add_argument("--genes", type=Path, help="genes TSV with gene and optional aliases/accessions columns")
    ap.add_argument(
        "--db",
        choices=("both",) + DATABASES,
        default="both",
        help="RefSeq database to search (default: both)",
    )
    ap.add_argument(
        "--max-results",
        type=int,
        default=20,
        help="maximum records per query and database (default: 20)",
    )
    ap.add_argument("--output", type=Path, required=True, help="output TSV")
    args = ap.parse_args()

    if args.max_results < 1 or args.max_results > 1000:
        raise SystemExit("--max-results must be between 1 and 1000")
    specs = load_specs(args.term, args.accession, args.genes)
    if not specs:
        raise SystemExit("provide --term, --accession, or --genes with at least one gene")

    run_id = new_run_id()
    databases = DATABASES if args.db == "both" else (args.db,)
    rows: list[dict] = []
    errors: list[dict] = []
    searches: list[dict] = []
    incomplete = False

    for spec in specs:
        for database in databases:
            audit = {
                "input_gene": spec["input_gene"],
                "term": spec["term"],
                "query_source": spec["query_source"],
                "database": database,
                "query": spec["query"],
                "reported": 0,
                "retrieved": 0,
                "complete": False,
                "error": "",
            }
            try:
                ids, count = eutils_esearch(database, spec["query"], retmax=args.max_results)
                summaries = eutils_esummary(database, ids)
                audit["reported"] = count
                audit["retrieved"] = len(summaries)
                audit["complete"] = count <= len(ids) and len(summaries) == len(ids)
                if not audit["complete"]:
                    incomplete = True
                rows.extend(summary_row(item, spec, database, run_id) for item in summaries)
            except Exception as exc:
                message = str(exc)
                audit["error"] = message
                errors.append(
                    {
                        "input_gene": spec["input_gene"],
                        "database": database,
                        "query": spec["query"],
                        "error": message,
                    }
                )
                rows.append(error_row(spec, database, run_id, message))
            searches.append(audit)

    rows = merge_rows(rows)
    backup = rotate_existing(args.output, run_id)
    write_tsv(args.output, rows, OUTPUT_FIELDS)
    run_path = args.output.with_name(f"{args.output.stem}.run.json")
    run_backup = rotate_existing(run_path, run_id)
    write_json(
        run_path,
        {
            **provenance("search_refseq.py"),
            "run_id": run_id,
            "created_at": utc_now(),
            "databases": list(databases),
            "max_results": args.max_results,
            "search_complete": not incomplete and not errors,
            "searches": searches,
            "records_written": len(rows),
            "errors": errors,
            "output": str(args.output),
            "backup": backup,
            "run_backup": run_backup,
        },
    )
    print(f"wrote {len(rows)} RefSeq records to {args.output}")
    raise SystemExit(exit_code_for_run(errors=errors, incomplete=incomplete))


if __name__ == "__main__":
    main()
