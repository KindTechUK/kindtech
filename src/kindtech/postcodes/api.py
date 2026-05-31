"""
KindTech Postcodes API

Wraps `postcodes.io <https://postcodes.io/>`_ to turn UK postcodes (and
postcode outcodes) into the ONS geography codes the rest of KindTech joins on.

postcodes.io is built on the ONS Postcode Directory, Ordnance Survey Open Names
and the Scottish Postcode Directory (all Open Government Licence). No API key is
needed.

The returned ``geography_code`` column aligns with
:func:`kindtech.geo.api.geodata_to_properties` and :func:`kindtech.ons.load_ons`,
so any list of postcodes joins directly to boundaries and statistics:

    >>> from kindtech import postcodes_to_geography, load_geodata, load_ons
    >>> import pandas as pd
    >>>
    >>> located = postcodes_to_geography(["SE13 7HX", "SE6 4RU"], "LSOA")
    >>> per_lsoa = located.groupby("geography_code").size()  # rows per LSOA
"""

import logging
from collections.abc import Iterable, Iterator
from typing import Any

import requests

from kindtech._frames import dicts_to_frame
from kindtech._mapping import extract_code

POSTCODES_BASE_URL = "https://api.postcodes.io"

# postcodes.io caps bulk lookups at 100 postcodes per request.
BULK_BATCH_SIZE = 100

logger = logging.getLogger(__name__)

# Which key in the postcodes.io ``codes`` dict holds the code for each
# KindTech geography type, paired with the row column its name lands in.
# Where a level has both vintages, the 2021 geography is chosen so codes
# align with the rest of KindTech (boundaries and statistics).
_LEVEL_FIELDS: dict[str, tuple[str, str | None]] = {
    "LSOA": ("lsoa_code", "lsoa_name"),
    "MSOA": ("msoa_code", "msoa_name"),
    "OA": ("oa_code", None),
    "LAD": ("lad_code", "lad_name"),
    "WD": ("ward_code", None),
    "ICB": ("icb_code", None),
    "TTWA": ("ttwa_code", None),
}

_NULL_ROW: dict[str, Any] = {
    "lsoa_code": None,
    "lsoa_name": None,
    "msoa_code": None,
    "msoa_name": None,
    "oa_code": None,
    "lad_code": None,
    "lad_name": None,
    "ward_code": None,
    "icb_code": None,
    "ttwa_code": None,
    "latitude": None,
    "longitude": None,
}


def _chunks(items: list[str], size: int) -> Iterator[list[str]]:
    """Yield successive ``size``-length chunks of ``items``."""
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _as_list(value: str | Iterable[str]) -> list[str]:
    """Normalise a single string or an iterable of strings to a list."""
    if isinstance(value, str):
        return [value]
    return list(value)


def _row_from_result(query: str, result: dict | None) -> dict[str, Any]:
    """Shape a postcodes.io lookup result into a flat row.

    ``result`` is ``None`` for an unrecognised postcode/location.
    """
    if not result:
        return {"postcode": query, "valid": False, **_NULL_ROW}
    codes = result.get("codes", {})
    return {
        "postcode": result.get("postcode", query),
        "valid": True,
        "lsoa_code": codes.get("lsoa21") or codes.get("lsoa"),
        "lsoa_name": result.get("lsoa"),
        "msoa_code": codes.get("msoa21") or codes.get("msoa"),
        "msoa_name": result.get("msoa"),
        "oa_code": codes.get("oa21"),
        "lad_code": codes.get("admin_district"),
        "lad_name": result.get("admin_district"),
        "ward_code": codes.get("admin_ward"),
        "icb_code": codes.get("icb"),
        "ttwa_code": codes.get("ttwa"),
        "latitude": result.get("latitude"),
        "longitude": result.get("longitude"),
    }


def _lookup_rows(postcodes: list[str], base_url: str) -> list[dict[str, Any]]:
    """Bulk-look up postcodes, preserving input order, one row each."""
    rows: list[dict[str, Any]] = []
    for batch in _chunks(postcodes, BULK_BATCH_SIZE):
        response = _post(f"{base_url}/postcodes", {"postcodes": batch})
        for entry in response["result"]:
            rows.append(_row_from_result(entry["query"], entry.get("result")))
    return rows


def _resolve_level(geography_type: Any) -> tuple[str, str | None]:
    """Validate a geography type and return its (code_col, name_col)."""
    geo = extract_code(geography_type)
    if geo not in _LEVEL_FIELDS:
        supported = ", ".join(sorted(_LEVEL_FIELDS))
        msg = (
            f"Unsupported geography_type {geo!r}. "
            f"Postcode lookup supports: {supported}."
        )
        raise ValueError(msg)
    return _LEVEL_FIELDS[geo]


def lookup_postcodes(
    postcodes: str | Iterable[str],
    base_url: str = POSTCODES_BASE_URL,
) -> Any:
    """Look up one or many UK postcodes.

    Args:
        postcodes: A single postcode or an iterable of postcodes. Whitespace
            and case are handled by postcodes.io.
        base_url: postcodes.io base URL.

    Returns:
        DataFrame (pandas or polars) with one row per input postcode, in input
        order. Columns: ``postcode``, ``valid`` (False for unrecognised
        postcodes), ``lsoa_code``/``lsoa_name``, ``msoa_code``/``msoa_name``,
        ``oa_code``, ``lad_code``/``lad_name``, ``ward_code``, ``icb_code``,
        ``ttwa_code``, ``latitude``, ``longitude``.

    Raises:
        ImportError: If neither pandas nor polars is installed.
    """
    rows = _lookup_rows(_as_list(postcodes), base_url)
    return dicts_to_frame(rows)


def postcodes_to_geography(
    postcodes: str | Iterable[str],
    geography_type: Any = "LSOA",
    base_url: str = POSTCODES_BASE_URL,
) -> Any:
    """Map postcodes to a single geography level, ready to join.

    Args:
        postcodes: A single postcode or an iterable of postcodes.
        geography_type: One of ``LSOA``, ``MSOA``, ``OA``, ``LAD``, ``WD``,
            ``ICB``, ``TTWA`` (string or :class:`~kindtech.geo.GeographyType`).
        base_url: postcodes.io base URL.

    Returns:
        DataFrame with columns ``postcode``, ``geography_code``,
        ``geography_name``. ``geography_code`` aligns with
        :func:`~kindtech.geo.geodata_to_properties` and
        :func:`~kindtech.ons.load_ons`, so the result joins straight to
        boundaries and statistics. ``geography_code`` is ``None`` for
        unrecognised postcodes.

    Raises:
        ValueError: If ``geography_type`` is not supported.
        ImportError: If neither pandas nor polars is installed.
    """
    code_col, name_col = _resolve_level(geography_type)
    rows = _lookup_rows(_as_list(postcodes), base_url)
    tidy = [
        {
            "postcode": row["postcode"],
            "geography_code": row[code_col],
            "geography_name": row[name_col] if name_col else None,
        }
        for row in rows
    ]
    return dicts_to_frame(tidy)


def lookup_outcodes(
    outcodes: str | Iterable[str],
    base_url: str = POSTCODES_BASE_URL,
) -> Any:
    """Look up postcode outcodes (the prefix before the space, e.g. ``SE13``).

    An outcode spans many areas, so postcodes.io returns the *list* of Local
    Authorities it touches plus the outcode's geometric centroid.

    Args:
        outcodes: A single outcode or an iterable of outcodes.
        base_url: postcodes.io base URL.

    Returns:
        DataFrame with one row per outcode. Columns: ``outcode``, ``valid``,
        ``admin_districts`` (comma-separated LAD names the outcode spans),
        ``latitude``, ``longitude`` (centroid).

    Raises:
        ImportError: If neither pandas nor polars is installed.
    """
    rows: list[dict[str, Any]] = []
    for outcode in _as_list(outcodes):
        result = _get(f"{base_url}/outcodes/{outcode}")
        if not result:
            rows.append(
                {
                    "outcode": outcode,
                    "valid": False,
                    "admin_districts": None,
                    "latitude": None,
                    "longitude": None,
                }
            )
            continue
        rows.append(
            {
                "outcode": result.get("outcode", outcode),
                "valid": True,
                "admin_districts": ", ".join(result.get("admin_district", [])),
                "latitude": result.get("latitude"),
                "longitude": result.get("longitude"),
            }
        )
    return dicts_to_frame(rows)


def outcode_to_geography(
    outcodes: str | Iterable[str],
    geography_type: Any = "LSOA",
    base_url: str = POSTCODES_BASE_URL,
) -> Any:
    """Approximate an outcode to a single geography via its centroid.

    .. warning::
        An outcode covers many LSOAs/wards. This returns the geography
        *containing the outcode's geometric centroid* — a rough stand-in, not
        an exact mapping. For per-area analysis (e.g. counts per capita by
        LSOA) prefer full postcodes via :func:`postcodes_to_geography`, or a
        population-weighted split across the outcode's constituent areas.

    Args:
        outcodes: A single outcode or an iterable of outcodes.
        geography_type: Target level (see :func:`postcodes_to_geography`).
        base_url: postcodes.io base URL.

    Returns:
        DataFrame with columns ``outcode``, ``geography_code``,
        ``geography_name`` (centroid-based; ``None`` for unrecognised outcodes).

    Raises:
        ValueError: If ``geography_type`` is not supported.
        ImportError: If neither pandas nor polars is installed.
    """
    code_col, name_col = _resolve_level(geography_type)
    rows: list[dict[str, Any]] = []
    for outcode in _as_list(outcodes):
        centroid = _get(f"{base_url}/outcodes/{outcode}")
        nearest = None
        if centroid and centroid.get("longitude") is not None:
            results = _get_list(
                f"{base_url}/postcodes",
                params={
                    "lon": centroid["longitude"],
                    "lat": centroid["latitude"],
                },
            )
            nearest = results[0] if results else None
        mapped = _row_from_result(outcode, nearest)
        rows.append(
            {
                "outcode": outcode,
                "geography_code": mapped[code_col],
                "geography_name": mapped[name_col] if name_col else None,
            }
        )
    return dicts_to_frame(rows)


def _post(url: str, payload: dict) -> dict:
    """POST JSON and return the parsed body."""
    logger.info("POST %s", url)
    response = requests.post(url, json=payload, timeout=60)
    response.raise_for_status()
    return response.json()


def _get(url: str, params: dict | None = None) -> dict | None:
    """GET a single-object endpoint, returning its ``result`` (or None on 404)."""
    logger.info("GET %s", url)
    response = requests.get(url, params=params, timeout=60)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json().get("result")


def _get_list(url: str, params: dict | None = None) -> list | None:
    """GET a list endpoint, returning its ``result`` list (or None)."""
    logger.info("GET %s", url)
    response = requests.get(url, params=params, timeout=60)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json().get("result")
