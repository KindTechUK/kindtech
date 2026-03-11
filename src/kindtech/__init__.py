"""KindTech package."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("kindtech")
except PackageNotFoundError:
    # Package is not installed
    __version__ = "0.0.0"

# Import key functions for easier access
from kindtech._mapping import (
    list_dataset_aliases,
    list_geography_mappings,
)
from kindtech.geo import load_geodata
from kindtech.ons import load_ons

# Define what's available when using `from kindtech import *`
__all__ = [
    "list_dataset_aliases",
    "list_geography_mappings",
    "load_geodata",
    "load_ons",
]
