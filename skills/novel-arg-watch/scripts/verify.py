#!/usr/bin/env python3
"""Offline verification for this skill. No network. Exit 0 only if all checks pass.

Run from anywhere:
  python path/to/novel-arg-watch/scripts/verify.py
"""

from __future__ import annotations

import csv
import re
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
SKILL_DIR = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))

import screen_candidates
import test_offline
from screen_candidates import screen_text


def fail(message: str) -> None:
    raise SystemExit(f"VERIFY_FAIL: {message}")


def check_frontmatter() -> None:
    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    if not match:
        fail("SKILL.md missing YAML frontmatter")
    block = match.group(1)
    if "name: novel-arg-watch" not in block:
        fail("frontmatter name")
    if "description:" not in block:
        fail("frontmatter description")
    for name in (
        "search_after_date.py",
        "crossvalidate.py",
        "screen_candidates.py",
        "validate_evidence.py",
        "queries.py",
        "lib.py",
        "install.py",
        "test_offline.py",
    ):
        if not (SCRIPTS / name).exists():
            fail(f"missing script {name}")
    if not (SKILL_DIR / "reference.md").exists():
        fail("missing reference.md")
    for name in ("screen_cases.tsv", "evidence_cases.tsv"):
        if not (SKILL_DIR / "examples" / name).exists():
            fail(f"missing examples/{name}")


def check_python_version() -> None:
    from lib import MIN_PYTHON

    if sys.version_info < MIN_PYTHON:
        fail(f"needs Python {'.'.join(map(str, MIN_PYTHON))}+, running {sys.version.split()[0]}")


def check_scripts_have_help() -> None:
    """Anyone picking this up should be able to read --help without a network."""
    import subprocess

    for name in ("search_after_date.py", "screen_candidates.py", "crossvalidate.py", "validate_evidence.py"):
        proc = subprocess.run(
            [sys.executable, str(SCRIPTS / name), "--help"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if proc.returncode != 0:
            fail(f"{name} --help exited {proc.returncode}: {proc.stderr.strip()[:200]}")


def check_screen_fixtures() -> None:
    path = SKILL_DIR / "examples" / "screen_cases.tsv"
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    if len(rows) < 12:
        fail("screen fixtures too few")
    statuses = {row["expected_status"] for row in rows}
    for needed in ("review_candidate", "review_candidate_weak", "exclude_review", "not_candidate"):
        if needed not in statuses:
            fail(f"screen fixtures missing a {needed} case")
    for row in rows:
        got = screen_text(row["title"], row.get("abstract", ""), row.get("publication_types", ""))
        expected = row["expected_status"]
        if got["screen_status"] != expected:
            fail(f"{row['title'][:60]!r}: expected {expected}, got {got['screen_status']}")
        if expected == "review_candidate" and not got["promoted"]:
            fail("review_candidate must set promoted")
        if expected != "review_candidate" and got["promoted"]:
            fail(f"non-candidate promoted: {row['title'][:60]!r}")


def check_screen_missing_title_exits() -> None:
    argv = sys.argv
    try:
        with tempfile.TemporaryDirectory() as tmp:
            inp = Path(tmp) / "in.tsv"
            inp.write_text("title\tabstract\n\tno title here\n", encoding="utf-8")
            out = Path(tmp) / "out.tsv"
            sys.argv = ["screen_candidates.py", "--input", str(inp), "--output", str(out)]
            try:
                screen_candidates.main()
            except SystemExit as exc:
                if exc.code != 2:
                    fail(f"missing title expected exit 2, got {exc.code}")
            else:
                fail("missing title exited 0")
    finally:
        sys.argv = argv


def main() -> None:
    check_python_version()
    check_frontmatter()
    check_screen_fixtures()
    check_screen_missing_title_exits()
    check_scripts_have_help()
    test_offline.main()
    print(f"verify passed ({SKILL_DIR})")


if __name__ == "__main__":
    main()
