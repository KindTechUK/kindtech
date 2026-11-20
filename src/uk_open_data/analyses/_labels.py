"""The plain name of each option, the same on every door.

A page shows the name beside the option, the command line lists it, and every
message that points a person at an option uses it, in quotes. The code name,
such as ``catchment``, is for whoever writes the call and is never put in a
sentence a person reads.
"""

from __future__ import annotations

LABELS = {
    "catchment": "Area you serve",
    "catchment_min_share": "Share that makes a place part of your area",
    "characteristic": "What people are grouped by",
    "groups": "How your labels match census groups",
    "need": "Who counts as in need",
    "postcode_lookup": "Where postcodes are looked up",
    "suppress_below": "Smallest count shown",
    "top": "Places listed",
    "under_represented_below": "What counts as under-represented",
    "within_km": "Distance within reach, in kilometres",
}


def said(option: str) -> str:
    """Give an option's plain name in quotes, ready to put in a sentence."""
    return f"'{LABELS[option]}'"
