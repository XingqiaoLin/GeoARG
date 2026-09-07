#!/usr/bin/env python3
"""Search Europe PMC and PubMed for candidate novel-ARG papers on or after --since.

This is a retrieval step only. Keyword hits are not novel ARGs.
Always paginate. Write every record, including preprints.
Truncation is an audit status, not only a console warning.

Coverage comes from three places: many chunked queries, two sources, and the
abstract text. The abstract is written to the hit table because the screening
step reads it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import (
    SKILL_VERSION,
    clean,
    dedup_key,
    epmc_search,
    exit_code_for_run,
    is_preprint,
    new_run_id,
    provenance,
    pubmed_search,
    rec_date,
    rec_date_info,
    require_day,
    rotate_existing,
    utc_now,
    vs_cutoff,
    write_json,
    write_tsv,
)
from queries import DEFAULT_PROFILE, PROFILES, epmc_queries, pubmed_queries

HIT_FIELDS = [
    "key",
    "id",
    "source",
    "source_db",
    "pmid",
    "pmcid",
    "doi",
    "title",
    "abstract",
    "publication_types",
    "journal",
    "first_publication_date",
    "date_raw",
    "date_normalized",
    "date_precision",
    "in_window",
    "is_preprint",
    "queries",
    "n_queries",
    "url",
    "skill_version",
    "run_id",
]


def epmc_date_clause(since: str, until: str | None) -> str:
    if until:
        return f"FIRST_PDATE:[{since} TO {until}]"
    return f"FIRST_PDATE:[{since} TO 3000-01-01]"


def pubmed_date_clause(since: str, until: str | None) -> str:
    end = until or "3000/01/01"
    since_slash = since.replace("-", "/")
    end_slash = end.replace("-", "/")
    return f'"{since_slash}"[EDAT] : "{end_slash}"[EDAT]'


def window_status(parsed_normalized: str, precision: str, since: str, until: str | None) -> str:
    """PubMed EDAT is an indexing date, so a hit can sit outside the window.

    Those rows are kept — an older paper naming the same gene is exactly what
    the date gate needs — but they are labelled instead of silently mixed in.
    """
    relation = vs_cutoff(parsed_normalized, precision, since)
    if relation == "before":
        return "before_since"
    if relation == "unknown":
        return "unknown"
    if relation == "unresolved":
        return "unresolved"
    if until and parsed_normalized and precision == "day" and parsed_normalized > until:
        return "after_until"
    return "in_window"


def pub_types(row: dict) -> str:
    types = row.get("pubTypeList", {}).get("pubType", [])
    if isinstance(types, str):
        types = [types]
    return ";".join(clean(str(t)) for t in types if t)


def record_url(row: dict) -> str:
    if row.get("doi"):
        return "https://doi.org/" + row["doi"]
    if row.get("pmid"):
        return f"https://pubmed.ncbi.nlm.nih.gov/{row['pmid']}/"
    return f"https://europepmc.org/article/{row.get('source')}/{row.get('id')}"


def load_extra_queries(path: Path | None, extra: list[str]) -> list[tuple[str, str]]:
    """User queries, so a wider sweep does not need a skill edit."""
    out: list[tuple[str, str]] = []
    for i, query in enumerate(extra, start=1):
        out.append((f"q_user_{i:02d}", query))
    if path:
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "\t" in line:
                name, query = line.split("\t", 1)
                out.append((name.strip(), query.strip()))
            else:
                out.append((f"q_file_{i:02d}", line))
    return out


def run_source(
    source_db: str,
    queries: list[tuple[str, str]],
    clause: str,
    seen: dict[str, dict],
    stats: list[dict],
    errors: list[dict],
    *,
    max_pages: int,
    page_size: int,
    max_records: int,
    since: str,
    until: str | None,
) -> None:
    for name, template in queries:
        query = template.format(date=clause) if "{date}" in template else f"({clause}) AND ({template})"
        try:
            if source_db == "epmc":
                page = epmc_search(query, page_size=page_size, max_pages=max_pages)
            else:
                page = pubmed_search(query, max_records=max_records)
        except Exception as exc:  # noqa: BLE001 — finish other queries, then fail
            errors.append({"source": source_db, "query_name": name, "error": str(exc)})
            stats.append(
                {
                    "source": source_db,
                    "query_name": name,
                    "query": query,
                    "hit_count": 0,
                    "saved": 0,
                    "new_records": 0,
                    "pages": 0,
                    "truncated": True,
                    "complete": False,
                    "error": str(exc),
                }
            )
            print(f"{name}: PROCESS_FAILED {exc}", file=sys.stderr)
            continue

        added = 0
        for row in page.rows:
            key = dedup_key(row)
            if key in seen:
                entry = seen[key]
                if name not in entry["queries"].split(";"):
                    entry["queries"] += ";" + name
                    entry["n_queries"] = len(entry["queries"].split(";"))
                if not entry["abstract"] and row.get("abstractText"):
                    entry["abstract"] = clean(row.get("abstractText", ""))
                if not entry["publication_types"]:
                    entry["publication_types"] = pub_types(row)
                if source_db not in entry["source_db"].split(";"):
                    entry["source_db"] += ";" + source_db
                continue
            parsed = rec_date_info(row)
            seen[key] = {
                "key": key,
                "id": row.get("id", ""),
                "source": row.get("source", ""),
                "source_db": source_db,
                "pmid": row.get("pmid", ""),
                "pmcid": row.get("pmcid", ""),
                "doi": row.get("doi", ""),
                "title": clean(row.get("title", "")),
                "abstract": clean(row.get("abstractText", "")),
                "publication_types": pub_types(row),
                "journal": (row.get("journalInfo") or {}).get("journal", {}).get("title", ""),
                "first_publication_date": rec_date(row),
                "date_raw": parsed.original,
                "date_normalized": parsed.normalized,
                "date_precision": parsed.precision,
                "in_window": window_status(parsed.normalized, parsed.precision, since, until),
                "is_preprint": is_preprint(row),
                "queries": name,
                "n_queries": 1,
                "url": record_url(row),
                "skill_version": SKILL_VERSION,
                "run_id": "",
            }
            added += 1

        stats.append(
            {
                "source": source_db,
                "query_name": name,
                "query": query,
                "hit_count": page.hit_count,
                "saved": page.retrieved,
                "new_records": added,
                "pages": page.pages,
                "truncated": page.truncated,
                "complete": page.complete,
            }
        )
        status = "complete" if page.complete else "truncated"
        print(f"{name}: saved {page.retrieved} / reported {page.hit_count} (+{added} new) [{status}]")
        if page.truncated:
            print(f"  SEARCH_INCOMPLETE: raise --max-pages (now {max_pages})")


def main() -> None:
    ap = argparse.ArgumentParser(description="Date-bounded literature sweep for candidate novel ARGs")
    ap.add_argument("--since", required=True, help="Inclusive start date YYYY-MM-DD")
    ap.add_argument("--until", help="Inclusive end date YYYY-MM-DD; omit for open-ended")
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--max-pages", type=int, default=40)
    ap.add_argument("--page-size", type=int, default=1000, help="Europe PMC page size, max 1000")
    ap.add_argument("--max-records", type=int, default=10000, help="Per-query PubMed cap")
    ap.add_argument(
        "--profile",
        choices=PROFILES,
        default=DEFAULT_PROFILE,
        help="core = fewest queries, broad = default, max = widest and slowest",
    )
    ap.add_argument(
        "--sources",
        default="epmc,pubmed",
        help="Comma list: epmc, pubmed. Both by default.",
    )
    ap.add_argument("--extra-query", action="append", default=[], help="Extra Europe PMC query; repeatable")
    ap.add_argument("--query-file", type=Path, help="File of extra queries; optional name<TAB>query")
    args = ap.parse_args()

    since = require_day(args.since, "--since")
    until = require_day(args.until, "--until") if args.until else None
    if until and until < since:
        raise SystemExit("--until must be on or after --since")
    page_size = max(1, min(args.page_size, 1000))
    sources = [s.strip().lower() for s in args.sources.split(",") if s.strip()]
    unknown = [s for s in sources if s not in {"epmc", "pubmed"}]
    if unknown:
        raise SystemExit(f"unknown source(s): {', '.join(unknown)}; use epmc and/or pubmed")
    if not sources:
        raise SystemExit("--sources needs at least one of epmc, pubmed")

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

    seen: dict[str, dict] = {}
    stats: list[dict] = []
    errors: list[dict] = []
    started = utc_now()

    if "epmc" in sources:
        queries = epmc_queries(args.profile) + load_extra_queries(args.query_file, args.extra_query)
        print(f"Europe PMC: {len(queries)} queries [profile={args.profile}]")
        run_source(
            "epmc",
            queries,
            epmc_date_clause(since, until),
            seen,
            stats,
            errors,
            max_pages=args.max_pages,
            page_size=page_size,
            max_records=args.max_records,
            since=since,
            until=until,
        )

    if "pubmed" in sources:
        queries = pubmed_queries(args.profile)
        print(f"PubMed: {len(queries)} queries [profile={args.profile}]")
        run_source(
            "pubmed",
            queries,
            pubmed_date_clause(since, until),
            seen,
            stats,
            errors,
            max_pages=args.max_pages,
            page_size=page_size,
            max_records=args.max_records,
            since=since,
            until=until,
        )

    records = sorted(seen.values(), key=lambda r: (r["first_publication_date"] or "9999", r["key"]))
    for row in records:
        row["run_id"] = run_id
    write_tsv(tsv, records, HIT_FIELDS)

    search_complete = bool(stats) and all(item["complete"] for item in stats) and not errors
    code = exit_code_for_run(errors=errors, incomplete=not search_complete)
    with_abstract = sum(1 for r in records if r["abstract"])
    audit = provenance("search_after_date.py")
    audit.update(
        {
            "run_id": run_id,
            "started_at": started,
            "finished_at": utc_now(),
            "since": since,
            "until": until,
            "profile": args.profile,
            "sources": sources,
            "max_pages": args.max_pages,
            "page_size": page_size,
            "max_records": args.max_records,
            "n_queries": len(stats),
            "unique_records": len(records),
            "records_with_abstract": with_abstract,
            "window_counts": {
                status: sum(1 for r in records if r["in_window"] == status)
                for status in sorted({r["in_window"] for r in records})
            },
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
    print(f"queries run: {len(stats)}")
    print(f"unique records: {len(records)}")
    print(f"with abstract: {with_abstract}")
    print(f"in_window: {audit['window_counts']}")
    print(f"preprints: {audit['preprints']}")
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
