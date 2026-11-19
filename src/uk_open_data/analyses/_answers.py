"""Words shared by the sentences that answer an analysis's question.

Every analysis ends with a sentence or two that answer its question. The
sentence is built from the figures and tables the result holds, after small
counts are hidden, so it can say nothing the result does not already show.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from uk_open_data.analyses._model import Figure, Table

AREA = "the area you serve"
HIDDEN = "hidden to protect a small count"
NAMED = 3  # how many places or groups a sentence names before it counts the rest
SHOWN_FIRST = 3  # how many key figures a result names
# An answer says how many people it leaves out when they are this share or more.
LARGE_SHARE_LEFT_OUT = 0.2


@dataclass(frozen=True)
class NeedWords:
    """The words for the people a need counts, so a sentence fits the measure."""

    people: str
    per: str
    high: str
    # For labels and headings: what is counted, and the places with most of it.
    noun: str = "people in need"
    places: str = "high-need local authorities"
    # What a label calls the total: "People in need in the area you serve".
    counted: str = "People in need"
    # What a title sets beside reach or provision: "Need and reach".
    topic: str = "need"
    # What the working says of a place in the top quarter.
    rule: str = "is high need"

    def headings(self) -> dict[str, str]:
        """Headings for the columns about need, in the words that fit."""
        if self.noun == IN_NEED.noun:
            return {}
        return {
            "people_in_need": "Residents",
            "people_per_100_in_need": "Your people per 100 residents",
            "volume_per_1000_in_need": "Provision per 1,000 residents",
            "high_need": "Among the most residents",
            "need_band": "Residents, grouped",
        }


IN_NEED = NeedWords("the people in need", "in need", "high need")
# Every resident is not a need, so no sentence, label or heading calls it one.
ALL_RESIDENTS = NeedWords(
    "residents",
    "residents",
    "the most residents",
    noun="residents",
    places="the local authorities with the most residents",
    counted="People",
    topic="residents",
    rule="is among those with the most residents",
)


def sentence_case(text: str) -> str:
    """Start a label with a capital letter and leave the rest as it is."""
    return text[:1].upper() + text[1:]


def need_words(residents: bool) -> NeedWords:
    """Pick the words for a measure of need, or for a count of every resident."""
    return ALL_RESIDENTS if residents else IN_NEED


def shown_first(figures: Sequence[Figure], wanted: Sequence[str]) -> tuple[str, ...]:
    """The first three of the wanted figures that are not hidden, in order.

    A figure hidden to protect a small count has nothing to show, so the next
    wanted figure takes its place.
    """
    hidden = {figure.id for figure in figures if figure.suppressed}
    return tuple(i for i in wanted if i not in hidden)[:SHOWN_FIRST]


def values(figures: Sequence[Figure]) -> dict[str, Any]:
    """The value of each figure by its id. A hidden figure has ``None``."""
    return {figure.id: figure.value for figure in figures}


def column(table: Table, name: str) -> list[Any]:
    """One column of a table, in the order of its rows."""
    return [row[name] for row in table.rows]


def names(items: Sequence[str], last: str = "and") -> str:
    """Join names as a person would say them, counting any beyond the first few."""
    shown = list(items[:NAMED])
    more = len(items) - len(shown)
    if more:
        return f"{', '.join(shown)} {last} {more} more"
    if len(shown) == 1:
        return shown[0]
    return f"{', '.join(shown[:-1])} {last} {shown[-1]}"


def look_first(
    priority: Table,
    lowest: str,
    rate: str,
    overall: float | None,
    high: str = IN_NEED.high,
) -> str:
    """Name the first few listed places that fall below the whole area, or none.

    A priority list holds every high-need place when there are few, so its
    first rows are not always places that lag. A place is named only when its
    rate, in the column ``rate``, is below the rate for the whole area,
    ``overall``. A place whose rate is hidden is not named.

    ``lowest`` says what the list is in order of, such as "your lowest reach".
    The sentence starts with a space so it can follow another.
    """
    places = [
        row["geography_name"]
        for row in priority.rows
        if row[rate] is not None and (overall is None or row[rate] < overall)
    ][:NAMED]
    if not places:
        return ""
    if len(places) == 1:
        return f" The place to look at first, with {high} and {lowest}, is {places[0]}."
    return (
        f" The places to look at first, with {high} and {lowest}, are {names(places)}."
    )


def not_counted(supplied: int, located: int, counted: int) -> str:
    """Say how many people an answer leaves out, when it is a large share.

    People who could not be placed at all are a mistake in the data to put
    right. People who live outside the area are not. So when there are both,
    the sentence says how many of each. It starts with a space so it can
    follow another.
    """
    left_out = supplied - counted
    if left_out < LARGE_SHARE_LEFT_OUT * supplied:
        return ""
    unplaced, outside = supplied - located, located - counted
    opening = f" {number(left_out)} of the {number(supplied)} people in your data"
    if unplaced and outside:
        return (
            f"{opening} are not counted: {number(unplaced)} could not be "
            f"placed in a local authority, and {number(outside)} live outside "
            f"{AREA}."
        )
    return f"{opening} could not be placed in {AREA} and are not counted."


def number(value: float) -> str:
    """A number as the figures show it, with commas in the thousands."""
    return f"{value:,}"


def high_need_places(count: int, high: str = IN_NEED.high) -> str:
    """Name the local authorities with high need, by how many there are."""
    if count == 1:
        return f"the one local authority with {high}"
    return f"the {count} local authorities with {high}"
