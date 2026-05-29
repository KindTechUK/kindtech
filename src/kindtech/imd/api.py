"""
KindTech IMD API

Loads UK deprivation data, keyed on ONS geography codes so it joins to
:func:`kindtech.geo.load_geodata` and :func:`kindtech.ons.load_ons`.

Two vintages are available via the ``year`` argument:

``year=2019`` (default) — the **composite UK IMD** by
`mySociety <https://github.com/mysociety/composite_uk_imd>`_, which harmonises
the four nations' 2017–2020 indices onto one UK-wide ranking (the only way to
compare deprivation *across* nations). On 2011 LSOAs / Data Zones / SOAs.

``year=2025`` — the **latest national index**, published on **2021 LSOAs** (a
native join to Census 2021). Currently England's IMD 2025; rankings are
within-nation, not UK-comparable.

    >>> from kindtech import load_imd
    >>> uk = load_imd()                              # composite, all nations
    >>> england = load_imd(nation="England", year=2025)  # latest, 2021 LSOAs
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

# English Indices of Deprivation 2025, File 7 (2021 LSOAs).
ENGLAND_IMD_2025_URL = (
    "https://assets.publishing.service.gov.uk/media/691ded56d140bbbaa59a2a7d/"
    "File_7_IoD2025_All_Ranks_Scores_Deciles_Population_Denominators.csv"
)

# Composite columns -> KindTech names.
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

# IoD2025 File 7 domains: kindtech prefix -> (Score column, domain label).
# The decile column is "<label> Decile (where 1 is most deprived 10% of LSOAs)".
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

_DECILE_SUFFIX = "Decile (where 1 is most deprived 10% of LSOAs)"
_IMD = "Index of Multiple Deprivation (IMD)"


def _england_2025_columns() -> dict[str, str]:
    """IoD2025 File 7 column names -> KindTech names (overall IMD + domains)."""
    columns = {
        "LSOA code (2021)": "geography_code",
        "LSOA name (2021)": "geography_name",
        "Local Authority District code (2024)": "lad_code",
        "Local Authority District name (2024)": "lad_name",
        f"{_IMD} Score": "imd_score",
        f"{_IMD} Rank (where 1 is most deprived)": "imd_rank",
        f"{_IMD} {_DECILE_SUFFIX}": "imd_decile",
    }
    for prefix, (score_col, label) in _ENGLAND_2025_DOMAINS.items():
        columns[score_col] = f"{prefix}_score"
        columns[f"{label} {_DECILE_SUFFIX}"] = f"{prefix}_decile"
    return columns


_ENGLAND_2025_COLUMNS = _england_2025_columns()

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

# Latest year available per nation (None nation = UK-wide -> composite only).
# England has IoD 2025 on 2021 LSOAs; the others' latest sits in the composite.
_LATEST_YEAR = {"E": 2025}

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


def _load_composite(nation_code: str | None, url: str) -> Any:
    """Composite UK IMD path (year=2019)."""
    frame = _renamed(url, _COMPOSITE_COLUMNS)
    if nation_code is not None:
        frame = frame.filter(nw.col("nation") == nation_code)
    return frame.to_native()


def _load_national_2025(nation_code: str | None, url: str) -> Any:
    """Latest national index path (year=2025)."""
    if nation_code is None:
        msg = (
            "year=2025 is published per-nation, not UK-wide. Specify "
            "nation='England' (or 'Wales'). For a UK-comparable index use "
            "year=2019 (the composite)."
        )
        raise ValueError(msg)
    if nation_code == "E":
        frame = _renamed(url or ENGLAND_IMD_2025_URL, _ENGLAND_2025_COLUMNS)
        return frame.with_columns(nation=nw.lit("E")).to_native()
    if nation_code == "W":
        msg = (
            "WIMD 2025 (Wales) is published on StatsWales without a stable "
            "machine-readable download endpoint, so it is not yet wired up. "
            "Use year=2019 (the composite) for Wales for now."
        )
        raise ValueError(msg)
    # Scotland / Northern Ireland have no 2025 release.
    name = _NATION_NAMES[nation_code]
    latest = "SIMD 2020" if nation_code == "S" else "NIMDM 2017"
    msg = (
        f"No 2025 deprivation index exists for {name}; the latest is {latest}. "
        "Use year=2019 (the composite) to access it."
    )
    raise ValueError(msg)


def load_imd(
    nation: str | None = "UK",
    year: int | None = None,
    url: str | None = None,
) -> Any:
    """Load UK deprivation data.

    Args:
        nation: ``"UK"`` (default, composite only), or a nation —
            ``"England"``, ``"Wales"``, ``"Scotland"``,
            ``"Northern Ireland"`` (codes ``E``/``W``/``S``/``N`` also work).
        year: ``2019`` for the composite UK index (the only UK-comparable
            option, and useful for change analysis), or ``2025`` for the latest
            national index on 2021 LSOAs (England; Wales pending). Defaults to
            the **latest available** for the chosen nation — ``2025`` for
            England, ``2019`` otherwise.
        url: Override the source URL (mainly for testing).

    Returns:
        DataFrame (pandas or polars), one row per area, keyed on
        ``geography_code``.

        - ``year=2019``: ``geography_code``, ``nation``, ``imd_rank``,
          ``imd_decile``, ``imd_quintile`` (UK-wide), ``nation_decile``
          (within-nation), and income/employment/local scores.
        - ``year=2025``: ``geography_code`` (2021 LSOA), ``geography_name``,
          ``nation``, ``lad_code``, ``lad_name``, ``imd_score``/``imd_rank``/
          ``imd_decile``, and score+decile for the seven domains (income,
          employment, education, health, crime, housing, living_environment).
          Deciles are within-nation.

    Raises:
        ValueError: If ``nation`` is unrecognised, or ``year``/``nation`` name a
            combination with no published index.
        ImportError: If neither pandas nor polars is installed.
    """
    nation_code = _resolve_nation(nation)
    if year is None:
        year = _LATEST_YEAR.get(nation_code, 2019)
    if year == 2019:
        return _load_composite(nation_code, url or COMPOSITE_IMD_URL)
    if year == 2025:
        return _load_national_2025(nation_code, url)
    msg = "year must be 2019 (composite UK) or 2025 (latest national)."
    raise ValueError(msg)
