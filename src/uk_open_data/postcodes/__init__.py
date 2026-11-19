"""
KindTech Postcodes Package

Turns UK postcodes and outcodes into ONS geography codes via postcodes.io, so
address data joins directly to KindTech boundaries and statistics. The
``offline`` functions do the same from a table on this machine, so postcodes
are not sent anywhere.
"""

from .api import (
    lookup_outcodes,
    lookup_postcodes,
    outcode_to_geography,
    postcodes_to_geography,
)
from .offline import (
    PostcodeTableError,
    build_postcode_table,
    district_to_local_authorities,
    download_postcode_table,
    install_postcode_table,
    postcode_table_info,
    postcode_table_path,
    postcode_to_lsoa,
    postcodes_to_local_authority,
    postcodes_to_lsoa,
)

__all__ = [
    "PostcodeTableError",
    "build_postcode_table",
    "district_to_local_authorities",
    "download_postcode_table",
    "install_postcode_table",
    "lookup_outcodes",
    "lookup_postcodes",
    "outcode_to_geography",
    "postcode_table_info",
    "postcode_table_path",
    "postcode_to_lsoa",
    "postcodes_to_geography",
    "postcodes_to_local_authority",
    "postcodes_to_lsoa",
]
