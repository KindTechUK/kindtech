"""
Geography crosswalk between ONS geography types and NOMIS TYPE codes.

Maps the GeographyType codes used in ``kindtech.geo`` to the internal
TYPE codes used by the NOMIS API, handling the fact that NOMIS assigns
different TYPE codes to the same geography concept at different time
points (e.g. LADs are TYPE424 from 2023, TYPE431 for 2021-2022, etc.).

Both APIs return standard ONS geography codes (e.g. E06000001) so
joins between geo boundaries and NOMIS statistics are reliable on
codes, not names.
"""

from __future__ import annotations

# Each value is a list of (min_year, max_year, nomis_type_code) tuples,
# sorted newest-first. The first match for a given year wins.
# Source: NOMIS geography dimension metadata via
# nomisweb.co.uk/api/v01/dataset/NM_1_1/geography.def.sdmx.json
NOMIS_GEO_TYPES: dict[str, list[tuple[int, int, str]]] = {
    "LAD": [
        (2023, 9999, "TYPE424"),
        (2021, 2022, "TYPE431"),
        (2019, 2020, "TYPE434"),
        (2015, 2018, "TYPE446"),
        (0, 2014, "TYPE464"),
    ],
    "CTYUA": [
        (2023, 9999, "TYPE423"),
        (2021, 2022, "TYPE431"),
        (2015, 2020, "TYPE446"),
        (0, 2014, "TYPE463"),
    ],
    "LSOA": [
        (2021, 9999, "TYPE151"),
        (0, 2020, "TYPE304"),
    ],
    "MSOA": [
        (2021, 9999, "TYPE152"),
        (0, 2020, "TYPE305"),
    ],
    "RGN": [(0, 9999, "TYPE480")],
    "CTRY": [(0, 9999, "TYPE499")],
    "WD": [(2025, 9999, "TYPE182")],
    "CAUTH": [(2025, 9999, "TYPE442")],
    "TTWA": [
        (2011, 9999, "TYPE447"),
        (0, 2010, "TYPE444"),
    ],
    "ITL": [
        (2025, 9999, "TYPE419"),
        (2021, 2024, "TYPE421"),
    ],
}


def resolve_nomis_geography(
    geography_type: str,
    year: int | None = None,
) -> str:
    """Resolve a geography type code to a NOMIS TYPE code.

    Args:
        geography_type: ONS geography code (e.g. ``"LAD"``, ``"LSOA"``).
        year: Optional year for version-specific resolution.
            If ``None``, returns the most recent TYPE code.

    Returns:
        NOMIS TYPE code string (e.g. ``"TYPE424"``).

    Raises:
        ValueError: If the geography type has no NOMIS mapping.
    """
    code = geography_type.upper()
    ranges = NOMIS_GEO_TYPES.get(code)
    if not ranges:
        supported = ", ".join(sorted(NOMIS_GEO_TYPES))
        msg = f"No NOMIS mapping for geography type '{code}'. Supported: {supported}"
        raise ValueError(msg)

    if year is None:
        return ranges[0][2]

    for min_year, max_year, type_code in ranges:
        if min_year <= year <= max_year:
            return type_code

    msg = (
        f"No NOMIS TYPE code for '{code}' in year {year}. "
        f"Available ranges: " + ", ".join(f"{lo}-{hi} → {tc}" for lo, hi, tc in ranges)
    )
    raise ValueError(msg)


def geo_code_field(geography_type: str, year: int) -> str:
    """Return the ArcGIS code field name for a geography type and year.

    Example:
        >>> geo_code_field("LAD", 2024)
        'LAD24CD'
    """
    return f"{geography_type.upper()}{year % 100:02d}CD"


def geo_name_field(geography_type: str, year: int) -> str:
    """Return the ArcGIS name field name for a geography type and year.

    Example:
        >>> geo_name_field("LAD", 2024)
        'LAD24NM'
    """
    return f"{geography_type.upper()}{year % 100:02d}NM"


def list_geography_mappings() -> list[dict[str, str]]:
    """Return the geography crosswalk as a list of dicts.

    Each dict has keys: ``geography_type``, ``year_from``,
    ``year_to``, ``nomis_type``.

    Returns:
        List of mapping entries for display or documentation.
    """
    rows: list[dict[str, str]] = []
    for geo_type, ranges in sorted(NOMIS_GEO_TYPES.items()):
        for min_year, max_year, type_code in ranges:
            rows.append(
                {
                    "geography_type": geo_type,
                    "year_from": str(min_year) if min_year > 0 else "",
                    "year_to": (str(max_year) if max_year < 9999 else ""),
                    "nomis_type": type_code,
                }
            )
    return rows
