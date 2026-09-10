#!/usr/bin/env python3
"""Screen named ARGs against earlier public records after --since.

This script never marks a gene as a finished novel ARG. It only reports a
date-gate status:

- exclude: formal / preprint / article with day precision before --since
- no_earlier_record_found: search finished; no earlier literature hit
- insufficient_evidence: missing dates, coarse dates, truncated search, or
  sequence evidence that uses the current NCBI title only
- provisional_sequence_before_since: current nuccore title matches, CreateDate
  is before --since; name-at-create is not verified

某个 arg 正式发文在 某日期之后，但 preprint 在某日期之前，这种也不能算 novel arg
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
    PRECISION_DAY,
    SKILL_VERSION,
    clean,
    dedup_key,
    epmc_search,
    eutils_esearch,
    eutils_esummary,
    exit_code_for_run,
    is_preprint,
    mention_re,
    mentions,
    new_run_id,
    parse_date,
    provenance,
    pubmed_search,
    rec_date_info,
    require_day,
    rotate_existing,
    sort_by_date,
    utc_now,
    vs_cutoff,
    write_json,
    write_tsv,
)
from queries import expand_aliases

TITLE_QUERY = 'TITLE:"{alias}"'
ABS_QUERY = 'ABSTRACT:"{alias}"'

OUTPUT_FIELDS = [
    "gene",
    "aliases",
    "alias_variants",
    "since",
    "formal_date",
    "formal_date_raw",
    "formal_date_normalized",
    "formal_date_precision",
    "date_gate",
    "review_status",
    "novel_for_cutoff",
    "first_public_date",
    "first_public_basis",
    "first_literature_date",
    "earliest_current_named_nuccore_date",
    "sequence_name_evidence",
    "preprint_before_since",
    "article_before_since",
    "provisional_sequence_before_since",
    "lit_search_complete",
    "seq_search_complete",
    "epmc_reported",
    "epmc_retrieved",
    "pubmed_reported",
    "pubmed_retrieved",
    "exact_mentions",
    "title_mentions",
    "deciding_record",
    "earliest_preprints",
    "earliest_articles",
    "earliest_sequences",
    "skill_version",
    "run_id",
    "error",
]


def title_query(aliases: list[str]) -> str:
    parts = [TITLE_QUERY.format(alias=a) for a in aliases]
    parts += [ABS_QUERY.format(alias=a) for a in aliases[:6]]
    return "(" + " OR ".join(parts) + ")"


def pubmed_term(aliases: list[str]) -> str:
    return "(" + " OR ".join(f'"{alias}"[tiab]' for alias in aliases) + ")"


def isolate_only_mention(title: str, aliases: list[str], pattern) -> bool:
    stripped = title
    for alias in aliases:
        stripped = re.sub(
            rf"\b(?:strain|isolate|sample|specimen)\s+{re.escape(alias)}\b",
            " ",
            stripped,
            flags=re.I,
        )
    return not mentions(stripped, pattern)


def summarize_nuccore(ids: list[str], pattern, context_re, aliases: list[str]) -> list[dict]:
    hits = []
    for item in eutils_esummary("nuccore", ids):
        title = clean(item.get("title") or "")
        if not mentions(title, pattern) or isolate_only_mention(title, aliases, pattern):
            continue
        if context_re and not context_re.search(title):
            continue
        created = parse_date(str(item.get("createdate") or item.get("createDate") or ""))
        acc = item.get("accessionversion") or item.get("caption") or item.get("uid")
        hits.append(
            {
                "db": "nuccore",
                "accession": acc,
                "createdate": created.normalized if created.precision == PRECISION_DAY else "",
                "createdate_raw": created.original,
                "createdate_normalized": created.normalized,
                "createdate_precision": created.precision,
                "title": title,
                "name_at_create_verified": False,
                "sequence_name_evidence": "current_title_only_unverified",
            }
        )
    return hits


def ncbi_named_nuccore(term: str, accessions: list[str], pattern, context_re, aliases: list[str]) -> tuple[list[dict], bool]:
    """Current-title nuccore hits. CreateDate is not a verified naming date."""
    ids: list[str] = []
    reported = 0
    retrieved = 0
    for acc in accessions:
        found, count = eutils_esearch("nuccore", f"{acc}[Accession]", retmax=3)
        ids.extend(found)
        reported += count
        retrieved += len(found)
    if term:
        found, count = eutils_esearch("nuccore", term, retmax=20)
        ids.extend(found)
        reported += count
        retrieved += len(found)
    seen: list[str] = []
    for uid in ids:
        if uid and uid not in seen:
            seen.append(uid)
    hits = summarize_nuccore(seen, pattern, context_re, aliases)
    hits = sort_by_date(hits, "createdate")
    complete = reported <= retrieved
    return hits, complete


def earliest_day(values: list[str]) -> str:
    dates = [v for v in values if v]
    return min(dates) if dates else ""


def classify(
    since: str,
    formal: str,
    formal_precision: str,
    preprint_before: bool,
    article_before: bool,
    unresolved_lit: bool,
    current_seq_before: bool,
    lit_search_complete: bool,
    seq_search_complete: bool,
) -> str:
    formal_vs = vs_cutoff(formal, formal_precision, since) if formal_precision == PRECISION_DAY or formal else "unknown"
    if formal_precision == PRECISION_DAY and formal_vs == "before":
        return "formal_before_since"
    if preprint_before:
        return "preprint_before_since"
    if article_before:
        return "article_before_since"
    if unresolved_lit or formal_precision in {"month", "year", "invalid"}:
        return "insufficient_evidence"
    if current_seq_before:
        return "provisional_sequence_before_since"
    if not lit_search_complete:
        return "insufficient_evidence"
    if formal_precision == "missing" or not formal:
        return "insufficient_evidence"
    if formal_precision == PRECISION_DAY and formal_vs == "on_or_after" and lit_search_complete:
        if not seq_search_complete and not current_seq_before:
            return "insufficient_evidence"
        return "no_earlier_record_found"
    return "insufficient_evidence"


def dump(rows: list[dict], limit: int = 3) -> str:
    return json.dumps(rows[:limit], ensure_ascii=False)


def review_one(
    gene: str,
    aliases: list[str],
    since: str,
    formal: str,
    formal_precision: str,
    formal_raw: str,
    ncbi_term: str,
    context: str,
    accessions: list[str],
    run_id: str,
    use_pubmed: bool = True,
) -> dict:
    variants = expand_aliases(aliases)
    pattern = mention_re(variants)
    context_re = re.compile(context, re.I) if context else None
    query = title_query(variants)
    page = epmc_search(query, page_size=100, max_pages=8)
    rows = [("epmc", row) for row in page.rows]

    pubmed_reported = 0
    pubmed_retrieved = 0
    pubmed_complete = True
    if use_pubmed:
        pm = pubmed_search(pubmed_term(variants), batch=100, max_records=400)
        rows += [("pubmed", row) for row in pm.rows]
        pubmed_reported = pm.hit_count
        pubmed_retrieved = pm.retrieved
        pubmed_complete = pm.complete

    matched: list[dict] = []
    seen_keys: set[str] = set()
    unresolved_lit = False
    for source_db, row in rows:
        title = clean(row.get("title", ""))
        abstract = clean(row.get("abstractText", ""))
        blob = f"{title} {abstract}"
        if not (mentions(title, pattern) or mentions(abstract, pattern)):
            continue
        if context_re and not context_re.search(blob):
            continue
        key = dedup_key(row)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        parsed = rec_date_info(row)
        relation = vs_cutoff(parsed.normalized, parsed.precision, since) if parsed.normalized else "unknown"
        if relation == "unresolved":
            unresolved_lit = True
        matched.append(
            {
                "id": row.get("id"),
                "source": row.get("source"),
                "source_db": source_db,
                "date": parsed.normalized if parsed.precision == PRECISION_DAY else "",
                "date_raw": parsed.original,
                "date_normalized": parsed.normalized,
                "date_precision": parsed.precision,
                "vs_cutoff": relation,
                "doi": row.get("doi", ""),
                "title": title,
                "is_preprint": is_preprint(row),
                "in_title": bool(mentions(title, pattern)),
            }
        )

    title_hits = [h for h in matched if h["in_title"]]
    focus = title_hits or matched
    preprints = sort_by_date([h for h in focus if h["is_preprint"]], "date")
    articles = sort_by_date([h for h in focus if not h["is_preprint"]], "date")
    preprints_before = [h for h in preprints if h["vs_cutoff"] == "before"]
    articles_before = [h for h in articles if h["vs_cutoff"] == "before"]

    seq_hits, seq_complete = (
        ncbi_named_nuccore(ncbi_term, accessions, pattern, context_re, aliases)
        if (ncbi_term or accessions)
        else ([], True)
    )
    seq_before = []
    for hit in seq_hits:
        relation = vs_cutoff(hit["createdate_normalized"], hit["createdate_precision"], since)
        hit["vs_cutoff"] = relation
        if relation == "before":
            seq_before.append(hit)
        if relation == "unresolved":
            unresolved_lit = True

    first_lit = earliest_day([h["date"] for h in focus])
    first_seq_current = earliest_day([h["createdate"] for h in seq_hits])
    first_public = earliest_day([formal if formal_precision == PRECISION_DAY else "", first_lit])
    if first_lit and (not formal or first_lit < formal):
        basis = "preprint" if any(h["date"] == first_lit and h["is_preprint"] for h in focus) else "article"
    elif formal_precision == PRECISION_DAY and formal:
        basis = "formal"
    else:
        basis = ""

    date_gate = classify(
        since,
        formal,
        formal_precision,
        bool(preprints_before),
        bool(articles_before),
        unresolved_lit,
        bool(seq_before),
        page.complete and pubmed_complete,
        seq_complete,
    )

    deciding = None
    if date_gate == "formal_before_since":
        deciding = {"kind": "formal", "date": formal, "precision": formal_precision}
    elif date_gate == "preprint_before_since" and preprints_before:
        deciding = preprints_before[0]
    elif date_gate == "article_before_since" and articles_before:
        deciding = articles_before[0]
    elif date_gate == "provisional_sequence_before_since" and seq_before:
        deciding = seq_before[0]

    return {
        "gene": gene,
        "aliases": ";".join(aliases),
        "alias_variants": ";".join(variants),
        "since": since,
        "formal_date": formal if formal_precision == PRECISION_DAY else "",
        "formal_date_raw": formal_raw,
        "formal_date_normalized": formal,
        "formal_date_precision": formal_precision,
        "date_gate": date_gate,
        "review_status": "machine_screen",
        "novel_for_cutoff": False,
        "first_public_date": first_public,
        "first_public_basis": basis,
        "first_literature_date": first_lit,
        "earliest_current_named_nuccore_date": first_seq_current,
        "sequence_name_evidence": "current_title_only_unverified" if seq_hits else "none",
        "preprint_before_since": bool(preprints_before),
        "article_before_since": bool(articles_before),
        "provisional_sequence_before_since": bool(seq_before),
        "lit_search_complete": page.complete and pubmed_complete,
        "seq_search_complete": seq_complete,
        "epmc_reported": page.hit_count,
        "epmc_retrieved": page.retrieved,
        "pubmed_reported": pubmed_reported,
        "pubmed_retrieved": pubmed_retrieved,
        "exact_mentions": len(matched),
        "title_mentions": len(title_hits),
        "deciding_record": json.dumps(deciding or {}, ensure_ascii=False),
        "earliest_preprints": dump(preprints),
        "earliest_articles": dump(articles),
        "earliest_sequences": dump(seq_hits, 4),
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
            aliases = [a.strip() for a in (row.get("aliases") or gene).split(";") if a.strip()]
            parsed = parse_date(row.get("formal_date", ""))
            rows.append(
                {
                    "gene": gene,
                    "aliases": aliases,
                    "formal_date": parsed.normalized,
                    "formal_date_precision": parsed.precision,
                    "formal_date_raw": parsed.original,
                    "ncbi_term": row.get("ncbi_term", ""),
                    "context": row.get("context", ""),
                    "accessions": [a.strip() for a in (row.get("accessions") or "").split(";") if a.strip()],
                }
            )
    return rows


def flag_label(date_gate: str) -> str:
    if date_gate in {"formal_before_since", "preprint_before_since", "article_before_since"}:
        return "DROP"
    if date_gate == "no_earlier_record_found":
        return "OPEN"
    return "HOLD"


def main() -> None:
    ap = argparse.ArgumentParser(description="Cross-validate named ARGs against earlier public records")
    ap.add_argument("--since", required=True)
    ap.add_argument("--genes", type=Path, required=True, help="TSV with gene, aliases, formal_date, ncbi_term")
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument(
        "--no-pubmed",
        action="store_true",
        help="Europe PMC only. Narrower; use when PubMed is unreachable.",
    )
    args = ap.parse_args()
    since = require_day(args.since, "--since")
    run_id = new_run_id()
    meta_path = args.output.with_name(args.output.stem + ".run.json")
    rotated = [p for p in (rotate_existing(args.output, run_id), rotate_existing(meta_path, run_id)) if p]

    items = parse_genes(args.genes)
    meta = provenance("crossvalidate.py")
    meta.update(
        {
            "run_id": run_id,
            "started_at": utc_now(),
            "finished_at": "",
            "since": since,
            "genes_file": str(args.genes),
            "output": str(args.output),
            "sources": ["epmc"] if args.no_pubmed else ["epmc", "pubmed"],
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
                since,
                item["formal_date"],
                item["formal_date_precision"],
                item["formal_date_raw"],
                item["ncbi_term"],
                item["context"],
                item["accessions"],
                run_id,
                use_pubmed=not args.no_pubmed,
            )
        except Exception as exc:  # noqa: BLE001 — keep the rest of the run
            row = {field: "" for field in OUTPUT_FIELDS}
            row.update(
                {
                    "gene": item["gene"],
                    "aliases": ";".join(item["aliases"]),
                    "alias_variants": ";".join(expand_aliases(item["aliases"])),
                    "since": since,
                    "formal_date": item["formal_date"] if item["formal_date_precision"] == PRECISION_DAY else "",
                    "formal_date_raw": item["formal_date_raw"],
                    "formal_date_normalized": item["formal_date"],
                    "formal_date_precision": item["formal_date_precision"],
                    "date_gate": "insufficient_evidence",
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
            f"{flag_label(row['date_gate']):4} {item['gene']:12} "
            f"formal={row['formal_date_raw'] or row['formal_date'] or row['formal_date_precision']:10} "
            f"first_public={row['first_public_date'] or '-':10} {row['date_gate']}"
        )

    code = exit_code_for_run(errors=meta["errors"], incomplete=False)
    meta["finished_at"] = utc_now()
    meta["exit_code"] = code
    write_json(meta_path, meta)
    print(f"wrote {args.output} ({len(results)} rows); novel_for_cutoff is never set by this script")
    print(f"run metadata: {meta_path}")
    if rotated:
        print("rotated previous: " + "; ".join(rotated))
    if code:
        print(f"PROCESS_FAILED: {len(meta['errors'])} gene(s) raised; exit {code}", file=sys.stderr)
        raise SystemExit(code)


if __name__ == "__main__":
    main()
