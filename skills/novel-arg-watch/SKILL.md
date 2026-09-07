---
name: novel-arg-watch
description: >-
  Date-bounded search and first-public-date cross-validation for novel antimicrobial
  resistance genes (ARGs). Accepts a cutoff date, retrieves later papers, screens
  candidates, then flags any named gene whose preprint or earlier article predates
  the cutoff. Also quotes the full-text sentence that proves a gene was
  experimentally validated at the gene level. Use when the user asks to find novel
  ARGs after a date, watch new resistance genes, cross-validate preprints vs formal
  papers, check whether a resistance gene was functionally confirmed, or continue a
  novel-ARG literature audit.
---

# Novel ARG watch

Search papers on or after a user-specified date, then decide novelty by **first public appearance**, not by formal publication date alone. A gene has to clear two gates: nothing about it was public before the cutoff, and the paper actually proved the gene causes resistance.

某个 arg 正式发文在 某日期之后，但 preprint 在某日期之前，这种也不能算 novel arg

只有论文正文里能引到"这个基因导致耐药"的原句，才算实验验证过的 ARG。摘要里的说法不算。

Scripts never emit a finished novel-ARG conclusion. `novel_for_cutoff` stays false. Sequence fetch is not part of the default run.

`$SKILL_DIR` is the folder that contains this `SKILL.md`. Run every command from the user's workspace with that path. Do not hard-code `.cursor` or `novel/`.

## Cursor or Codex

This folder is the whole skill. Copy it, or open a repo that already contains it.

| Tool | Where it should live |
| --- | --- |
| Cursor | `.cursor/skills/novel-arg-watch/` |
| Codex | `.agents/skills/novel-arg-watch/` or `~/.codex/skills/novel-arg-watch/` |

Same files either way. `install.py` copies the folder for you:

```bash
python $SKILL_DIR/scripts/install.py --codex      # ~/.codex/skills/novel-arg-watch
python $SKILL_DIR/scripts/install.py --cursor     # ./.cursor/skills/novel-arg-watch
```

Requirements: Python 3.9+ and outbound HTTPS. Nothing to `pip install` — every script is standard library only, and `verify.py` fails if that ever stops being true. No API key is needed for Europe PMC, PubMed, or NCBI at this request rate.

Before a real search, run:

```bash
python $SKILL_DIR/scripts/verify.py
```

`verify.py` is offline. Exit `0` means frontmatter, screen fixtures, evidence fixtures, date-gate, portability, and exit-code checks passed.

## Inputs

- `--since` (required): inclusive cutoff, day precision `YYYY-MM-DD`
- `--until` (optional): inclusive end date, same precision
- Output directory: the path the user names

Month-only values such as `2026-03` are rejected for `--since` / `--until`. On a gene row they are kept as `month` precision and force `insufficient_evidence`.

If the user gives only one date, treat it as `--since`.

## Workflow

Copy and track. Stop after step 6 unless the user asked for sequences.

```
- [ ] 0. python $SKILL_DIR/scripts/verify.py
- [ ] 1. Search after --since
- [ ] 2. Screen candidates (keyword != novel ARG)
- [ ] 3. Extract named gene objects
- [ ] 4. Cross-validate first public date (date gate)
- [ ] 5. Validate experimental evidence from full text (evidence gate)
- [ ] 6. Read the quotes and classify (human)
- [ ] 7. Sequences only if the user asked
```

### 1. Search after the cutoff

```bash
python $SKILL_DIR/scripts/search_after_date.py \
  --since YYYY-MM-DD \
  --until YYYY-MM-DD \
  --output-dir path/to/watch_YYYY-MM-DD
```

Two sources run by default: Europe PMC (journals plus `SRC:PPR` preprints) and PubMed. Queries are chunked by drug class and gene family, so one crowded query cannot hit the pagination ceiling and hide records.

| Flag | Default | Use |
| --- | --- | --- |
| `--profile` | `broad` | `core` is fastest, `max` is widest and slowest |
| `--sources` | `epmc,pubmed` | drop one if it is unreachable |
| `--page-size` | `1000` | Europe PMC page size |
| `--max-pages` | `40` | raise it when a query reports `truncated` |
| `--max-records` | `10000` | per-query PubMed cap |
| `--extra-query` | — | one more Europe PMC query; repeatable |
| `--query-file` | — | file of extra queries, optional `name<TAB>query` |

Widen further without editing the skill:

```bash
python $SKILL_DIR/scripts/search_after_date.py --since YYYY-MM-DD \
  --profile max --extra-query 'TITLE_ABS:"blaZZZ"' \
  --output-dir path/to/watch_YYYY-MM-DD
```

- Keep preprints in the hit table. They are evidence, not automatically eligible.
- Formal date basis: first online / `firstPublicationDate`. Keep issue dates only for checking.
- `in_window` says how each row relates to `--since` / `--until`. PubMed is searched by `EDAT`, an indexing date, so a paper first published earlier can come back. Those rows say `before_since` and are kept on purpose: an older paper that already names the gene is what step 4 needs.
- Read `search_audit.json`. If `search_complete` is false, later “no hit” is `insufficient_evidence`, not absence.
- Non-zero exit: do not treat the hit table as a finished search.

### 2. Screen; do not promote keyword hits

```bash
python $SKILL_DIR/scripts/screen_candidates.py \
  --input path/to/watch_YYYY-MM-DD/search_hits.tsv \
  --output path/to/watch_YYYY-MM-DD/screened.tsv
```

`review_candidate` / `promoted=true` only means the paper is worth naming genes. It is not experimental validation.

Rows come out sorted by `screen_score` (0–100), highest first, so a wide sweep stays readable. Score rises with a coined gene name, naming language, and gene-level wording; `evidence_hint` says which of those fired. The score ranks; it never decides.

| `screen_status` | Meaning |
| --- | --- |
| `review_candidate` | ARG plus novelty plus function language; name the genes |
| `review_candidate_weak` | names a gene or says “designated”, but no function wording; skim these, they are not promoted |
| `exclude_review` | review, meta-analysis, perspective, “advances in” |
| `exclude_offtopic` | inhibitor, phage, `sp. nov.`, peptide, antifungal, anti-cancer, plant extract |
| `exclude_known_report` | first regional report / new plasmid of a **known** gene |
| `not_candidate` | keywords only |

Do not skip `review_candidate_weak`. A paper that names a new allele in a genome survey often has no MIC wording in the abstract.

Screening reads the abstract, so run it on a `search_hits.tsv` that has one. Golden cases: `$SKILL_DIR/examples/screen_cases.tsv`. `verify.py` checks them.

### 3. Name the object

One named gene = one object. Merge papers that characterize the same name. Split a paper that reports several variants and judge each name.

Write a genes TSV (`gene`, `aliases`, `formal_date`, `ncbi_term`, optional `context`, optional `accessions`). See [examples/priority_genes.2026-03-29.tsv](examples/priority_genes.2026-03-29.tsv). Always put known accessions in `accessions`; name search alone can miss them.

### 4. Cross-validate (required; this is the date gate)

```bash
python $SKILL_DIR/scripts/crossvalidate.py \
  --since YYYY-MM-DD \
  --genes path/to/genes.tsv \
  --output path/to/watch_YYYY-MM-DD/crossvalidate.tsv
```

Europe PMC and PubMed are both queried per gene; `--no-pubmed` narrows it to Europe PMC. Each alias is expanded to its spelling variants (`blaKPC-249`, `KPC-249`, `bla_KPC-249`, `ant(9)-If` → `ant9-If`) and the list used is written to `alias_variants`. Exact alias match in title or abstract only. Literature dates can exclude. NCBI `CreateDate` plus the **current** title cannot prove the name existed on that day.

| `date_gate` | Meaning | Script print | `novel_for_cutoff` |
| --- | --- | --- | --- |
| `formal_before_since` | journal day date is before `--since` | DROP | false |
| `preprint_before_since` | same named object on a preprint before `--since` | DROP | false |
| `article_before_since` | earlier journal/article names the same object | DROP | false |
| `provisional_sequence_before_since` | current nuccore title matches; CreateDate before `--since`; name-at-create unverified | HOLD | false |
| `no_earlier_record_found` | search finished; no earlier literature hit | OPEN | false |
| `insufficient_evidence` | missing/coarse date, truncated search, or unresolved span | HOLD | false |

`review_status` is always `machine_screen`. Only a human pass that also records novelty class and evidence class may set `review_complete`.

`first_public_date` is literature plus formal day dates only. Current-title nuccore dates go in `earliest_current_named_nuccore_date`.

### 5. Validate the experiment (required; this is the evidence gate)

```bash
python $SKILL_DIR/scripts/validate_evidence.py \
  --genes path/to/genes.tsv \
  --crossvalidate path/to/watch_YYYY-MM-DD/crossvalidate.tsv \
  --output path/to/watch_YYYY-MM-DD/evidence.tsv
```

The genes TSV needs `gene` and `aliases`; add a `pmcid` column when you already know the paper, otherwise the script finds an open-access record by name. It pulls the Europe PMC full text, splits it into sentences, and keeps only windows of one or two sentences where **the gene name itself** sits next to an experiment and a susceptibility outcome. Every positive call ships the sentence in `quote` and its section in `quote_section`.

| `evidence_class` | What the text showed | `validation_status` |
| --- | --- | --- |
| `gene_level_causal` | gene cloned in / knocked out / complemented, or carried by a cloning host, plus an MIC or resistance change | `validated_gene_level` |
| `biochemical_only` | purified enzyme, kinetics, hydrolysis; no cell phenotype | `not_validated_biochemical_only` |
| `mobilization_only` | conjugation or plasmid transfer plus MIC; the whole plasmid moved, not the gene | `not_validated_transfer_only` |
| `cooccurrence_only` | isolate MIC plus PCR/WGS detection | `not_validated_cooccurrence` |
| `computational_only` | prediction, homology, docking, phylogeny | `not_validated_computational` |
| `no_full_text` | no open-access body text to read | `insufficient_evidence` |

Two extra guards, both deliberate:

- If gene-level wording exists **only** in the abstract or a caption, the status becomes `validated_gene_level_abstract_only`. A paper that claims it in the summary but never shows it in the body does not pass.
- `--allow-abstract` lets the script read an abstract when no full text exists. It then caps the result at `abstract_claim_only`, which never passes.

`novel_arg_call` joins both gates:

| `novel_arg_call` | Meaning |
| --- | --- |
| `drop_earlier_public_record` | the date gate already killed it |
| `pass_date_gate_and_gene_level_evidence` | no earlier record **and** a quoted gene-level experiment |
| `hold_abstract_only_evidence` | claim is summary-only |
| `hold_not_gene_level_evidence` | real paper, but the experiment does not isolate this gene |
| `hold_no_full_text` | cannot be judged; ask for the PDF or a `pmcid` |
| `hold_date_gate_unresolved` | evidence is fine, the date is not settled |

A `pass` means a quotable sentence exists, not that a human agreed with it. Golden cases: `$SKILL_DIR/examples/evidence_cases.tsv`.

### 6. Read the quotes and classify

Read [reference.md](reference.md) before calling anything “novel ARG”. Open every `pass` row and read `quote`, then `supporting_quotes`. Confirm the sentence is about **this** gene and that the control is an empty vector or a parent strain. Only then may a human set `review_complete`.

`no_earlier_record_found` on its own is not review-complete and is not a novel ARG.

### 7. Sequences only if asked

Do not start sequence download after a date-only request. Sequence helpers are not in this skill package.

## Output

Lead with DROP, then HOLD, then OPEN. Never present the search-hit count as the novel-ARG count. Never treat script `OPEN` or `promoted` as a determined novel ARG.

Never present `screen_score` as a novelty score; it only orders the reading queue.

When you report a validated gene, quote the sentence and name its section. A validation claim with no quote behind it is not reportable.

Each row carries `skill_version` and `run_id`. `*.run.json` also records `argv`, Python version, and SHA-256 of the skill files. Re-running the same output path moves the previous file to `*.bak-<run_id>.*` instead of overwriting it. Month/year dates stay in `formal_date_raw`; `formal_date` is day-precision only.
