#!/usr/bin/env python3
"""Shared helpers for date-bounded ARG search and first-public-date checks."""

from __future__ import annotations

import calendar
import csv
import hashlib
import html
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

UA = "GeoARG-novel-arg-watch/1.2.0"
SKILL_NAME = "novel-arg-watch"
SKILL_VERSION = "1.2.0"
EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
SLEEP = 0.3
RETRIES = 3

EXIT_OK = 0
EXIT_PROCESS = 2
EXIT_INCOMPLETE = 3


def exit_code_for_run(*, errors: list | None = None, incomplete: bool = False) -> int:
    """Non-zero if processing failed or retrieval did not finish.

    0 = finished with no exceptions and complete retrieval
    2 = one or more processing errors (request/parse/write per item)
    3 = retrieval truncated or otherwise incomplete, no exceptions
    """
    if errors:
        return EXIT_PROCESS
    if incomplete:
        return EXIT_INCOMPLETE
    return EXIT_OK

PRECISION_DAY = "day"
PRECISION_MONTH = "month"
PRECISION_YEAR = "year"
PRECISION_MISSING = "missing"
PRECISION_INVALID = "invalid"


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]*>", "", html.unescape(text or ""))).strip()


@dataclass(frozen=True)
class ParsedDate:
    original: str
    normalized: str
    precision: str


def parse_date(value: str | None) -> ParsedDate:
    """Keep the input string. Normalize only a copy used for comparison."""
    original = "" if value is None else str(value)
    stripped = original.strip()
    if not stripped:
        return ParsedDate(original=original, normalized="", precision=PRECISION_MISSING)
    compact = stripped.replace("/", "-")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", compact):
        try:
            date.fromisoformat(compact)
        except ValueError:
            return ParsedDate(original=original, normalized=compact, precision=PRECISION_INVALID)
        return ParsedDate(original=original, normalized=compact, precision=PRECISION_DAY)
    if re.fullmatch(r"\d{4}-\d{2}", compact):
        _year, month = compact.split("-")
        if 1 <= int(month) <= 12:
            return ParsedDate(original=original, normalized=compact, precision=PRECISION_MONTH)
        return ParsedDate(original=original, normalized=compact, precision=PRECISION_INVALID)
    if re.fullmatch(r"\d{4}", compact):
        return ParsedDate(original=original, normalized=compact, precision=PRECISION_YEAR)
    return ParsedDate(original=original, normalized="", precision=PRECISION_INVALID)


def require_day(value: str, label: str) -> str:
    parsed = parse_date(value)
    if parsed.precision == PRECISION_DAY:
        return parsed.normalized
    if parsed.precision == PRECISION_MISSING:
        raise SystemExit(f"{label} is missing; need YYYY-MM-DD")
    if parsed.precision in {PRECISION_MONTH, PRECISION_YEAR}:
        raise SystemExit(f"{label}={value!r} has {parsed.precision} precision; need YYYY-MM-DD")
    raise SystemExit(f"{label}={value!r} is not a valid date")


def date_span(parsed: str, precision: str) -> tuple[str, str] | None:
    if precision == PRECISION_DAY:
        return parsed, parsed
    if precision == PRECISION_MONTH:
        year, month = (int(x) for x in parsed.split("-"))
        last = calendar.monthrange(year, month)[1]
        return f"{year:04d}-{month:02d}-01", f"{year:04d}-{month:02d}-{last:02d}"
    if precision == PRECISION_YEAR:
        return f"{parsed}-01-01", f"{parsed}-12-31"
    return None


def vs_cutoff(parsed: str, precision: str, since: str) -> str:
    """before | on_or_after | unresolved | unknown"""
    span = date_span(parsed, precision)
    if not span:
        return "unknown"
    low, high = span
    if high < since:
        return "before"
    if low >= since:
        return "on_or_after"
    return "unresolved"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def get_json(url: str) -> dict:
    last: Exception | None = None
    for attempt in range(RETRIES):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=90) as resp:
                return json.loads(resp.read().decode())
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            last = exc
            time.sleep(SLEEP * (2**attempt))
    raise RuntimeError(f"request failed after {RETRIES} tries: {url}") from last


@dataclass
class SearchPage:
    rows: list[dict]
    hit_count: int
    retrieved: int
    truncated: bool
    pages: int
    complete: bool


def epmc_search(query: str, page_size: int = 100, max_pages: int = 40) -> SearchPage:
    """Paginate Europe PMC. Never stop at the first page."""
    rows: list[dict] = []
    cursor = "*"
    total = 0
    pages = 0
    for _ in range(max_pages):
        qs = urllib.parse.urlencode(
            {
                "query": query,
                "resultType": "core",
                "pageSize": str(page_size),
                "format": "json",
                "cursorMark": cursor,
            }
        )
        payload = get_json(f"{EPMC}?{qs}")
        time.sleep(SLEEP)
        pages += 1
        total = int(payload.get("hitCount") or 0)
        batch = payload.get("resultList", {}).get("result", [])
        rows.extend(batch)
        nxt = payload.get("nextCursorMark")
        if not batch or not nxt or nxt == cursor or len(rows) >= total:
            break
        cursor = nxt
    truncated = total > len(rows)
    return SearchPage(
        rows=rows,
        hit_count=total,
        retrieved=len(rows),
        truncated=truncated,
        pages=pages,
        complete=not truncated,
    )


def rec_date_info(row: dict) -> ParsedDate:
    raw = row.get("firstPublicationDate") or row.get("electronicPublicationDate") or ""
    return parse_date(raw)


def rec_date(row: dict) -> str:
    parsed = rec_date_info(row)
    return parsed.normalized if parsed.precision == PRECISION_DAY else ""


def is_preprint(row: dict) -> bool:
    if row.get("source") == "PPR":
        return True
    types = row.get("pubTypeList", {}).get("pubType", [])
    if isinstance(types, str):
        types = [types]
    return any("preprint" in str(t).lower() for t in types)


def mention_re(aliases: list[str]) -> re.Pattern[str]:
    alts = [re.escape(alias) for alias in aliases if alias]
    if not alts:
        return re.compile(r"(?!x)x")
    return re.compile(r"(?<![A-Za-z0-9.])(?:" + "|".join(alts) + r")(?![A-Za-z0-9.])", re.I)


def mentions(text: str, pattern: re.Pattern[str]) -> bool:
    return bool(pattern.search(clean(text or "")))


def eutils_esearch(db: str, term: str, retmax: int = 20) -> tuple[list[str], int]:
    qs = urllib.parse.urlencode({"db": db, "term": term, "retmax": str(retmax), "retmode": "json"})
    payload = get_json(f"{EUTILS}/esearch.fcgi?{qs}")
    time.sleep(SLEEP)
    result = payload.get("esearchresult", {})
    ids = result.get("idlist", [])
    count = int(result.get("count") or 0)
    return ids, count


def eutils_esummary(db: str, ids: list[str]) -> list[dict]:
    if not ids:
        return []
    qs = urllib.parse.urlencode({"db": db, "id": ",".join(ids), "retmode": "json"})
    payload = get_json(f"{EUTILS}/esummary.fcgi?{qs}")
    time.sleep(SLEEP)
    result = payload.get("result", {})
    uids = result.get("uids", [])
    return [result[uid] for uid in uids if uid in result]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]


def git_head(path: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def provenance(script: str) -> dict[str, Any]:
    scripts_dir = Path(__file__).resolve().parent
    skill_dir = scripts_dir.parent
    files = ["lib.py", "crossvalidate.py", "search_after_date.py", "screen_candidates.py", "SKILL.md"]
    hashes = {}
    for name in files:
        path = scripts_dir / name if name.endswith(".py") else skill_dir / name
        if path.exists():
            hashes[name] = sha256_file(path)
    return {
        "skill_name": SKILL_NAME,
        "skill_version": SKILL_VERSION,
        "ua": UA,
        "script": script,
        "script_path": str(scripts_dir / script),
        "skill_dir": str(skill_dir),
        "python": sys.version.split()[0],
        "argv": list(sys.argv),
        "git_head": git_head(skill_dir) or git_head(skill_dir.parent.parent),
        "file_sha256": hashes,
    }


def rotate_existing(path: Path, run_id: str) -> str:
    """Move a previous output aside. Never overwrite a finished file in place."""
    if not path.exists():
        return ""
    backup = path.with_name(f"{path.stem}.bak-{run_id}{path.suffix}")
    n = 1
    while backup.exists():
        backup = path.with_name(f"{path.stem}.bak-{run_id}.{n}{path.suffix}")
        n += 1
    path.replace(backup)
    return str(backup)


def write_tsv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".partial")
    with tmp.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(path)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".partial")
    if hasattr(payload, "__dataclass_fields__"):
        payload = asdict(payload)
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def sort_by_date(rows: list[dict], key: str) -> list[dict]:
    return sorted(rows, key=lambda row: (row.get(key) or "9999-99-99", str(row.get("id") or row.get("accession") or "")))
