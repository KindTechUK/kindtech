"""
KindTech Geo API

Provides a simple interface for accessing geospatial data from ArcGIS Feature Servers.

Examples:
    >>> from uk_open_data.geo import load_geodata, GeographyType, CoverageArea
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

from uk_open_data._mapping import extract_code, geo_code_field, geo_name_field

from . import _catalog
from ._enums import BoundaryType, CoverageArea, GeographyType, Month

logger = logging.getLogger(__name__)

# A boundary service answers with a few thousand features at most, and says
# so. The rest are asked for page by page, up to this many pages.
MAX_PAGES = 500
FLAG = "exceededTransferLimit"

# The number of the layer each service holds, kept once a service has said.
_LAYERS: dict[str, int] = {}

# One degree of latitude, near enough for telling a service how much detail
# to leave out of an outline.
METRES_PER_DEGREE = 111_320


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
    simplify_m: float | None = None,
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
        simplify_m: Ask the service to simplify each outline, leaving out
            detail finer than about this many metres. Use it with a
            full-resolution layer ("BFE" or "BFC") when no generalised one is
            published, for example ``simplify_m=20`` for neighbourhoods.
            Left out, outlines come as the layer holds them.
        **filters: Field filters (e.g., LAD21NM="Manchester")

    Returns:
        GeoJSON FeatureCollection as a dictionary. A large layer is fetched
        page by page, so every feature is there. The collection is empty,
        and an error is logged, when no service matches or a request fails:
        it is never a part of the layer.

    Raises:
        ValueError: If ``simplify_m`` is not above zero.
    """
    if simplify_m is not None and simplify_m <= 0:
        raise ValueError("simplify_m must be a number of metres above zero.")

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

    return _query_arcgis_service(service["url"], filters or None, simplify_m)


def geodata_to_properties(
    geojson: dict[str, Any],
    geography_type: str | GeographyType,
    year: int | str,
) -> list[dict[str, Any]]:
    """Extract feature properties with normalised column names.

    Adds ``geography_code`` and ``geography_name`` keys derived
    from the year-stamped ArcGIS field names (e.g. ``LAD24CD``),
    so they match ``geography_code`` / ``geography_name`` from
    :func:`~uk_open_data.ons.api.load_ons`.

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

    layer_url = _layer_url(service["url"])
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
    simplify_m: float | None = None,
) -> dict[str, Any]:
    """
    Query an ArcGIS Feature Server service and return GeoJSON results.

    Args:
        service_url: URL of the ArcGIS Feature Server service.
        filters: Optional field filters to apply.
        simplify_m: Detail to leave out of each outline, in metres.

    Returns:
        GeoJSON FeatureCollection as a dictionary. A layer larger than the
        service gives in one answer is asked for page by page, so the
        collection is whole. When any request fails, or the service does not
        page, the collection is empty: never a part of the layer.
    """
    layer_url = _layer_url(service_url)

    params: dict[str, Any] = {
        "f": "geojson",
        "outFields": "*",
        "where": "1=1",
        "outSR": 4326,
    }
    if simplify_m is not None:
        # The service takes this in the units of the answer, which are degrees.
        params["maxAllowableOffset"] = round(simplify_m / METRES_PER_DEGREE, 7)

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

    empty: dict[str, Any] = {"type": "FeatureCollection", "features": []}
    try:
        logger.info("Querying ArcGIS service: %s", layer_url)
        first = _query_page(layer_url, params, 0)
        features = list(first.get("features") or [])
        if not features or not _cut_short(first):
            return first
        for _ in range(MAX_PAGES):
            page = _query_page(layer_url, params, len(features))
            got = page.get("features") or []
            if got and got[0] == features[0]:
                # The service ignored the offset and gave the first page again.
                break
            features.extend(got)
            if not got or not _cut_short(page):
                return _whole_collection(first, features)
    except requests.exceptions.RequestException as e:
        logger.error("Error querying ArcGIS service: %s", e)
        return empty
    logger.error("The ArcGIS service did not stop paging: %s", layer_url)
    return empty


def _layer_url(service_url: str) -> str:
    """The address of the layer a boundary service holds.

    Most services hold one layer, numbered 0, but not all: the 2021
    neighbourhoods at full extent hold only layer 3. A service is asked for
    its layers once and the answer is kept. When it cannot be asked, or
    lists no layer, layer 0 is tried and nothing is kept, so the next call
    asks again.
    """
    if service_url not in _LAYERS:
        layer = _first_layer(service_url)
        if layer is None:
            return f"{service_url}/0"
        _LAYERS[service_url] = layer
    return f"{service_url}/{_LAYERS[service_url]}"


def _first_layer(service_url: str) -> int | None:
    """Ask a service for the number of its first layer, or None if it has none."""
    try:
        response = requests.get(service_url, params={"f": "json"}, timeout=60)
        response.raise_for_status()
        layers = response.json().get("layers") or []
    except (requests.exceptions.RequestException, ValueError) as error:
        logger.warning("Could not list the layers of %s: %s", service_url, error)
        return None
    number = layers[0].get("id") if layers else None
    return number if isinstance(number, int) else None


def _query_page(layer_url: str, params: dict[str, Any], offset: int) -> dict[str, Any]:
    """Ask for one page of a layer, starting after ``offset`` features."""
    asked = {**params, "resultOffset": offset} if offset else params
    response = requests.get(layer_url + "/query", params=asked, timeout=60)
    response.raise_for_status()
    return response.json()


def _cut_short(page: dict[str, Any]) -> bool:
    """Whether the service says it has more features than it gave.

    The flag is at the top of an answer in the service's own format, and
    under ``properties`` in a GeoJSON answer.
    """
    properties = page.get("properties") or {}
    return bool(page.get(FLAG) or properties.get(FLAG))


def _whole_collection(first: dict[str, Any], features: list[Any]) -> dict[str, Any]:
    """Put every page's features in one collection that no longer says it is cut."""
    whole = {key: value for key, value in first.items() if key != FLAG}
    if isinstance(whole.get("properties"), dict):
        whole["properties"] = {
            key: value for key, value in whole["properties"].items() if key != FLAG
        }
    whole["features"] = features
    return whole
