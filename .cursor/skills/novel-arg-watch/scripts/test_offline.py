#!/usr/bin/env python3
"""Offline checks for date parsing, classify, sorting, and empty input."""

from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import crossvalidate
from crossvalidate import OUTPUT_FIELDS, classify, dump, flag_label
from lib import SKILL_VERSION, exit_code_for_run, parse_date, require_day, rotate_existing, sort_by_date, vs_cutoff, write_tsv


def check(cond: bool, message: str) -> None:
    if not cond:
        raise SystemExit(f"FAIL: {message}")


def test_parse_date() -> None:
    empty = parse_date("")
    check(empty.normalized == "" and empty.precision == "missing" and empty.original == "", "empty is missing")
    day = parse_date("2026-03-29")
    check(day.normalized == "2026-03-29" and day.precision == "day" and day.original == "2026-03-29", "day")
    slash = parse_date("2026/03/29")
    check(slash.normalized == "2026-03-29" and slash.original == "2026/03/29", "slash day keeps original")
    month = parse_date("2026-03")
    check(month.normalized == "2026-03" and month.precision == "month" and month.original == "2026-03", "month not coerced")
    slash_month = parse_date("2026/03")
    check(slash_month.original == "2026/03" and slash_month.normalized == "2026-03" and slash_month.precision == "month", "slash month original")
    year = parse_date("2026")
    check(year.normalized == "2026" and year.precision == "year" and year.original == "2026", "year")
    check(parse_date("2026-13-01").precision == "invalid", "bad month day")
    check(parse_date("2026-02-31").precision == "invalid", "bad calendar day")
    check(parse_date("2026-13").precision == "invalid", "bad month")
    free = parse_date("March 2026")
    check(free.precision == "invalid" and free.original == "March 2026", "free text original kept")


def test_require_day() -> None:
    try:
        require_day("2026-03", "--since")
    except SystemExit as exc:
        check("month precision" in str(exc), exc)
    else:
        raise SystemExit("FAIL: month since should exit")
    try:
        require_day("not-a-date", "--since")
    except SystemExit as exc:
        check("not a valid date" in str(exc), exc)
    else:
        raise SystemExit("FAIL: invalid since should exit")


def test_vs_cutoff() -> None:
    check(vs_cutoff("2026-02-27", "day", "2026-03-29") == "before", "day before")
    check(vs_cutoff("2026-03-29", "day", "2026-03-29") == "on_or_after", "on cutoff")
    check(vs_cutoff("2026-03", "month", "2026-03-29") == "unresolved", "month overlap")
    check(vs_cutoff("2026-02", "month", "2026-03-29") == "before", "month entirely before")
    check(vs_cutoff("2026-04", "month", "2026-03-29") == "on_or_after", "month after")


def test_classify_empty_is_not_pass() -> None:
    status = classify(
        since="2026-03-29",
        formal="",
        formal_precision="missing",
        preprint_before=False,
        article_before=False,
        unresolved_lit=False,
        current_seq_before=False,
        lit_search_complete=True,
        seq_search_complete=True,
    )
    check(status == "insufficient_evidence", f"empty dates -> {status}")
    check(flag_label(status) == "HOLD", "empty is HOLD")


def test_classify_incomplete_search() -> None:
    status = classify(
        since="2026-03-29",
        formal="2026-04-07",
        formal_precision="day",
        preprint_before=False,
        article_before=False,
        unresolved_lit=False,
        current_seq_before=False,
        lit_search_complete=False,
        seq_search_complete=True,
    )
    check(status == "insufficient_evidence", f"truncated -> {status}")


def test_classify_no_earlier_not_novel() -> None:
    status = classify(
        since="2026-03-29",
        formal="2026-04-07",
        formal_precision="day",
        preprint_before=False,
        article_before=False,
        unresolved_lit=False,
        current_seq_before=False,
        lit_search_complete=True,
        seq_search_complete=True,
    )
    check(status == "no_earlier_record_found", status)
    check(flag_label(status) == "OPEN", "open not keep")


def test_classify_preprint_and_seq() -> None:
    check(
        classify("2026-03-29", "2026-04-05", "day", True, False, False, True, True, True)
        == "preprint_before_since",
        "preprint wins over sequence",
    )
    check(
        classify("2026-03-29", "2026-04-15", "day", False, False, False, True, True, True)
        == "provisional_sequence_before_since",
        "unverified sequence is provisional",
    )
    check(
        classify("2026-03-29", "2026-02-27", "day", False, False, False, False, True, True)
        == "formal_before_since",
        "formal before",
    )
    check(
        classify("2026-03-29", "2026-03", "month", False, False, False, False, True, True)
        == "insufficient_evidence",
        "month formal",
    )


def test_sort_earliest() -> None:
    rows = [
        {"id": "late", "date": "2026-04-05"},
        {"id": "early", "date": "2026-02-27"},
        {"id": "mid", "date": "2026-03-01"},
    ]
    ordered = sort_by_date(rows, "date")
    check([r["id"] for r in ordered] == ["early", "mid", "late"], ordered)
    payload = dump(ordered, 1)
    check("2026-02-27" in payload and "early" in payload, payload)


def test_empty_genes_tsv() -> None:
    script = Path(__file__).resolve().parent / "crossvalidate.py"
    header = Path(__file__).resolve().parent.parent / "examples" / "genes.header.tsv"
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out.tsv"
        proc = subprocess.run(
            [sys.executable, str(script), "--since", "2026-03-29", "--genes", str(header), "--output", str(out)],
            check=False,
            capture_output=True,
            text=True,
        )
        check(proc.returncode == 0, proc.stderr or proc.stdout)
        with out.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle, delimiter="\t"))
        check(rows == [], f"expected 0 data rows, got {rows}")
        with out.open(encoding="utf-8", newline="") as handle:
            header_row = next(csv.reader(handle, delimiter="\t"))
        check(header_row == OUTPUT_FIELDS, header_row)
        meta = out.with_name("out.run.json")
        check(meta.exists(), "run metadata missing")


def test_exit_code_for_run() -> None:
    check(exit_code_for_run(errors=[], incomplete=False) == 0, "clean")
    check(exit_code_for_run(errors=None, incomplete=False) == 0, "none errors")
    check(exit_code_for_run(errors=[{"gene": "X"}], incomplete=False) == 2, "process error")
    check(exit_code_for_run(errors=[{"gene": "X"}], incomplete=True) == 2, "error wins")
    check(exit_code_for_run(errors=[], incomplete=True) == 3, "truncated")


def test_crossvalidate_error_exits_nonzero() -> None:
    orig = crossvalidate.review_one

    def boom(*_a, **_k):
        raise RuntimeError("forced")

    crossvalidate.review_one = boom
    argv = sys.argv
    try:
        with tempfile.TemporaryDirectory() as tmp:
            genes = Path(tmp) / "g.tsv"
            genes.write_text(
                "gene\taliases\tformal_date\tncbi_term\tcontext\taccessions\nX\tX\t2026-04-01\t\t\t\n",
                encoding="utf-8",
            )
            out = Path(tmp) / "out.tsv"
            sys.argv = ["crossvalidate.py", "--since", "2026-03-29", "--genes", str(genes), "--output", str(out)]
            try:
                crossvalidate.main()
            except SystemExit as exc:
                check(exc.code == 2, f"expected exit 2, got {exc.code}")
            else:
                raise SystemExit("FAIL: process error exited 0")
            with out.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))
            check(len(rows) == 1 and rows[0]["error"] == "forced", rows)
            check(out.with_name("out.run.json").exists(), "run json missing after failure")
    finally:
        sys.argv = argv
        crossvalidate.review_one = orig


def test_month_date_raw_in_output() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        genes = Path(tmp) / "g.tsv"
        genes.write_text(
            "gene\taliases\tformal_date\tncbi_term\tcontext\taccessions\nX\tX\t2026/03\t\t\t\n",
            encoding="utf-8",
        )
        parsed = crossvalidate.parse_genes(genes)
        check(parsed[0]["formal_date_raw"] == "2026/03", parsed)
        check(parsed[0]["formal_date"] == "2026-03", parsed)
        check(parsed[0]["formal_date_precision"] == "month", parsed)


def test_rerun_rotates_previous() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "out.tsv"
        write_tsv(path, [{"gene": "old"}], ["gene"])
        backup = rotate_existing(path, "run1")
        check(backup != "", "expected backup path")
        check(not path.exists(), "current path should be moved")
        check(Path(backup).read_text(encoding="utf-8").splitlines()[1] == "old", Path(backup).read_text())
        write_tsv(path, [{"gene": "new"}], ["gene"])
        check("old" in Path(backup).read_text(encoding="utf-8"), "previous content lost")
        check("new" in path.read_text(encoding="utf-8"), "new content missing")


def test_error_row_keeps_raw_and_version() -> None:
    orig = crossvalidate.review_one

    def boom(*_a, **_k):
        raise RuntimeError("forced")

    crossvalidate.review_one = boom
    argv = sys.argv
    try:
        with tempfile.TemporaryDirectory() as tmp:
            genes = Path(tmp) / "g.tsv"
            genes.write_text(
                "gene\taliases\tformal_date\tncbi_term\tcontext\taccessions\nX\tX\tMarch 2026\t\t\t\n",
                encoding="utf-8",
            )
            out = Path(tmp) / "out.tsv"
            sys.argv = ["crossvalidate.py", "--since", "2026-03-29", "--genes", str(genes), "--output", str(out)]
            try:
                crossvalidate.main()
            except SystemExit as exc:
                check(exc.code == 2, f"expected exit 2, got {exc.code}")
            else:
                raise SystemExit("FAIL: process error exited 0")
            with out.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))
            check(rows[0]["formal_date_raw"] == "March 2026", rows[0])
            check(rows[0]["formal_date_precision"] == "invalid", rows[0])
            check(rows[0]["skill_version"] == SKILL_VERSION, rows[0])
            check(rows[0]["run_id"], "missing run_id")
            meta = json.loads(out.with_name("out.run.json").read_text(encoding="utf-8"))
            check(meta["skill_version"] == SKILL_VERSION, meta)
            check("file_sha256" in meta and "crossvalidate.py" in meta["file_sha256"], meta)
            check(meta["run_id"] == rows[0]["run_id"], meta)
    finally:
        sys.argv = argv
        crossvalidate.review_one = orig


def test_write_empty_not_index_error() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "empty.tsv"
        write_tsv(path, [], OUTPUT_FIELDS)
        text = path.read_text(encoding="utf-8")
        check(text.splitlines()[0] == "\t".join(OUTPUT_FIELDS), text)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "empty.tsv"
        write_tsv(path, [], OUTPUT_FIELDS)
        text = path.read_text(encoding="utf-8")
        check(text.splitlines()[0] == "\t".join(OUTPUT_FIELDS), text)


def main() -> None:
    test_parse_date()
    test_require_day()
    test_vs_cutoff()
    test_classify_empty_is_not_pass()
    test_classify_incomplete_search()
    test_classify_no_earlier_not_novel()
    test_classify_preprint_and_seq()
    test_sort_earliest()
    test_write_empty_not_index_error()
    test_empty_genes_tsv()
    test_exit_code_for_run()
    test_crossvalidate_error_exits_nonzero()
    test_month_date_raw_in_output()
    test_rerun_rotates_previous()
    test_error_row_keeps_raw_and_version()
    print("offline checks passed")


if __name__ == "__main__":
    main()
