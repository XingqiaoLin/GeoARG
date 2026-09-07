#!/usr/bin/env python3
"""Search Europe PMC for candidate novel-ARG papers on or after --since.

This is a retrieval step only. Keyword hits are not novel ARGs.
Always paginate. Write every record, including preprints.
Truncation is an audit status, not only a console warning.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import (
    SKILL_VERSION,
    clean,
    epmc_search,
    exit_code_for_run,
    is_preprint,
    new_run_id,
    provenance,
    rec_date,
    rec_date_info,
    require_day,
    rotate_existing,
    utc_now,
    write_json,
    write_tsv,
)

QUERIES = [
    (
        "q_novel_resistance",
        '({date}) AND (TITLE_ABS:"novel" OR TITLE_ABS:"newly" OR TITLE_ABS:"previously uncharacterized" OR TITLE_ABS:"previously undescribed") AND TITLE_ABS:"resistance" AND (TITLE_ABS:"gene" OR TITLE_ABS:"enzyme" OR TITLE_ABS:"variant" OR TITLE_ABS:"allele" OR TITLE_ABS:"determinant")',
    ),
    (
        "q_novel_arg_class",
        '({date}) AND (TITLE_ABS:"novel" OR TITLE_ABS:"newly" OR TITLE_ABS:"previously uncharacterized" OR TITLE_ABS:"previously undescribed") AND (TITLE_ABS:"antibiotic resistance" OR TITLE_ABS:"antimicrobial resistance" OR TITLE_ABS:"fosfomycin resistance" OR TITLE_ABS:"colistin resistance" OR TITLE_ABS:"aminoglycoside resistance" OR TITLE_ABS:"macrolide resistance" OR TITLE_ABS:"beta-lactamase" OR TITLE_ABS:"β-lactamase" OR TITLE_ABS:"carbapenemase") AND (TITLE_ABS:"gene" OR TITLE_ABS:"enzyme" OR TITLE_ABS:"variant" OR TITLE_ABS:"allele" OR TITLE_ABS:"determinant")',
    ),
    (
        "q_confers_resistance",
        '({date}) AND (TITLE_ABS:"confers resistance" OR TITLE_ABS:"conferred resistance" OR TITLE_ABS:"resistance determinant" OR TITLE_ABS:"functional resistance gene") AND (TITLE_ABS:"gene" OR TITLE_ABS:"enzyme" OR TITLE_ABS:"variant" OR TITLE_ABS:"allele" OR TITLE_ABS:"determinant" OR TITLE_ABS:"beta-lactamase")',
    ),
    (
        "q_named_new_arg",
        '({date}) AND (TITLE_ABS:"designated" OR TITLE:"new" OR TITLE:"novel") AND (TITLE_ABS:"bla" OR TITLE_ABS:"mcr" OR TITLE_ABS:"fosA" OR TITLE_ABS:"lsa" OR TITLE_ABS:"ant(" OR TITLE_ABS:"aph(" OR TITLE_ABS:"aac(")',
    ),
]

HIT_FIELDS = [
    "key",
    "id",
    "source",
    "pmid",
    "pmcid",
    "doi",
    "title",
    "journal",
    "first_publication_date",
    "date_raw",
    "date_normalized",
    "date_precision",
    "is_preprint",
    "queries",
    "url",
    "skill_version",
    "run_id",
]


def date_clause(since: str, until: str | None) -> str:
    if until:
        return f"FIRST_PDATE:[{since} TO {until}]"
    return f"FIRST_PDATE:[{since} TO 3000-01-01]"


def main() -> None:
    ap = argparse.ArgumentParser(description="Date-bounded Europe PMC search for candidate novel ARGs")
    ap.add_argument("--since", required=True, help="Inclusive start date YYYY-MM-DD")
    ap.add_argument("--until", help="Inclusive end date YYYY-MM-DD; omit for open-ended")
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--max-pages", type=int, default=40)
    args = ap.parse_args()
    since = require_day(args.since, "--since")
    until = require_day(args.until, "--until") if args.until else None
    if until and until < since:
        raise SystemExit("--until must be on or after --since")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    run_id = new_run_id()
    tsv = args.output_dir / "search_hits.tsv"
    audit_path = args.output_dir / "search_audit.json"
    queries_path = args.output_dir / "search_queries.json"
    rotated = [
        p
        for p in (
            rotate_existing(tsv, run_id),
            rotate_existing(audit_path, run_id),
            rotate_existing(queries_path, run_id),
        )
        if p
    ]
    clause = date_clause(since, until)
    seen: dict[str, dict] = {}
    stats = []
    errors = []
    started = utc_now()

    for name, template in QUERIES:
        query = template.format(date=clause)
        try:
            page = epmc_search(query, max_pages=args.max_pages)
        except Exception as exc:  # noqa: BLE001 — finish other queries, then fail
            errors.append({"query_name": name, "error": str(exc)})
            stats.append(
                {
                    "query_name": name,
                    "query": query,
                    "hit_count": 0,
                    "saved": 0,
                    "pages": 0,
                    "truncated": True,
                    "complete": False,
                    "error": str(exc),
                }
            )
            print(f"{name}: PROCESS_FAILED {exc}", file=sys.stderr)
            continue
        stats.append(
            {
                "query_name": name,
                "query": query,
                "hit_count": page.hit_count,
                "saved": page.retrieved,
                "pages": page.pages,
                "truncated": page.truncated,
                "complete": page.complete,
            }
        )
        status = "complete" if page.complete else "truncated"
        print(f"{name}: saved {page.retrieved} / reported {page.hit_count} [{status}]")
        if page.truncated:
            print(f"  SEARCH_INCOMPLETE: raise --max-pages (now {args.max_pages})")
        for row in page.rows:
            key = f"{row.get('source', '')}:{row.get('id', '')}"
            if key in seen:
                seen[key]["queries"] += ";" + name
                continue
            parsed = rec_date_info(row)
            seen[key] = {
                "key": key,
                "id": row.get("id", ""),
                "source": row.get("source", ""),
                "pmid": row.get("pmid", ""),
                "pmcid": row.get("pmcid", ""),
                "doi": row.get("doi", ""),
                "title": clean(row.get("title", "")),
                "journal": (row.get("journalInfo") or {}).get("journal", {}).get("title", ""),
                "first_publication_date": rec_date(row),
                "date_raw": parsed.original,
                "date_normalized": parsed.normalized,
                "date_precision": parsed.precision,
                "is_preprint": is_preprint(row),
                "queries": name,
                "url": ("https://doi.org/" + row["doi"]) if row.get("doi") else f"https://europepmc.org/article/{row.get('source')}/{row.get('id')}",
                "skill_version": SKILL_VERSION,
                "run_id": run_id,
            }

    records = sorted(seen.values(), key=lambda r: (r["first_publication_date"] or "9999", r["key"]))
    write_tsv(tsv, records, HIT_FIELDS)
    search_complete = bool(stats) and all(item["complete"] for item in stats) and not errors
    code = exit_code_for_run(errors=errors, incomplete=not search_complete)
    audit = provenance("search_after_date.py")
    audit.update(
        {
            "run_id": run_id,
            "started_at": started,
            "finished_at": utc_now(),
            "since": since,
            "until": until,
            "max_pages": args.max_pages,
            "unique_records": len(records),
            "preprints": sum(1 for r in records if r["is_preprint"]),
            "queries": stats,
            "errors": errors,
            "search_complete": search_complete,
            "rotated_previous": rotated,
            "exit_code": code,
        }
    )
    write_json(queries_path, audit)
    write_json(audit_path, audit)
    print(f"unique records: {len(records)}")
    print(f"preprints in window: {audit['preprints']}")
    print(f"search_complete: {audit['search_complete']}")
    print(f"wrote {tsv}")
    if rotated:
        print("rotated previous: " + "; ".join(rotated))
    if code:
        kind = "PROCESS_FAILED" if errors else "SEARCH_INCOMPLETE"
        print(f"{kind}: exit {code}", file=sys.stderr)
        raise SystemExit(code)


if __name__ == "__main__":
    main()
