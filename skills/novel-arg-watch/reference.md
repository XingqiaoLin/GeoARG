# Novelty and evidence rules

These rules decide what may be called a novel ARG after a cutoff date. They do not extract primers, constructs, or wet-lab protocols.

Scripts stop at `machine_screen`. A determined novel ARG also needs `review_complete`, a novelty class, and an evidence class.

## Date rule

The cutoff is inclusive and must be a day. The literature clock starts at the earliest **published** naming of the same object:

1. matching preprint (Europe PMC `PPR`, bioRxiv, medRxiv, Preprints.org, Research Square, …)
2. earlier journal article or genome announcement that **names** the gene in that publication
3. formal first-online date of the index paper, when it has day precision

某个 arg 正式发文在 某日期之后，但 preprint 在某日期之前，这种也不能算 novel arg

The same holds for an earlier article that already uses the name.

Month or year dates are not coerced to a day. If the span overlaps `--since`, the gate is `insufficient_evidence`.

## Sequence records are not a naming-time proof

NCBI `CreateDate` plus the **current** definition-line title is not the title at creation. RefSeq and GenBank often back-fill a later official name.

Treat that pair as `current_title_only_unverified`:

- store it in `earliest_current_named_nuccore_date`
- if that CreateDate is before `--since`, the gate is `provisional_sequence_before_since` (HOLD), not a finished exclude
- do not write “当时已经命名” unless a dated GenBank history or contemporaneous release shows the name

Do not auto-drop on RefSeq WP protein `CreateDate`. An unnamed CDS deposited before the paper also does not, by itself, kill a newly designated gene.

## Same named object

Merge records that use the same official or paper-designated name, including `bla` prefixes and trivial punctuation (`KPC-249`, `blaKPC-249`, `bla_KPC-249`). Running text also drops the hyphen (`blaKPC249`), so alias expansion covers that form; without it the cloning sentence in the KPC-249 paper is invisible.

Two papers on OXA-1054 are one gene. A paper that lists five OXA numbers is five objects.

## Novelty classes (keep separate)

| Class | Counts as “new ARG family”? |
| --- | --- |
| New gene family | only this class, and only if first **literature** public date ≥ cutoff |
| New family member | new member, not a new family |
| New allele / variant | allele-level only |
| First resistance function of a known gene | function claim, not a new sequence name |

## Evidence classes

| Class | Functionally validated? |
| --- | --- |
| Heterologous expression / complementation / knockout that changes MIC of that gene | yes, gene-level causal |
| Purified-enzyme kinetics without a cell phenotype | biochemical only |
| Conjugation or plasmid transfer plus MIC | no — the whole plasmid moved |
| Isolate MIC plus PCR/WGS detection | no |
| Computational prediction or catalog membership | no |

## The quote rule

`validate_evidence.py` decides these classes from the paper's own text, and it may only say `validated_gene_level` when it can hand back the sentence. The requirements, in order:

1. **The gene name is in the window.** A methods sentence about "a knockout mutant" that never names the gene proves nothing about this gene. Windows are one or two consecutive sentences, so a claim split across a sentence boundary still counts.
2. **A gene-level manipulation.** Cloning into a vector, a named plasmid, heterologous or over-expression, knockout, complementation, or a cloning host such as DH5α, BL21, TOP10, JH2-2, RN4220 carrying the gene. AST quality-control strains (ATCC 25922 and friends) are excluded on purpose: they appear in surveillance papers that never touch the gene.
3. **A susceptibility outcome.** An MIC, a fold change, conferred or reduced resistance, a restored phenotype, a zone of inhibition.
4. **Body text, not just the abstract.** Gene-level wording found only in the abstract or a figure caption yields `validated_gene_level_abstract_only`, which does not pass. Papers do overclaim in summaries.

Both gates must clear before a gene is reportable: `no_earlier_record_found` **and** `validated_gene_level`. That combination is `pass_date_gate_and_gene_level_evidence`. It still needs a human to read the quote, because a regex cannot tell whether the control was the right one.

Two failure modes this gate is tuned against, both found on real papers:

- a case-insensitive plasmid pattern read the word `PCR` as the vector `pCR`, which promoted prevalence screening to causal evidence
- "the recombinant strain … demonstrated a 32-fold increase in the MIC" was scored biochemical-only because the manipulation vocabulary only covered "recombinant plasmid"

Both are pinned by fixtures in `examples/evidence_cases.tsv`.

## Coverage

Recall comes before precision in retrieval, because a paper the sweep never returned cannot be recovered later, while a false positive is dropped in one screening pass.

- two sources: Europe PMC (journals and preprints) and PubMed
- queries chunked by drug class and by gene family, so no single query is truncated
- gene tokens always carry a family suffix or number. A bare stem is not searchable: `MCR` matches multicomponent-reaction chemistry, `van` matches Dutch author names, `cat` and `sul` match ordinary words
- PubMed is searched by `EDAT`, so out-of-window papers appear. They are labelled `in_window=before_since`, not deleted; an earlier paper naming the gene is the point of the date gate

## Automatic exclusions

- reviews and meta-analyses
- new plasmid / new strain / new ST / first local report of a **known** gene
- “novel” referring to a method, outbreak, or treatment
- plant, algae, or isolate-name collisions
- the index paper’s own preprint dated before `--since`

## Worked 2026-03-29 screens (not final novel-ARG calls)

Literature-supported excludes:

- **KPC-249**: formal first-online 2026-02-27 → `formal_before_since`
- **MPN_080**: journal 2026-04-05, same-title preprint 2026-02-27 → `preprint_before_since`
- **OXA-1207**: bioRxiv 2025-07-31 names OXA-1207; 2025-12 Qatar genome announcement also names it

Current-title + CreateDate only (HOLD unless history is checked):

- **KPC-160** `OQ579136`: current title has `blaKPC-160`; CreateDate 2023-03-14
- **OXA-1054** `OM322820`: current title has the name; CreateDate 2024-12-31
- **mcr-12** `NG_245195`: current title has mcr-12 / MCR-12.1; CreateDate 2025-07-15
- **mcr-10.6** `NG_246066`: current title has MCR-10.6; CreateDate 2026-03-23

`no_earlier_record_found` rows still need novelty class and gene-level evidence. They are not `review_complete`.
