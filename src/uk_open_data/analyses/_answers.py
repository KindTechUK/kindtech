"""Words shared by the sentences that answer an analysis's question.

Every analysis ends with a sentence or two that answer its question. The
sentence is built from the figures and tables the result holds, after small
counts are hidden, so it can say nothing the result does not already show.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from uk_open_data.analyses._model import Figure, Table

AREA = "the area you serve"
HIDDEN = "hidden to protect a small count"
NAMED = 3  # how many places or groups a sentence names before it counts the rest


def values(figures: Sequence[Figure]) -> dict[str, Any]:
    """The value of each figure by its id. A hidden figure has ``None``."""
    return {figure.id: figure.value for figure in figures}


def column(table: Table, name: str) -> list[Any]:
    """One column of a table, in the order of its rows."""
    return [row[name] for row in table.rows]


def names(items: Sequence[str]) -> str:
    """Join names as a person would say them, counting any beyond the first few."""
    shown = list(items[:NAMED])
    more = len(items) - len(shown)
    if more:
        return f"{', '.join(shown)} and {more} more"
    if len(shown) == 1:
        return shown[0]
    return f"{', '.join(shown[:-1])} and {shown[-1]}"


def look_first(priority: Table, lowest: str) -> str:
    """Name the first few places of a priority list, or say nothing.

    ``lowest`` says what the list is in order of, such as "your lowest reach".
    The sentence starts with a space so it can follow another.
    """
    places = column(priority, "geography_name")[:NAMED]
    if not places:
        return ""
    if len(places) == 1:
        return (
            f" The place to look at first, with high need and {lowest}, is {places[0]}."
        )
    return (
        f" The places to look at first, with high need and {lowest}, are "
        f"{names(places)}."
    )


def number(value: float) -> str:
    """A number as the figures show it, with commas in the thousands."""
    return f"{value:,}"


def high_need_places(count: int) -> str:
    """Name the local authorities with high need, by how many there are."""
    if count == 1:
        return "the one local authority with high need"
    return f"the {count} local authorities with high need"
