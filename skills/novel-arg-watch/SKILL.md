---
name: novel-arg-watch
description: >-
  Date-bounded search and first-public-date cross-validation for novel antimicrobial
  resistance genes (ARGs). Accepts a cutoff date, retrieves later papers, screens
  candidates, then flags any named gene whose preprint or earlier article predates
  the cutoff. Use when the user asks to find novel ARGs after a date, watch new
  resistance genes, cross-validate preprints vs formal papers, or continue a
  novel-ARG literature audit.
---

# Novel ARG watch

Search papers on or after a user-specified date, then decide novelty by **first public appearance**, not by formal publication date alone.

某个 arg 正式发文在 某日期之后，但 preprint 在某日期之前，这种也不能算 novel arg

Scripts never emit a finished novel-ARG conclusion. `novel_for_cutoff` stays false. Sequence fetch is not part of the default run.

`$SKILL_DIR` is the folder that contains this `SKILL.md`. Run every command from the user's workspace with that path. Do not hard-code `.cursor` or `novel/`.

## Cursor or Codex

This folder is the whole skill. Copy it, or open a repo that already contains it.

| Tool | Where it should live |
| --- | --- |
| This repo | `skills/novel-arg-watch/` |
| Cursor | `.cursor/skills/novel-arg-watch/` |
| Codex | `.agents/skills/novel-arg-watch/` or `~/.codex/skills/novel-arg-watch/` |

Same files either way. Before a real search, run:

```bash
python $SKILL_DIR/scripts/verify.py
```

`verify.py` is offline. Exit `0` means frontmatter, screen fixtures, date-gate, and exit-code checks passed.

## Inputs

- `--since` (required): inclusive cutoff, day precision `YYYY-MM-DD`
- `--until` (optional): inclusive end date, same precision
- Output directory: the path the user names

Month-only values such as `2026-03` are rejected for `--since` / `--until`. On a gene row they are kept as `month` precision and force `insufficient_evidence`.

If the user gives only one date, treat it as `--since`.

## Workflow

Copy and track. Stop after step 5 unless the user asked for sequences.

```
- [ ] 0. python $SKILL_DIR/scripts/verify.py
- [ ] 1. Search after --since
- [ ] 2. Screen candidates (keyword != novel ARG)
- [ ] 3. Extract named gene objects
- [ ] 4. Cross-validate first public date
- [ ] 5. Classify novelty / evidence (human)
- [ ] 6. Sequences only if the user asked
```

### 1. Search after the cutoff

```bash
python $SKILL_DIR/scripts/search_after_date.py \
  --since YYYY-MM-DD \
  --until YYYY-MM-DD \
  --output-dir path/to/watch_YYYY-MM-DD
```

- Paginate Europe PMC. Do not stop at the first 1000 hits.
- Keep preprints (`SRC:PPR`) in the hit table. They are evidence, not automatically eligible.
- Formal date basis: first online / `firstPublicationDate`. Keep issue dates only for checking.
- Read `search_audit.json`. If `search_complete` is false, later “no hit” is `insufficient_evidence`, not absence.
- Non-zero exit: do not treat the hit table as a finished search.

### 2. Screen; do not promote keyword hits

```bash
python $SKILL_DIR/scripts/screen_candidates.py \
  --input path/to/watch_YYYY-MM-DD/search_hits.tsv \
  --output path/to/watch_YYYY-MM-DD/screened.tsv
```

`review_candidate` / `promoted=true` only means the paper is worth naming genes. It is not experimental validation.

Exclude on title/abstract when the script says:

- `exclude_review`
- `exclude_offtopic` (inhibitor, drug, phage, `sp. nov.`)
- `exclude_known_report` (first regional / new plasmid / known gene, no novel-gene language)

Golden cases: `$SKILL_DIR/examples/screen_cases.tsv`. `verify.py` checks them.

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

Exact alias match in title or abstract only. Literature dates can exclude. NCBI `CreateDate` plus the **current** title cannot prove the name existed on that day.

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

### 5. Classify survivors

Read [reference.md](reference.md) before calling anything “novel ARG”. Record novelty class and evidence class. Strain MIC + PCR/WGS detection is not validation.

`no_earlier_record_found` is not review-complete and is not a novel ARG.

### 6. Sequences only if asked

Do not start sequence download after a date-only request. Sequence helpers are not in this skill package.

## Output

Lead with DROP, then HOLD, then OPEN. Never present the search-hit count as the novel-ARG count. Never treat script `OPEN` or `promoted` as a determined novel ARG.

Each row carries `skill_version` and `run_id`. `*.run.json` also records `argv`, Python version, and SHA-256 of the skill files. Re-running the same output path moves the previous file to `*.bak-<run_id>.*` instead of overwriting it. Month/year dates stay in `formal_date_raw`; `formal_date` is day-precision only.
