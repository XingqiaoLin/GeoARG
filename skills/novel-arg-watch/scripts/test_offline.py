#!/usr/bin/env python3
"""Offline checks for date parsing, classify, sorting, and empty input."""

from __future__ import annotations

import csv
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import crossvalidate
import search_after_date
import validate_evidence
from crossvalidate import OUTPUT_FIELDS, classify, dump, flag_label
from lib import (
    SKILL_VERSION,
    dedup_key,
    exit_code_for_run,
    parse_date,
    parse_pubmed_xml,
    require_day,
    rotate_existing,
    sort_by_date,
    split_sentences,
    vs_cutoff,
    write_tsv,
)
from queries import PROFILES, alias_variants, epmc_queries, expand_aliases, pubmed_queries
from screen_candidates import screen_text


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


PUBMED_XML = """<PubmedArticleSet><PubmedArticle>
<MedlineCitation><PMID>42075228</PMID><Article>
<Journal><Title>Microorganisms</Title>
<JournalIssue><PubDate><Year>2026</Year><Month>Apr</Month></PubDate></JournalIssue></Journal>
<ArticleTitle>Identification of MPN_080 as a Novel Determinant</ArticleTitle>
<Abstract><AbstractText>Overexpression increased MICs.</AbstractText></Abstract>
<ArticleDate DateType="Electronic"><Year>2026</Year><Month>04</Month><Day>05</Day></ArticleDate>
<PublicationTypeList><PublicationType>Journal Article</PublicationType></PublicationTypeList>
</Article></MedlineCitation>
<PubmedData><ArticleIdList>
<ArticleId IdType="doi">10.3390/microorganisms14040831</ArticleId>
<ArticleId IdType="pmc">PMC13118816</ArticleId>
</ArticleIdList></PubmedData>
</PubmedArticle></PubmedArticleSet>"""


def test_query_profiles() -> None:
    counts = {}
    for profile in PROFILES:
        queries = epmc_queries(profile)
        names = [name for name, _ in queries]
        check(len(names) == len(set(names)), f"{profile} has duplicate query names")
        check(all("{date}" in query for _n, query in queries), f"{profile} missing date placeholder")
        counts[profile] = len(queries)
        pm = pubmed_queries(profile)
        check(all("{date}" in query for _n, query in pm), f"{profile} pubmed missing date")
        check(len(pm) >= 3, f"{profile} pubmed too few")
    check(counts["broad"] > counts["core"], counts)
    check(counts["max"] > counts["broad"], counts)
    try:
        epmc_queries("nope")
    except ValueError as exc:
        check("unknown profile" in str(exc), exc)
    else:
        raise SystemExit("FAIL: unknown profile should raise")


def test_query_covers_more_classes() -> None:
    joined = " ".join(query for _n, query in epmc_queries("broad"))
    for term in ("vancomycin", "tigecycline", "rifampi", "trimethoprim", "efflux pump", "SRC:\"PPR\""):
        check(term in joined, f"broad profile missing {term}")


def test_alias_variants() -> None:
    variants = alias_variants("blaKPC-249")
    for expected in ("blaKPC-249", "KPC-249", "bla_KPC-249", "bla-KPC-249"):
        check(expected in variants, f"{expected} missing from {variants}")
    variants = alias_variants("ant(9)-If")
    check("ant9-If" in variants, variants)
    check("ant(9)-If" == variants[0], variants)
    expanded = expand_aliases(["Lsa(F)", "lsaF"], limit=6)
    check(len(expanded) == 6 and expanded[0] == "Lsa(F)", expanded)


def test_alias_variants_drop_hyphen() -> None:
    """Papers write blaKPC249 in running text, so the hyphenless form must match."""
    variants = alias_variants("blaKPC-249")
    for needed in ("blaKPC-249", "KPC-249", "blaKPC249", "KPC249"):
        check(needed in variants, f"{needed} missing from {variants}")
    check("mcr10.6" in alias_variants("mcr-10.6"), alias_variants("mcr-10.6"))


def test_pubmed_xml_parse() -> None:
    rows = parse_pubmed_xml(PUBMED_XML)
    check(len(rows) == 1, rows)
    row = rows[0]
    check(row["pmid"] == "42075228", row)
    check(row["doi"] == "10.3390/microorganisms14040831", row)
    check(row["firstPublicationDate"] == "2026-04-05", row)
    check("MPN_080" in row["title"], row)
    check("MICs" in row["abstractText"], row)
    check(row["pubTypeList"]["pubType"] == ["Journal Article"], row)
    check(row["journalInfo"]["journal"]["title"] == "Microorganisms", row)


def test_dedup_key() -> None:
    a = {"doi": "10.1/ABC", "pmid": "1", "source": "MED", "id": "1"}
    b = {"doi": "10.1/abc.", "pmid": "2", "source": "PPR", "id": "9"}
    check(dedup_key(a) == dedup_key(b), (dedup_key(a), dedup_key(b)))
    check(dedup_key({"pmid": "7"}) == "pmid:7", dedup_key({"pmid": "7"}))
    check(dedup_key({"source": "PPR", "id": "X"}) == "PPR:X", "fallback key")


def test_date_clauses() -> None:
    check(
        search_after_date.epmc_date_clause("2026-03-29", "2026-09-06")
        == "FIRST_PDATE:[2026-03-29 TO 2026-09-06]",
        "epmc clause",
    )
    check("3000-01-01" in search_after_date.epmc_date_clause("2026-03-29", None), "open ended")
    clause = search_after_date.pubmed_date_clause("2026-03-29", "2026-09-06")
    check(clause == '"2026/03/29"[EDAT] : "2026/09/06"[EDAT]', clause)


def test_extra_queries() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "q.txt"
        path.write_text(
            "# comment\nq_named\tTITLE:\"blaZZZ-1\"\nTITLE:\"unnamed query\"\n",
            encoding="utf-8",
        )
        got = search_after_date.load_extra_queries(path, ["TITLE:\"cli\""])
        names = [n for n, _q in got]
        check(names[0] == "q_user_01", got)
        check("q_named" in names, got)
        check(len(got) == 3, got)


def test_window_status() -> None:
    ws = search_after_date.window_status
    check(ws("2026-04-05", "day", "2026-03-29", "2026-09-06") == "in_window", "inside")
    check(ws("2026-02-27", "day", "2026-03-29", "2026-09-06") == "before_since", "older EDAT hit")
    check(ws("2026-10-01", "day", "2026-03-29", "2026-09-06") == "after_until", "past until")
    check(ws("", "missing", "2026-03-29", None) == "unknown", "no date")
    check(ws("2026-03", "month", "2026-03-29", None) == "unresolved", "coarse date")


def test_screen_rejects_bare_stems() -> None:
    """Broader vocabulary must not match author names or unrelated acronyms."""
    for title, abstract in [
        ("From 2-Azido Products to Complex Heterocycles: the Ugi MCR in Modern Synthesis", "A new MCR route."),
        ("A novel biomarker reported by van Dijk and colleagues", "New cohort analysis."),
        ("Cryo-EM structural analysis of liposome-reconstituted AcrB", "Novel substrate density maps."),
    ]:
        got = screen_text(title, abstract)
        check(got["promoted"] is False, f"{title}: {got}")


def test_screen_score_ranks_named_genes_first() -> None:
    named = screen_text(
        "Phenotypic and molecular characterization of a novel blaKPC-202 variant",
        "The gene was cloned into E. coli and raised meropenem MICs.",
    )
    generic = screen_text(
        "Antibiotic resistance trends in a regional hospital network",
        "Susceptibility testing showed a novel rise in resistance rates.",
    )
    check(named["screen_score"] > generic["screen_score"], (named, generic))
    check(named["evidence_hint"] == "gene_level_language", named)
    check(screen_text("", "")["screen_score"] == 0, "empty title scores 0")


def test_screen_excludes_eukaryote_and_review_framing() -> None:
    for title in [
        "Antimicrobial Resistance Across the Farm-to-Fork Continuum: A One Health Perspective",
        "Advances on anti-cancer combination therapies targeting DNA repair",
        "AI agent-based discovery of antimicrobial peptides against resistant bacteria",
        "Ferroptosis key genes and immune infiltration in Legionnaires' disease",
    ]:
        got = screen_text(title, "Novel resistance gene analysis with MIC testing.")
        check(got["promoted"] is False, f"{title}: {got}")


def test_screen_weak_tier() -> None:
    weak = screen_text(
        "A genome survey of blaOXA-1422, a designated class D beta-lactamase allele",
        "The allele was found in a canine bite wound isolate collection.",
    )
    check(weak["screen_status"] == "review_candidate_weak", weak)
    check(weak["promoted"] is False, weak)
    strong = screen_text(
        "A novel carbapenemase blaGUA-1 confers resistance in Pseudomonas",
        "Cloning into E. coli raised meropenem MICs.",
    )
    check(strong["screen_status"] == "review_candidate", strong)
    check(strong["promoted"] is True, strong)
    off = screen_text("Piperacillin-tazobactam versus colistin for pneumonia", "A clinical trial.")
    check(off["screen_status"] == "not_candidate", off)


def test_screen_broader_vocabulary() -> None:
    for title, abstract in [
        ("A novel vanM-like glycopeptide resistance gene cluster", "Knockout lowered vancomycin MIC."),
        ("tet(X8), a new tigecycline resistance determinant", "Heterologous expression raised MICs."),
        ("Novel efflux pump gene tmexCD5 confers multidrug resistance", "Complementation restored resistance."),
    ]:
        got = screen_text(title, abstract)
        check(got["screen_status"] == "review_candidate", f"{title}: {got}")


def test_split_sentences() -> None:
    text = "The gene was cloned into E. coli DH5a. MICs rose 64-fold (Fig. 2A). Purified protein was assayed."
    got = split_sentences(text)
    check(len(got) == 3, got)
    check("E. coli DH5a" in got[0], got)
    check(got[1].startswith("MICs rose"), got)
    check(split_sentences("") == [], "empty text")


def test_evidence_requires_gene_in_same_window() -> None:
    """An experiment sentence that never names the gene is not evidence."""
    pattern = validate_evidence.mention_re(["blaXYZ-1"])
    windows = validate_evidence.build_windows(
        [("Results", "A knockout mutant showed a 32-fold decrease in the meropenem MIC.")]
    )
    label, quotes, _counts, _body = validate_evidence.classify_windows(windows, pattern)
    check(label == "no_evidence_found", label)
    check(quotes == [], quotes)


def test_evidence_two_sentence_window() -> None:
    pattern = validate_evidence.mention_re(["blaGUA-1"])
    windows = validate_evidence.build_windows(
        [("Results", "The blaGUA-1 gene was cloned into pET28a. MICs of ceftazidime increased 32-fold.")]
    )
    label, quotes, _counts, in_body = validate_evidence.classify_windows(windows, pattern)
    check(label == "gene_level_causal", label)
    check(quotes and "blaGUA-1" in quotes[0]["quote"], quotes)
    check(quotes[0]["section"] == "Results", quotes)
    check(in_body is True, "Results is body text")


def test_pcr_is_not_a_plasmid_name() -> None:
    """A case-insensitive plasmid pattern read `PCR` as the vector `pCR`."""
    check(not validate_evidence.PLASMID_NAME.search("PCR screening was performed"), "PCR matched")
    for good in ("pET28a", "pUC19", "pHSG398", "pMD19", "pSET2", "pUCP24", "pAM401"):
        check(bool(validate_evidence.PLASMID_NAME.search(f"cloned into {good} and assayed")), good)
    pattern = validate_evidence.mention_re(["Lsa(F)"])
    windows = validate_evidence.build_windows(
        [
            (
                "Prevalence",
                "To evaluate the prevalence of the Lsa(F) gene, PCR screening was performed on 26 isolates. "
                "Genes linked to decreased susceptibility to tiamulin were also investigated.",
            )
        ]
    )
    label, _quotes, _counts, _body = validate_evidence.classify_windows(windows, pattern)
    check(label == "cooccurrence_only", f"PCR prevalence should not be causal, got {label}")


def test_recombinant_strain_counts_as_gene_level() -> None:
    """Real miss: `recombinant strain ... 32-fold increase in MIC` was scored biochemical."""
    pattern = validate_evidence.mention_re(["ant(9)-If"])
    text = (
        "Compared with the control strain JH2-2/pAM401, the recombinant strain JH2-2/pAM401-ant(9)-If "
        "demonstrated a 32-fold increase in the MIC of spectinomycin. ANT(9)-If demonstrated high catalytic "
        "efficiency with a kcat/Km value of 8.78e4."
    )
    windows = validate_evidence.build_windows([("Results", text)])
    label, quotes, _counts, _body = validate_evidence.classify_windows(windows, pattern)
    check(label == "gene_level_causal", f"expected gene_level_causal, got {label}")
    check("32-fold" in quotes[0]["quote"], quotes[0]["quote"][:80])


def test_abstract_only_evidence_is_not_a_pass() -> None:
    pattern = validate_evidence.mention_re(["blaGUA-1"])
    windows = validate_evidence.build_windows(
        [("Abstract", "Heterologous expression of blaGUA-1 increased the ceftazidime MIC 32-fold.")]
    )
    label, _quotes, _counts, in_body = validate_evidence.classify_windows(windows, pattern)
    check(label == "gene_level_causal", label)
    check(in_body is False, "abstract is not body")
    check(
        validate_evidence.novel_call("no_earlier_record_found", "validated_gene_level_abstract_only")
        == "hold_abstract_only_evidence",
        "abstract-only must not pass",
    )


def test_quote_ranking_prefers_body_and_fold_change() -> None:
    weak = validate_evidence.quote_strength("Abstract", "The gene conferred resistance to tiamulin.")
    strong = validate_evidence.quote_strength(
        "Results", "The gene was cloned into pSET2 and the MIC increased eightfold, an 8-fold change."
    )
    check(strong > weak, f"{strong} !> {weak}")
    screening = validate_evidence.quote_strength("Results", "PCR screening showed decreased susceptibility.")
    check(strong > screening, f"{strong} !> {screening}")


def test_evidence_fixtures() -> None:
    path = Path(__file__).resolve().parent.parent / "examples" / "evidence_cases.tsv"
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    check(len(rows) >= 8, "evidence fixtures too few")
    seen = set()
    for row in rows:
        aliases = [a.strip() for a in row["aliases"].split(";") if a.strip()]
        pattern = validate_evidence.mention_re(validate_evidence.expand_aliases(aliases))
        windows = validate_evidence.build_windows([("Results", row["text"])])
        label, quotes, _counts, _body = validate_evidence.classify_windows(windows, pattern)
        check(label == row["expected_class"], f"{row['gene']}: expected {row['expected_class']}, got {label}")
        if label == "gene_level_causal":
            check(bool(quotes), f"{row['gene']}: gene_level_causal without a quote")
        seen.add(label)
    for needed in ("gene_level_causal", "biochemical_only", "cooccurrence_only", "no_evidence_found"):
        check(needed in seen, f"evidence fixtures missing {needed}")


def test_validation_status_mapping() -> None:
    for label, status in validate_evidence.VALIDATION_BY_CLASS.items():
        if label == "gene_level_causal":
            check(status == "validated_gene_level", status)
        else:
            check(status.startswith("not_validated"), f"{label} -> {status}")


def test_only_gene_level_can_pass() -> None:
    """Nothing except body-level causal evidence may reach a pass call."""
    statuses = set(validate_evidence.VALIDATION_BY_CLASS.values()) | {
        "insufficient_evidence",
        "abstract_claim_only",
        "validated_gene_level_abstract_only",
    }
    passing = {
        status
        for status in statuses
        if validate_evidence.novel_call("no_earlier_record_found", status)
        == "pass_date_gate_and_gene_level_evidence"
    }
    check(passing == {"validated_gene_level"}, f"unexpected passing statuses: {passing}")


def test_novel_call_needs_both_gates() -> None:
    call = validate_evidence.novel_call
    check(
        call("no_earlier_record_found", "validated_gene_level") == "pass_date_gate_and_gene_level_evidence",
        "both gates pass",
    )
    check(call("preprint_before_since", "validated_gene_level") == "drop_earlier_public_record", "date drop wins")
    check(call("no_earlier_record_found", "insufficient_evidence") == "hold_no_full_text", "no full text")
    check(
        call("no_earlier_record_found", "not_validated_cooccurrence") == "hold_not_gene_level_evidence",
        "cooccurrence is not validation",
    )
    check(
        call("no_earlier_record_found", "abstract_claim_only") == "hold_abstract_only_evidence",
        "abstract claim is not validation",
    )
    check(
        call("provisional_sequence_before_since", "validated_gene_level") == "hold_date_gate_unresolved",
        "provisional date gate holds",
    )
    check(call("", "validated_gene_level") == "hold_date_gate_not_run", "no date gate")


def test_no_absolute_paths_in_skill() -> None:
    """A skill that hard-codes one machine's paths is not portable."""
    skill_dir = Path(__file__).resolve().parent.parent
    # Assembled from fragments so this check does not flag its own source line.
    pattern = re.compile("|".join(["/" + "work/", "/" + "Users/", "/" + "home/[a-z]", "[A-Z]:" + re.escape("\\\\")]))
    bad = []
    for path in sorted(skill_dir.rglob("*")):
        if not path.is_file() or path.suffix not in {".py", ".md", ".yaml", ".tsv"}:
            continue
        if "__pycache__" in path.parts:
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if pattern.search(line):
                bad.append(f"{path.relative_to(skill_dir)}:{lineno}: {line.strip()[:80]}")
    check(not bad, "absolute paths found:\n" + "\n".join(bad))


def test_stdlib_only() -> None:
    """Codex users may have nothing installed, so third-party imports are out."""
    scripts = Path(__file__).resolve().parent
    allowed = {
        "argparse", "calendar", "csv", "dataclasses", "datetime", "hashlib", "html",
        "json", "pathlib", "re", "shutil", "subprocess", "sys", "tempfile", "time",
        "typing", "urllib", "uuid", "xml", "collections", "itertools", "functools",
        "os", "textwrap", "unicodedata", "__future__",
    }
    local = {p.stem for p in scripts.glob("*.py")}
    bad = []
    for path in sorted(scripts.glob("*.py")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            match = re.match(r"\s*(?:import|from)\s+([A-Za-z_][\w.]*)", line)
            if not match:
                continue
            root = match.group(1).split(".")[0]
            if root not in allowed and root not in local:
                bad.append(f"{path.name}:{lineno}: {root}")
    check(not bad, "non-stdlib imports: " + "; ".join(bad))


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
    test_query_profiles()
    test_query_covers_more_classes()
    test_alias_variants()
    test_alias_variants_drop_hyphen()
    test_pubmed_xml_parse()
    test_dedup_key()
    test_date_clauses()
    test_extra_queries()
    test_window_status()
    test_screen_rejects_bare_stems()
    test_screen_score_ranks_named_genes_first()
    test_screen_excludes_eukaryote_and_review_framing()
    test_screen_weak_tier()
    test_screen_broader_vocabulary()
    test_split_sentences()
    test_evidence_requires_gene_in_same_window()
    test_evidence_two_sentence_window()
    test_evidence_fixtures()
    test_pcr_is_not_a_plasmid_name()
    test_recombinant_strain_counts_as_gene_level()
    test_abstract_only_evidence_is_not_a_pass()
    test_quote_ranking_prefers_body_and_fold_change()
    test_validation_status_mapping()
    test_only_gene_level_can_pass()
    test_novel_call_needs_both_gates()
    test_no_absolute_paths_in_skill()
    test_stdlib_only()
    print("offline checks passed")


if __name__ == "__main__":
    main()
