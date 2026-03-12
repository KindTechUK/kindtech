"""
KindTech Geo Package

Provides access to UK geospatial boundary data from the ONS ArcGIS Feature Servers.
"""

from ._enums import (
    BoundaryType,
    CoverageArea,
    GeographyType,
    Month,
)
from .api import (
    geodata_to_properties,
    get_available_boundary_types,
    get_available_coverage_areas,
    get_available_geography_types,
    get_field_info,
    load_geodata,
)

__all__ = [
    "BoundaryType",
    "CoverageArea",
    "GeographyType",
    "Month",
    "geodata_to_properties",
    "get_available_boundary_types",
    "get_available_coverage_areas",
    "get_available_geography_types",
    "get_field_info",
    "load_geodata",
]
