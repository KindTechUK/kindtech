"""
KindTech Geo API

Provides a simple interface for accessing geospatial data from ArcGIS Feature Servers.

Examples:
    >>> from kindtech.geo import load_geodata, GeographyType, CoverageArea
    >>>
    >>> # Using string parameters
    >>> data = load_geodata(geography_type="LAD", coverage="UK", boundary_type="BGC")
    >>>
    >>> # Using enum parameters
    >>> data = load_geodata(
    ...     geography_type=GeographyType.LAD,
    ...     coverage=CoverageArea.UK,
    ...     boundary_type="BGC"
    ... )
    >>>
    >>> # Using filters
    >>> data = load_geodata(geography_type="LAD", LAD21NM="Manchester")
"""

import logging
from typing import Any

import requests

from kindtech._mapping import extract_code, geo_code_field, geo_name_field

from . import _catalog
from ._enums import BoundaryType, CoverageArea, GeographyType, Month

logger = logging.getLogger(__name__)


def _resolve_service(
    geography_type: str | GeographyType,
    year: str | None = None,
    month: str | Month | None = None,
    coverage: str | CoverageArea | None = None,
    boundary_type: str | BoundaryType | None = None,
) -> dict | None:
    """Find the best matching service and return its metadata.

    Returns:
        Dict with ``url``, ``geography``, ``year`` keys,
        or ``None`` if no match found.
    """
    geo = extract_code(geography_type)
    mon = extract_code(month)
    cov = extract_code(coverage)
    bnd = extract_code(boundary_type)

    match: dict | None = None
    if year:
        matches = _catalog.find_services(
            geography_type=geo,
            year=year,
            month=mon,
            coverage=cov,
            boundary_type=bnd,
        )
        if not matches and mon:
            matches = _catalog.find_services(
                geography_type=geo,
                year=year,
                coverage=cov,
                boundary_type=bnd,
            )
        if matches:
            matches.sort(key=lambda m: int(m["year"]), reverse=True)
        match = matches[0] if matches else None
    else:
        match = _catalog.get_most_recent_service(
            geography_type=geo,
            coverage=cov or "UK",
            boundary_type=bnd,
        )

    if not match:
        logger.warning(
            "No matching service found for: geography_type=%s, year=%s, coverage=%s",
            geo,
            year,
            cov,
        )
        return None

    return {
        "url": _catalog.get_service_url(match["arcgis_id"]),
        "geography": match["geography"],
        "year": int(match["year"]),
    }


def load_geodata(
    geography_type: str | GeographyType,
    year: str | None = None,
    month: str | Month | None = None,
    coverage: str | CoverageArea | None = None,
    boundary_type: str | BoundaryType | None = "BGC",
    **filters,
) -> dict[str, Any]:
    """
    Load geospatial data from ArcGIS Feature Server.

    Args:
        geography_type: Geography type (e.g., "LAD", or GeographyType.LAD)
        year: Year of the data (e.g., "2021")
        month: Month of the data (e.g., "JAN", or Month.JAN)
        coverage: Coverage area (e.g., "UK", or CoverageArea.UK)
        boundary_type: Boundary type (e.g., "BGC", or BoundaryType.BGC)
        **filters: Field filters (e.g., LAD21NM="Manchester")

    Returns:
        GeoJSON FeatureCollection as a dictionary.
    """
    service = _resolve_service(
        geography_type,
        year,
        month,
        coverage,
        boundary_type,
    )
    if not service:
        return {"type": "FeatureCollection", "features": []}

    if year is None:
        logger.warning(
            "No year specified — using %s boundaries (year %d). "
            "Pass year='%d' to silence this warning.",
            service["geography"],
            service["year"],
            service["year"],
        )

    return _query_arcgis_service(service["url"], filters or None)


def geodata_to_properties(
    geojson: dict[str, Any],
    geography_type: str | GeographyType,
    year: int | str,
) -> list[dict[str, Any]]:
    """Extract feature properties with normalised column names.

    Adds ``geography_code`` and ``geography_name`` keys derived
    from the year-stamped ArcGIS field names (e.g. ``LAD24CD``),
    so they match ``geography_code`` / ``geography_name`` from
    :func:`~kindtech.ons.api.load_ons`.

    Args:
        geojson: GeoJSON FeatureCollection returned by
            :func:`load_geodata`.
        geography_type: Geography type used in the original query
            (e.g., ``"LAD"``).
        year: Data vintage year (e.g., ``2024`` or ``"2024"``).

    Returns:
        List of property dicts, each with ``geography_code`` and
        ``geography_name`` prepended.

    Example::

        geo = load_geodata("LAD")
        rows = geodata_to_properties(geo, "LAD", 2024)
        # rows[0]["geography_code"] == "E06000001"
    """
    geo = extract_code(geography_type)
    yr = int(year)
    code_field = geo_code_field(geo, yr)
    name_field = geo_name_field(geo, yr)

    rows: list[dict[str, Any]] = []
    warned = False
    for feature in geojson.get("features", []):
        props = feature.get("properties", {})
        code_val = props.get(code_field, "")
        if not code_val and not warned and props:
            import warnings

            warnings.warn(
                f"Field '{code_field}' not found in GeoJSON "
                f"properties. Check that geography_type="
                f"'{geo}' and year={yr} match the data "
                f"returned by load_geodata(). Available "
                f"fields: {list(props.keys())}",
                stacklevel=2,
            )
            warned = True
        row: dict[str, Any] = {
            "geography_code": code_val,
            "geography_name": props.get(name_field, ""),
        }
        row.update(props)
        rows.append(row)
    return rows


def get_field_info(
    geography_type: str | GeographyType,
    year: str | None = None,
    coverage: str | CoverageArea | None = None,
    boundary_type: str | BoundaryType | None = None,
) -> list[dict[str, Any]]:
    """
    Get available fields for filtering in a dataset.

    Args:
        geography_type: Geography type (e.g., "LAD", or GeographyType.LAD)
        year: Year of the data (e.g., "2021")
        coverage: Coverage area (e.g., "UK", or CoverageArea.UK)
        boundary_type: Boundary type (e.g., "BGC", or BoundaryType.BGC)

    Returns:
        List of field info dicts with name, type, alias, etc.
    """
    service = _resolve_service(
        geography_type,
        year,
        coverage=coverage,
        boundary_type=boundary_type,
    )
    if not service:
        return []

    layer_url = f"{service['url']}/0"
    try:
        response = requests.get(layer_url, params={"f": "json"}, timeout=60)
        response.raise_for_status()
        data = response.json()
        return data.get("fields", [])
    except requests.exceptions.RequestException as e:
        logger.error("Error querying ArcGIS service metadata: %s", e)
        return []


def get_available_geography_types() -> list[dict[str, str]]:
    """Get available geography types with their codes and descriptions."""
    return [{"code": g.code, "description": g.description} for g in GeographyType]


def get_available_boundary_types() -> list[dict[str, str]]:
    """Get available boundary types with their codes and descriptions."""
    return [{"code": b.code, "description": b.description} for b in BoundaryType]


def get_available_coverage_areas() -> list[dict[str, str]]:
    """Get available coverage areas with their codes and descriptions."""
    return [{"code": c.code, "description": c.description} for c in CoverageArea]


def _query_arcgis_service(
    service_url: str,
    filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Query an ArcGIS Feature Server service and return GeoJSON results.

    Args:
        service_url: URL of the ArcGIS Feature Server service.
        filters: Optional field filters to apply.

    Returns:
        GeoJSON FeatureCollection as a dictionary.
    """
    layer_url = f"{service_url}/0"

    params = {
        "f": "geojson",
        "outFields": "*",
        "where": "1=1",
        "outSR": 4326,
    }

    if filters:
        where_clauses = []
        for field, value in filters.items():
            if isinstance(value, str):
                where_clauses.append(f"{field} = '{value}'")
            elif isinstance(value, int | float):
                where_clauses.append(f"{field} = {value}")
            elif isinstance(value, list):
                values_str = ", ".join(
                    f"'{v}'" if isinstance(v, str) else str(v) for v in value
                )
                where_clauses.append(f"{field} IN ({values_str})")
        if where_clauses:
            params["where"] = " AND ".join(where_clauses)

    try:
        logger.info("Querying ArcGIS service: %s", layer_url)
        response = requests.get(layer_url + "/query", params=params, timeout=60)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error("Error querying ArcGIS service: %s", e)
        return {"type": "FeatureCollection", "features": []}
