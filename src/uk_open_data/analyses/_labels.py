"""The plain names of options and table columns, the same on every door.

A page shows an option's name beside it, the command line lists it, and every
message that points a person at an option uses it, in quotes. The code name,
such as ``catchment``, is for whoever writes the call and is never put in a
sentence a person reads.

A table column has a heading in the same way, and a unit where it has one, so
a table reads the same on a page, in a chat and on the command line.
"""

from __future__ import annotations

LABELS = {
    "catchment": "Area you serve",
    "catchment_min_share": "Share that makes a place part of your area",
    "characteristic": "What people are grouped by",
    "groups": "How your labels match census groups",
    "need": "People you are trying to reach",
    "postcode_lookup": "Where postcodes are looked up",
    "suppress_below": "Smallest count shown",
    "top": "Places listed",
    "under_represented_below": "What counts as under-represented",
    "within_km": "Distance within reach, in kilometres",
}


# The heading of each column an analysis in this package puts in a table. A
# table may give a column a heading of its own, where the shared one is too
# wide: a place is a neighbourhood in one table and a local authority in the rest.
HEADINGS = {
    "distance_band": "From its centre to your nearest site, grouped",
    "distance_km": "From its centre to your nearest site",
    "geography_code": "Code",
    "geography_name": "Local authority",
    "group": "Group",
    "high_need": "High need",
    "imd_decile": "Deprivation decile",
    "in_catchment": "In the area you serve",
    "lad_code": "Code",
    "lad_name": "Local authority",
    "local_authorities": "Local authorities in this row",
    "need_band": "Need, grouped",
    "people": "Your people",
    "people_band": "Your people, grouped",
    "people_in_need": "People in need",
    "people_in_need_per_1000_residents": "People in need per 1,000 residents",
    "people_per_1000": "Your people per 1,000 residents",
    "people_per_100_in_need": "Your people per 100 in need",
    "provision_band": "Provision, grouped",
    "rank": "Rank",
    "reach_band": "Reach, grouped",
    "representation": "Your share divided by the residents' share",
    "residents": "Residents",
    "share_of_people": "Share of your people",
    "share_of_residents": "Share of residents",
    "suppressed": "Hidden",
    "under_represented": "Under-represented",
    "volume": "Provision",
    "volume_per_1000_in_need": "Provision per 1,000 people in need",
    "within_reach": "Within reach",
}

# The unit of each column that has one, named as the units of figures are.
COLUMN_UNITS = {
    "distance_km": "km",
    "share_of_people": "percent",
    "share_of_residents": "percent",
}


def said(option: str) -> str:
    """Give an option's plain name in quotes, ready to put in a sentence."""
    return f"'{LABELS[option]}'"
