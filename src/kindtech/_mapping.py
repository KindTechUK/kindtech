"""
Geography crosswalk and dataset aliases for ONS/NOMIS data.

Maps the GeographyType codes used in ``kindtech.geo`` to the internal
TYPE codes used by the NOMIS API, handling the fact that NOMIS assigns
different TYPE codes to the same geography concept at different time
points (e.g. LADs are TYPE424 from 2023, TYPE431 for 2021-2022, etc.).

Also provides friendly dataset aliases so users can say
``load_ons("population")`` instead of ``load_ons("NM_2002_1")``.

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

# Friendly aliases for common NOMIS datasets.
# Keys are lowercase; values are NOMIS dataset IDs.
DATASET_ALIASES: dict[str, str] = {
    # Population
    "population": "NM_2002_1",
    "population_by_age": "NM_2002_1",
    "population_by_age_band": "NM_31_1",
    "population_lsoa": "NM_2014_1",
    # Employment / labour market
    "jsa": "NM_1_1",
    "claimant_count": "NM_162_1",
    "annual_population_survey": "NM_17_1",
    "earnings": "NM_30_1",
    "jobs_density": "NM_57_1",
    "vacancies": "NM_19_1",
    # Business
    "vat_registrations": "NM_29_1",
    # Census
    "census_2021": "NM_2021_1",
    "census_2011": "NM_144_1",
    "census_2001": "NM_58_1",
}


def resolve_dataset_id(dataset_id: str) -> str:
    """Resolve a dataset ID or friendly alias to a NOMIS dataset ID.

    If ``dataset_id`` starts with ``NM_``, returns it unchanged.
    Otherwise looks up the alias in ``DATASET_ALIASES``.

    Args:
        dataset_id: NOMIS dataset ID (e.g. ``"NM_1_1"``) or friendly
            alias (e.g. ``"population"``).

    Returns:
        NOMIS dataset ID string.

    Raises:
        ValueError: If the alias is not recognised.
    """
    if dataset_id.startswith("NM_"):
        return dataset_id
    key = dataset_id.lower().strip()
    if key in DATASET_ALIASES:
        return DATASET_ALIASES[key]
    available = ", ".join(sorted(DATASET_ALIASES))
    msg = (
        f"Unknown dataset alias '{dataset_id}'. "
        f"Available: {available}. "
        f"Or pass a NOMIS ID like 'NM_1_1'."
    )
    raise ValueError(msg)


def list_dataset_aliases() -> list[dict[str, str]]:
    """Return dataset aliases as a list of dicts.

    Each dict has keys: ``alias``, ``dataset_id``.
    """
    return [
        {"alias": alias, "dataset_id": did}
        for alias, did in sorted(DATASET_ALIASES.items())
    ]


def resolve_nomis_geography(
    geography_type: str,
    year: int | None = None,
) -> str:
    """Resolve a geography type code to a NOMIS TYPE code.

    Args:
        geography_type: ONS geography code
            (e.g. ``"LAD"``, ``"LSOA"``).
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
    """Return the ArcGIS code field name.

    Example:
        >>> geo_code_field("LAD", 2024)
        'LAD24CD'
    """
    return f"{geography_type.upper()}{year % 100:02d}CD"


def geo_name_field(geography_type: str, year: int) -> str:
    """Return the ArcGIS name field name.

    Example:
        >>> geo_name_field("LAD", 2024)
        'LAD24NM'
    """
    return f"{geography_type.upper()}{year % 100:02d}NM"


def list_geography_mappings() -> list[dict[str, str]]:
    """Return the geography crosswalk as a list of dicts.

    Each dict has keys: ``geography_type``, ``year_from``,
    ``year_to``, ``nomis_type``.
    """
    rows: list[dict[str, str]] = []
    for geo_type, ranges in sorted(NOMIS_GEO_TYPES.items()):
        for min_year, max_year, type_code in ranges:
            rows.append(
                {
                    "geography_type": geo_type,
                    "year_from": (str(min_year) if min_year > 0 else ""),
                    "year_to": (str(max_year) if max_year < 9999 else ""),
                    "nomis_type": type_code,
                }
            )
    return rows
