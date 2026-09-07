#!/usr/bin/env python3
"""Query vocabulary and query builders for the date-bounded ARG sweep.

Recall matters more than precision here. Screening happens later, so a broad
sweep is cheap and a missed paper is not recoverable.

Long OR lists are split into chunks. Each chunk is its own query, so a single
crowded query cannot hit the pagination ceiling and silently drop records.
"""

from __future__ import annotations

PROFILES = ("core", "broad", "max")
DEFAULT_PROFILE = "broad"

# Drug names, drug classes, and resistance phenotypes.
DRUG_TERMS = [
    "antibiotic resistance",
    "antimicrobial resistance",
    "antibacterial resistance",
    "multidrug resistance",
    "beta-lactamase",
    "β-lactamase",
    "carbapenemase",
    "carbapenem resistance",
    "cephalosporin resistance",
    "extended-spectrum beta-lactamase",
    "metallo-beta-lactamase",
    "penicillin resistance",
    "ceftazidime-avibactam",
    "cefiderocol resistance",
    "monobactam resistance",
    "colistin resistance",
    "polymyxin resistance",
    "aminoglycoside resistance",
    "gentamicin resistance",
    "streptomycin resistance",
    "spectinomycin resistance",
    "apramycin resistance",
    "plazomicin resistance",
    "macrolide resistance",
    "azithromycin resistance",
    "erythromycin resistance",
    "lincosamide resistance",
    "streptogramin resistance",
    "pleuromutilin resistance",
    "tetracycline resistance",
    "tigecycline resistance",
    "eravacycline resistance",
    "fosfomycin resistance",
    "chloramphenicol resistance",
    "phenicol resistance",
    "florfenicol resistance",
    "linezolid resistance",
    "oxazolidinone resistance",
    "vancomycin resistance",
    "glycopeptide resistance",
    "teicoplanin resistance",
    "daptomycin resistance",
    "lipopeptide resistance",
    "bacitracin resistance",
    "quinolone resistance",
    "fluoroquinolone resistance",
    "ciprofloxacin resistance",
    "rifampicin resistance",
    "rifampin resistance",
    "sulfonamide resistance",
    "sulfamethoxazole resistance",
    "trimethoprim resistance",
    "nitrofurantoin resistance",
    "mupirocin resistance",
    "fusidic acid resistance",
    "novobiocin resistance",
    "aminocoumarin resistance",
    "fidaxomicin resistance",
    "bleomycin resistance",
    "quaternary ammonium resistance",
    "efflux pump",
    "ribosomal protection protein",
    "target protection",
    "drug inactivation",
    "enzymatic inactivation",
]

# Gene and enzyme family tokens. These are the names papers actually coin.
#
# Bare stems such as "bla", "van", "sul", "cat", or "mcr" pull in unrelated
# papers ("Ugi MCR" chemistry, author names like "van Dijk"), so every token
# here carries a family suffix or number.
GENE_TOKENS = [
    "blaKPC",
    "blaNDM",
    "blaOXA",
    "blaIMP",
    "blaVIM",
    "blaSHV",
    "blaTEM",
    "blaCTX-M",
    "blaCMY",
    "blaGES",
    "blaSPM",
    "blaADC",
    "blaPER",
    "blaVEB",
    "blaFRI",
    "blaSME",
    "blaNMC",
    "blaHMB",
    "blaAIM",
    "blaDIM",
    "blaTMB",
    "blaSIM",
    "mcr-1",
    "mcr-9",
    "mcr-10",
    "mcr gene",
    "eptA",
    "arnT",
    "fosA",
    "fosB",
    "fosC",
    "fosL",
    "fosX",
    "tet(A)",
    "tet(X)",
    "tet(M)",
    "tet(L)",
    "tmexCD",
    "tnfxB",
    "erm(B)",
    "erm(T)",
    "mef(A)",
    "msr(E)",
    "mph(A)",
    "ere(A)",
    "lsa(A)",
    "lsa(E)",
    "vga(A)",
    "vgb(B)",
    "sal(A)",
    "cfr(B)",
    "optrA",
    "poxtA",
    "ant(",
    "aph(",
    "aac(",
    "aadA",
    "rmtB",
    "rmtF",
    "npmA",
    "armA",
    "apmA",
    "vanA",
    "vanB",
    "vanM",
    "vanN",
    "sul1",
    "sul4",
    "dfrA",
    "qnrA",
    "qnrS",
    "qepA",
    "oqxAB",
    "arr-3",
    "catA1",
    "catB",
    "floR",
    "fexA",
    "fexB",
    "estT",
    "qacA",
    "sat4",
    "Ngt-1",
]

NOVELTY_TERMS = [
    "novel",
    "new",
    "newly identified",
    "newly described",
    "newly characterized",
    "previously uncharacterized",
    "previously undescribed",
    "previously unreported",
    "unrecognized",
    "first characterization",
    "first identification",
    "discovery",
    "designated",
    "designated as",
    "we designated",
    "herein named",
    "named",
    "variant",
    "allele",
    "family member",
]

OBJECT_TERMS = [
    "gene",
    "enzyme",
    "variant",
    "allele",
    "determinant",
    "transferase",
    "lactamase",
    "carbapenemase",
    "methyltransferase",
    "acetyltransferase",
    "adenylyltransferase",
    "nucleotidyltransferase",
    "phosphotransferase",
    "glycosyltransferase",
    "hydrolase",
    "esterase",
    "efflux pump",
    "transporter",
    "ABC transporter",
    "ABC-F protein",
    "resistance protein",
]

FUNCTION_TERMS = [
    "confers resistance",
    "conferring resistance",
    "conferred resistance",
    "functional characterization",
    "heterologous expression",
    "cloned into",
    "complementation",
    "gene knockout",
    "deletion mutant",
    "minimum inhibitory concentration",
    "enzyme kinetics",
    "hydrolytic activity",
    "substrate profile",
]

DISCOVERY_TERMS = [
    "resistome",
    "functional metagenomics",
    "functional metagenomic selection",
    "functional selection",
    "metagenomic library",
    "soil resistome",
    "environmental resistome",
    "gut resistome",
    "hidden resistome",
    "uncultured bacteria",
]


def _field_or(terms: list[str], field: str = "TITLE_ABS") -> str:
    return " OR ".join(f'{field}:"{term}"' for term in terms)


def _chunks(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _profile_sizes(profile: str) -> dict[str, int]:
    if profile == "core":
        return {"drug": 24, "gene": 32}
    if profile == "max":
        return {"drug": 6, "gene": 10}
    return {"drug": 10, "gene": 16}


def epmc_queries(profile: str = DEFAULT_PROFILE) -> list[tuple[str, str]]:
    """Named Europe PMC queries. `{date}` is filled in by the caller."""
    if profile not in PROFILES:
        raise ValueError(f"unknown profile {profile!r}; use one of {', '.join(PROFILES)}")
    sizes = _profile_sizes(profile)
    novelty = _field_or(NOVELTY_TERMS)
    objects = _field_or(OBJECT_TERMS)
    function = _field_or(FUNCTION_TERMS)
    out: list[tuple[str, str]] = []

    out.append(
        (
            "q_novel_resistance",
            f'({{date}}) AND ({novelty}) AND TITLE_ABS:"resistance" AND ({objects})',
        )
    )

    if profile == "core":
        drug_terms = DRUG_TERMS[:24]
        gene_terms = GENE_TOKENS[:32]
    else:
        drug_terms = DRUG_TERMS
        gene_terms = GENE_TOKENS

    for i, chunk in enumerate(_chunks(drug_terms, sizes["drug"]), start=1):
        out.append(
            (
                f"q_novel_drugclass_{i:02d}",
                f'({{date}}) AND ({novelty}) AND ({_field_or(chunk)}) AND ({objects})',
            )
        )

    for i, chunk in enumerate(_chunks(gene_terms, sizes["gene"]), start=1):
        gene_or = _field_or(chunk)
        if profile == "max":
            query = f'({{date}}) AND ({gene_or}) AND ({objects})'
        else:
            query = f'({{date}}) AND ({novelty}) AND ({gene_or})'
        out.append((f"q_gene_token_{i:02d}", query))

    out.append(
        (
            "q_function_language",
            f'({{date}}) AND ({function}) AND ({objects})',
        )
    )
    out.append(
        (
            "q_designated_name",
            '({date}) AND (TITLE_ABS:"designated" OR TITLE_ABS:"we designated" OR '
            'TITLE_ABS:"designated as" OR TITLE_ABS:"herein named" OR TITLE_ABS:"we named") '
            'AND TITLE_ABS:"resistance"',
        )
    )
    out.append(
        (
            "q_new_family",
            '({date}) AND (TITLE_ABS:"new family" OR TITLE_ABS:"novel family" OR '
            'TITLE_ABS:"new subclass" OR TITLE_ABS:"novel subclass" OR TITLE_ABS:"new class") '
            'AND (TITLE_ABS:"lactamase" OR TITLE_ABS:"carbapenemase" OR TITLE_ABS:"transferase" OR '
            'TITLE_ABS:"resistance gene" OR TITLE_ABS:"resistance enzyme")',
        )
    )
    out.append(
        (
            "q_preprint_sweep",
            f'({{date}}) AND (SRC:"PPR") AND TITLE_ABS:"resistance" AND ({objects})',
        )
    )

    if profile in {"broad", "max"}:
        out.append(
            (
                "q_resistome_discovery",
                f'({{date}}) AND ({_field_or(DISCOVERY_TERMS)}) AND '
                f'(TITLE_ABS:"resistance gene" OR TITLE_ABS:"resistance determinant" OR '
                f'TITLE_ABS:"novel" OR TITLE_ABS:"new")',
            )
        )

    if profile == "max":
        out.append(
            (
                "q_any_resistance_gene",
                '({date}) AND (TITLE:"resistance gene" OR TITLE:"resistance determinant" OR '
                'TITLE:"lactamase" OR TITLE:"carbapenemase" OR TITLE:"resistance enzyme")',
            )
        )

    return out


def pubmed_queries(profile: str = DEFAULT_PROFILE) -> list[tuple[str, str]]:
    """Named PubMed queries. `{date}` is filled in by the caller."""
    if profile not in PROFILES:
        raise ValueError(f"unknown profile {profile!r}; use one of {', '.join(PROFILES)}")
    sizes = _profile_sizes(profile)
    novelty = " OR ".join(f'"{t}"[tiab]' for t in NOVELTY_TERMS)
    objects = " OR ".join(f'"{t}"[tiab]' for t in OBJECT_TERMS)
    out: list[tuple[str, str]] = []
    out.append(
        (
            "p_novel_resistance",
            f'({{date}}) AND ({novelty}) AND "resistance"[tiab] AND ({objects})',
        )
    )
    drug_terms = DRUG_TERMS[:24] if profile == "core" else DRUG_TERMS
    gene_terms = GENE_TOKENS[:32] if profile == "core" else GENE_TOKENS
    for i, chunk in enumerate(_chunks(drug_terms, sizes["drug"]), start=1):
        chunk_or = " OR ".join(f'"{t}"[tiab]' for t in chunk)
        out.append(
            (
                f"p_novel_drugclass_{i:02d}",
                f'({{date}}) AND ({novelty}) AND ({chunk_or}) AND ({objects})',
            )
        )
    for i, chunk in enumerate(_chunks(gene_terms, sizes["gene"]), start=1):
        chunk_or = " OR ".join(f'"{t}"[tiab]' for t in chunk)
        out.append(
            (
                f"p_gene_token_{i:02d}",
                f'({{date}}) AND ({novelty}) AND ({chunk_or})',
            )
        )
    return out


def alias_variants(alias: str) -> list[str]:
    """Spelling variants of one gene name, most specific first.

    `blaKPC-249` also appears as `bla_KPC-249`, `bla-KPC-249`, and `KPC-249`.
    `ant(9)-If` also appears as `ant9-If`.
    """
    seen: list[str] = []

    def add(value: str) -> None:
        value = value.strip()
        if value and value not in seen:
            seen.append(value)

    add(alias)
    stripped = alias.replace("(", "").replace(")", "")
    add(stripped)
    add(alias.replace("(", "-").replace(")", ""))
    lowered = alias.lower()
    if lowered.startswith("bla"):
        rest = alias[3:].lstrip("_-")
        add(rest)
        add(f"bla_{rest}")
        add(f"bla-{rest}")
    else:
        add(f"bla{alias}")
        add(f"bla_{alias}")
    if "_" in alias:
        add(alias.replace("_", "-"))
    if "-" in alias:
        add(alias.replace("-", "_"))
    return seen


def expand_aliases(aliases: list[str], limit: int = 12) -> list[str]:
    out: list[str] = []
    for alias in aliases:
        for variant in alias_variants(alias):
            if variant not in out:
                out.append(variant)
    return out[:limit]
