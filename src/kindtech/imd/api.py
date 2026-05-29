"""
KindTech IMD API

Loads the **composite UK Index of Multiple Deprivation** — a single ranking that
harmonises the four official indices (England IMD 2019, Wales WIMD 2019, Scotland
SIMD 2020, Northern Ireland NIMDM 2017) onto one UK-wide scale, built by
`mySociety <https://github.com/mysociety/composite_uk_imd>`_.

Each official index ranks areas only *within* its own nation, so their deciles
aren't comparable across the UK. The composite re-ranks every area (English and
Welsh LSOAs, Scottish Data Zones, NI Super Output Areas) on a common scale, which
is what makes ``imd_rank`` and ``imd_decile`` meaningful UK-wide.

The returned ``geography_code`` aligns with :func:`kindtech.geo.load_geodata`
and :func:`kindtech.ons.load_ons`, so deprivation joins straight to boundaries
and statistics:

    >>> from kindtech import load_imd
    >>> imd = load_imd(nation="England")          # English LSOAs (2011)
    >>> imd[["geography_code", "imd_decile"]].head()
"""

import logging
from typing import Any

import narwhals.stable.v2 as nw
import requests

from kindtech._frames import csv_to_frame

# England-anchored composite (covers all four nations on one UK scale).
COMPOSITE_IMD_URL = (
    "https://raw.githubusercontent.com/mysociety/composite_uk_imd/"
    "main/data/uk_index/UK_IMD_E.csv"
)

# Map the composite's raw column names to KindTech's names.
_COLUMN_MAP = {
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

# Accept friendly nation names and single-letter codes; map to the file's codes.
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

logger = logging.getLogger(__name__)

# In-process cache of the parsed composite, keyed by source URL — the dataset
# is a static research release, so one fetch per session is enough.
_CACHE: dict[str, Any] = {}


def _resolve_nation(nation: str | None) -> str | None:
    """Validate a nation argument and return the file's single-letter code."""
    if nation is None or nation.upper() in {"UK", "ALL"}:
        return None
    key = nation.strip().upper()
    if key not in _NATION_CODES:
        valid = "UK, England, Wales, Scotland, Northern Ireland"
        msg = f"Unknown nation {nation!r}. Use one of: {valid}."
        raise ValueError(msg)
    return _NATION_CODES[key]


def _fetch_composite(url: str) -> nw.DataFrame:
    """Fetch and parse the composite CSV (cached), renamed to KindTech columns."""
    if url not in _CACHE:
        logger.info("Fetching composite UK IMD: %s", url)
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        frame = nw.from_native(csv_to_frame(response.text), eager_only=True)
        frame = frame.rename(_COLUMN_MAP).select(list(_COLUMN_MAP.values()))
        _CACHE[url] = frame
    return _CACHE[url]


def load_imd(
    nation: str | None = "UK",
    url: str = COMPOSITE_IMD_URL,
) -> Any:
    """Load the composite UK Index of Multiple Deprivation.

    Args:
        nation: ``"UK"`` (default, all four nations), or one nation —
            ``"England"``, ``"Wales"``, ``"Scotland"``,
            ``"Northern Ireland"`` (single-letter codes ``E``/``W``/``S``/``N``
            also accepted).
        url: Source URL for the composite dataset.

    Returns:
        DataFrame (pandas or polars) with one row per area. Columns:

        - ``geography_code`` — LSOA (England/Wales, 2011), Data Zone
          (Scotland), or SOA (Northern Ireland); joins to
          :func:`~kindtech.geo.geodata_to_properties` and
          :func:`~kindtech.ons.load_ons`.
        - ``nation`` — ``E``/``W``/``S``/``N``.
        - ``imd_rank`` — UK-wide rank (1 = most deprived).
        - ``imd_decile`` / ``imd_quintile`` — UK-wide, population-weighted
          (1 = most deprived 10% / 20% of the UK).
        - ``nation_decile`` — the original within-nation decile (not
          comparable across nations).
        - ``imd_score``, ``income_score``, ``employment_score``,
          ``local_score``.

    Raises:
        ValueError: If ``nation`` is unrecognised.
        ImportError: If neither pandas nor polars is installed.
    """
    code = _resolve_nation(nation)
    frame = _fetch_composite(url)
    if code is not None:
        frame = frame.filter(nw.col("nation") == code)
    return frame.to_native()
