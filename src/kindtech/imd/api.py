"""
KindTech IMD API

Loads UK deprivation data, keyed on ONS geography codes so it joins to
:func:`kindtech.geo.load_geodata` and :func:`kindtech.ons.load_ons`.

A single nation returns its **official** index; ``"UK"`` returns a composite
for cross-nation comparison:

- ``nation="England"`` — the official **English Indices of Deprivation**
  (gov.uk File 7). ``year=2025`` (default, 2021 LSOAs) or ``year=2019`` (2011
  LSOAs); both carry all seven domains, ranks, deciles and a population
  denominator. Within-England rankings.
- ``nation="Wales"``/``"Scotland"``/``"Northern Ireland"`` — the official
  within-nation index (WIMD / SIMD / NIMDM), via the composite source.
- ``nation="UK"`` (default) — the **composite UK IMD** by
  `mySociety <https://github.com/mysociety/composite_uk_imd>`_, which re-ranks
  all four nations' indices onto one UK-wide scale. This is the *only* way to
  compare deprivation across nations; its rank/decile are UK-wide, not a
  nation's official figures.

    >>> from kindtech import load_imd
    >>> uk = load_imd()                              # composite, cross-nation
    >>> england = load_imd(nation="England")         # official IoD 2025
    >>> england_19 = load_imd(nation="England", year=2019)  # official IoD 2019
"""

import logging
from typing import Any

import narwhals.stable.v2 as nw
import requests

from kindtech._frames import csv_to_frame

# England-anchored composite (all four nations on one UK scale), 2017-2020.
COMPOSITE_IMD_URL = (
    "https://raw.githubusercontent.com/mysociety/composite_uk_imd/"
    "main/data/uk_index/UK_IMD_E.csv"
)

# English Indices of Deprivation, File 7 (all ranks/scores/deciles + population).
ENGLAND_IMD_2025_URL = (
    "https://assets.publishing.service.gov.uk/media/691ded56d140bbbaa59a2a7d/"
    "File_7_IoD2025_All_Ranks_Scores_Deciles_Population_Denominators.csv"
)
ENGLAND_IMD_2019_URL = (
    "https://assets.publishing.service.gov.uk/government/uploads/system/uploads/"
    "attachment_data/file/845345/"
    "File_7_-_All_IoD2019_Scores__Ranks__Deciles_and_Population_Denominators_3.csv"
)

# Composite columns -> KindTech names. Used ONLY for UK-wide, cross-nation
# comparison: every area is re-ranked onto a single UK scale, so ``imd_rank`` /
# ``imd_decile`` here are UK-wide, not a nation's official figures.
_COMPOSITE_COLUMNS = {
    "lsoa": "geography_code",
    "nation": "nation",
    "UK_IMD_E_score": "imd_score",
    "UK_IMD_E_rank": "imd_rank",
    "UK_IMD_E_pop_decile": "imd_decile",
    "UK_IMD_E_pop_quintile": "imd_quintile",
    "original_decile": "nation_decile",
    "income_score": "income_score",
    "employment_score": "employment_score",
    "overall_local_score": "local_score",
}

# Single non-England nations: surface the OFFICIAL within-nation index that the
# composite carries (``original_decile`` is the nation's own published decile,
# ``overall_local_score`` its own score) — not the UK-wide re-ranking.
_NATIONAL_FROM_COMPOSITE_COLUMNS = {
    "lsoa": "geography_code",
    "nation": "nation",
    "overall_local_score": "imd_score",
    "original_decile": "imd_decile",
    "income_score": "income_score",
    "employment_score": "employment_score",
}

# IoD2025 File 7 domains: kindtech prefix -> (Score column, domain label).
# Each domain also has "<label> Rank (where 1 is most deprived)" and
# "<label> Decile (where 1 is most deprived 10% of LSOAs)" columns.
_ENGLAND_2025_DOMAINS = {
    "income": ("Income Score (rate)", "Income"),
    "employment": ("Employment Score (rate)", "Employment"),
    "education": (
        "Education, Skills and Training Score",
        "Education, Skills and Training",
    ),
    "health": (
        "Health Deprivation and Disability Score",
        "Health Deprivation and Disability",
    ),
    "crime": ("Crime Score", "Crime"),
    "housing": (
        "Barriers to Housing and Services Score",
        "Barriers to Housing and Services",
    ),
    "living_environment": ("Living Environment Score", "Living Environment"),
}

_RANK_SUFFIX = "Rank (where 1 is most deprived)"
_DECILE_SUFFIX = "Decile (where 1 is most deprived 10% of LSOAs)"
_IMD = "Index of Multiple Deprivation (IMD)"


def _england_columns(
    lsoa_year: int, lad_year: int, population_col: str
) -> dict[str, str]:
    """England IoD File 7 column names -> KindTech names (overall IMD + domains).

    The 2019 and 2025 files share the same domain columns; only the LSOA
    vintage, the LAD year and the population-denominator column name differ.
    """
    columns = {
        f"LSOA code ({lsoa_year})": "geography_code",
        f"LSOA name ({lsoa_year})": "geography_name",
        f"Local Authority District code ({lad_year})": "lad_code",
        f"Local Authority District name ({lad_year})": "lad_name",
        f"{_IMD} Score": "imd_score",
        f"{_IMD} {_RANK_SUFFIX}": "imd_rank",
        f"{_IMD} {_DECILE_SUFFIX}": "imd_decile",
    }
    for prefix, (score_col, label) in _ENGLAND_2025_DOMAINS.items():
        columns[score_col] = f"{prefix}_score"
        columns[f"{label} {_RANK_SUFFIX}"] = f"{prefix}_rank"
        columns[f"{label} {_DECILE_SUFFIX}"] = f"{prefix}_decile"
    # Population denominator (same LSOA vintage) — handy for per-capita work.
    columns[population_col] = "population"
    return columns


# 2025: 2021 LSOAs, 2024 LADs, mid-2022 population.
_ENGLAND_2025_COLUMNS = _england_columns(2021, 2024, "Total population: mid 2022")
# 2019: 2011 LSOAs, 2019 LADs, mid-2015 population.
_ENGLAND_2019_COLUMNS = _england_columns(
    2011, 2019, "Total population: mid 2015 (excluding prisoners)"
)

# Friendly nation names / codes -> the composite's single-letter codes.
_NATION_CODES = {
    "E": "E",
    "ENGLAND": "E",
    "W": "W",
    "WALES": "W",
    "S": "S",
    "SCOTLAND": "S",
    "N": "N",
    "NI": "N",
    "NORTHERN IRELAND": "N",
}
_NATION_NAMES = {"E": "England", "W": "Wales", "S": "Scotland", "N": "Northern Ireland"}

logger = logging.getLogger(__name__)

# In-process cache of fetched CSVs, keyed by URL — these are static releases,
# so one fetch per source per session is enough.
_CACHE: dict[str, nw.DataFrame] = {}


def _resolve_nation(nation: str | None) -> str | None:
    """Validate a nation argument; return its code, or None for UK-wide."""
    if nation is None or nation.upper() in {"UK", "ALL"}:
        return None
    key = nation.strip().upper()
    if key not in _NATION_CODES:
        valid = "UK, England, Wales, Scotland, Northern Ireland"
        msg = f"Unknown nation {nation!r}. Use one of: {valid}."
        raise ValueError(msg)
    return _NATION_CODES[key]


def _fetch_raw(url: str) -> nw.DataFrame:
    """Fetch and parse a CSV into a narwhals DataFrame (cached by URL)."""
    if url not in _CACHE:
        logger.info("Fetching IMD data: %s", url)
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        _CACHE[url] = nw.from_native(csv_to_frame(response.text), eager_only=True)
    return _CACHE[url]


def _renamed(url: str, columns: dict[str, str]) -> nw.DataFrame:
    """Fetch a source and rename/select to KindTech columns."""
    frame = _fetch_raw(url)
    return frame.rename(columns).select(list(columns.values()))


def _load_composite_uk(url: str) -> Any:
    """UK-wide composite: every area on one cross-nation ranking."""
    return _renamed(url, _COMPOSITE_COLUMNS).to_native()


def _load_england(default_url: str, columns: dict[str, str], url: str | None) -> Any:
    """Official England IoD (File 7), 2019 or 2025 depending on ``columns``."""
    frame = _renamed(url or default_url, columns)
    return frame.with_columns(nation=nw.lit("E")).to_native()


def _load_national(nation_code: str, url: str) -> Any:
    """Official within-nation index for Wales/Scotland/NI (from the composite).

    ``imd_decile`` is the nation's own published decile (not the UK re-ranking).
    """
    frame = _renamed(url, _NATIONAL_FROM_COMPOSITE_COLUMNS)
    return frame.filter(nw.col("nation") == nation_code).to_native()


def _raise_no_2025(nation_code: str) -> None:
    """Explain why a nation has no 2025 index."""
    if nation_code == "W":
        msg = (
            "WIMD 2025 (Wales) is published on StatsWales without a stable "
            "machine-readable download endpoint, so it is not yet wired up. "
            "Use year=2019 for Wales for now."
        )
        raise ValueError(msg)
    name = _NATION_NAMES[nation_code]
    latest = "SIMD 2020" if nation_code == "S" else "NIMDM 2017"
    msg = (
        f"No 2025 deprivation index exists for {name}; the latest is {latest}. "
        "Use year=2019 to access it."
    )
    raise ValueError(msg)


def load_imd(
    nation: str | None = "UK",
    year: int | None = None,
    url: str | None = None,
) -> Any:
    """Load UK deprivation data.

    Single nations return their **official** index; ``"UK"`` returns the
    mySociety composite, which re-ranks all four nations onto one scale and is
    the only way to compare deprivation *across* nations.

    Args:
        nation: ``"UK"`` (default — composite, cross-nation), or a nation:
            ``"England"``, ``"Wales"``, ``"Scotland"``,
            ``"Northern Ireland"`` (codes ``E``/``W``/``S``/``N`` also work).
        year: For ``"England"``, ``2025`` (default — official IoD 2025, 2021
            LSOAs) or ``2019`` (official IoD 2019, 2011 LSOAs). For
            ``"UK"``/Wales/Scotland/NI only ``2019`` is available (the composite
            era); it defaults there. Wales 2025 is pending; Scotland/NI have no
            2025 release.
        url: Override the source URL (mainly for testing).

    Returns:
        DataFrame (pandas or polars), one row per area, keyed on
        ``geography_code``.

        - ``nation="UK"``: ``geography_code``, ``nation``, ``imd_rank``,
          ``imd_decile``, ``imd_quintile`` (all **UK-wide**), ``nation_decile``
          (the official within-nation decile), and income/employment/local
          scores.
        - ``nation="England"``: ``geography_code`` (2021 LSOA for 2025, 2011 for
          2019), ``geography_name``, ``nation``, ``lad_code``, ``lad_name``,
          ``imd_score``/``imd_rank``/``imd_decile``, plus score+rank+decile for
          the seven domains (income, employment, education, health, crime,
          housing, living_environment) and a ``population`` denominator.
          Official within-England figures (rank 1 = most deprived).
        - ``nation="Wales"``/``"Scotland"``/``"Northern Ireland"``:
          ``geography_code`` (LSOA / Data Zone / SOA), ``nation``, the official
          within-nation ``imd_score``/``imd_decile``, and income/employment
          scores.

    Raises:
        ValueError: If ``nation`` is unrecognised, or ``year``/``nation`` name a
            combination with no published index.
        ImportError: If neither pandas nor polars is installed.
    """
    nation_code = _resolve_nation(nation)

    # UK-wide: the composite is the only cross-nation index.
    if nation_code is None:
        if year not in (None, 2019):
            msg = (
                "UK-wide deprivation is only available as the composite "
                "(year=2019). For the latest official index choose a nation, "
                "e.g. load_imd(nation='England')."
            )
            raise ValueError(msg)
        return _load_composite_uk(url or COMPOSITE_IMD_URL)

    # England: official IoD, 2019 (2011 LSOAs) or 2025 (2021 LSOAs).
    if nation_code == "E":
        year = 2025 if year is None else year
        if year == 2025:
            return _load_england(ENGLAND_IMD_2025_URL, _ENGLAND_2025_COLUMNS, url)
        if year == 2019:
            return _load_england(ENGLAND_IMD_2019_URL, _ENGLAND_2019_COLUMNS, url)
        msg = "England IoD is available for year=2019 or year=2025."
        raise ValueError(msg)

    # Wales / Scotland / NI: official within-nation index (2019 era).
    year = 2019 if year is None else year
    if year == 2025:
        _raise_no_2025(nation_code)
    if year != 2019:
        name = _NATION_NAMES[nation_code]
        msg = f"{name}'s official index is only available for year=2019."
        raise ValueError(msg)
    return _load_national(nation_code, url or COMPOSITE_IMD_URL)
