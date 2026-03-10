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

from . import _catalog
from ._enums import BoundaryType, CoverageArea, GeographyType, Month

logger = logging.getLogger(__name__)


def _extract_code(value: Any) -> str | None:
    """Extract string code from an enum or pass through a string."""
    if value is None:
        return None
    return value.code if hasattr(value, "code") else value


def _resolve_service_url(
    geography_type: str | GeographyType,
    year: str | None = None,
    month: str | Month | None = None,
    coverage: str | CoverageArea | None = None,
    boundary_type: str | BoundaryType | None = None,
) -> str | None:
    """Find the best matching service and return its FeatureServer URL."""
    geo = _extract_code(geography_type)
    mon = _extract_code(month)
    cov = _extract_code(coverage)
    bnd = _extract_code(boundary_type)

    if year:
        matches = _catalog.find_services(
            geography_type=geo, year=year, month=mon, coverage=cov, boundary_type=bnd
        )
        if not matches and mon:
            matches = _catalog.find_services(
                geography_type=geo, year=year, coverage=cov, boundary_type=bnd
            )
        service_name = matches[0]["arcgis_id"] if matches else None
    else:
        service_name = _catalog.get_most_recent_service(
            geography_type=geo,
            coverage=cov or "UK",
            boundary_type=bnd,
        )

    if not service_name:
        logger.warning(
            "No matching service found for: geography_type=%s, year=%s, coverage=%s",
            geo,
            year,
            cov,
        )
        return None
    return _catalog.get_service_url(service_name)


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
    url = _resolve_service_url(geography_type, year, month, coverage, boundary_type)
    if not url:
        return {"type": "FeatureCollection", "features": []}

    return _query_arcgis_service(url, filters or None)


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
    url = _resolve_service_url(
        geography_type, year, coverage=coverage, boundary_type=boundary_type
    )
    if not url:
        return []

    layer_url = f"{url}/0"
    try:
        response = requests.get(layer_url, params={"f": "json"})
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
        response = requests.get(layer_url + "/query", params=params)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error("Error querying ArcGIS service: %s", e)
        return {"type": "FeatureCollection", "features": []}
