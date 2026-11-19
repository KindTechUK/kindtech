"""UK open data for charities: boundaries, statistics, postcodes and analyses."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("uk-open-data")
except PackageNotFoundError:
    # Package is not installed
    __version__ = "0.0.0"

# Import key functions for easier access
from uk_open_data._mapping import (
    list_dataset_aliases,
    list_geography_mappings,
)
from uk_open_data.geo import geodata_to_properties, load_geodata
from uk_open_data.imd import load_imd
from uk_open_data.ons import list_tables, load_ons
from uk_open_data.postcodes import (
    lookup_outcodes,
    lookup_postcodes,
    outcode_to_geography,
    postcodes_to_geography,
)

# Define what's available when using `from uk_open_data import *`
__all__ = [
    "geodata_to_properties",
    "list_dataset_aliases",
    "list_geography_mappings",
    "list_tables",
    "load_geodata",
    "load_imd",
    "load_ons",
    "lookup_outcodes",
    "lookup_postcodes",
    "outcode_to_geography",
    "postcodes_to_geography",
]
