"""
KindTech Postcodes Package

Turns UK postcodes and outcodes into ONS geography codes via postcodes.io, so
address data joins directly to KindTech boundaries and statistics.
"""

from .api import (
    lookup_outcodes,
    lookup_postcodes,
    outcode_to_geography,
    postcodes_to_geography,
)

__all__ = [
    "lookup_outcodes",
    "lookup_postcodes",
    "outcode_to_geography",
    "postcodes_to_geography",
]
