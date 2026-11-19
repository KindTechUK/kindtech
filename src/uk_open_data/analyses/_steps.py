"""Steps that more than one analysis takes.

Reading the options every analysis has, reading the data a person gives, and
placing postcodes. Each step writes what it did to a :class:`Trail`, and none of
them keeps or reports a value from the data.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any

import narwhals as nw

from uk_open_data.analyses._inputs import is_blank, tidy_postcode, to_count
from uk_open_data.analyses._labels import LABELS, said
from uk_open_data.analyses._model import (
    AnalysisInputError,
    Choice,
    Option,
    OptionChoice,
    Source,
    Step,
)
from uk_open_data.analyses._privacy import DEFAULT_SUPPRESS_BELOW
from uk_open_data.analyses.sources import POSTCODES_IO, ons_postcode_lookup
from uk_open_data.postcodes import (
    PostcodeTableError,
    lookup_postcodes,
    postcode_table_info,
    postcode_table_path,
    postcodes_to_geography,
    postcodes_to_local_authority,
    postcodes_to_lsoa,
)

MIN_SUPPRESS_BELOW = 3
LOOKUP_CHOICES = ("auto", "offline", "online")
EVERYWHERE = "England and Wales"
# The first letter of a local authority code in each country.
COUNTRIES = {"england": "E", "wales": "W"}

# A latitude and a longitude, in degrees.
Position = tuple[float, float]

NOT_A_COUNT = "a count that is not a whole number of zero or more"

# How to write a local authority so that it is found.
HOW_TO_NAME_A_PLACE = (
    "Write each council's name as the Office for National Statistics does, for "
    "example Lewisham, or give its code, for example E09000023."
)

# How many rows a message points at before it counts the rest.
ROWS_NAMED = 5

SUPPRESS_BELOW = Option(
    name="suppress_below",
    label=LABELS["suppress_below"],
    description=(
        "Counts above zero and below this number are hidden. It cannot "
        f"be set lower than {MIN_SUPPRESS_BELOW}."
    ),
    default=DEFAULT_SUPPRESS_BELOW,
)

POSTCODE_LOOKUP = Option(
    name="postcode_lookup",
    label=LABELS["postcode_lookup"],
    description=(
        "How postcodes are placed in areas. On this machine, a table is "
        "read and no postcode is sent anywhere. Online, the distinct "
        "postcodes are sent to postcodes.io. Left alone, the table is used "
        "when one is installed and postcodes.io otherwise."
    ),
    default="auto",
    choices=(
        OptionChoice("auto", "On this machine when a postcode table is installed"),
        OptionChoice("offline", "On this machine only"),
        OptionChoice("online", "With postcodes.io, an online service"),
    ),
)


CHOSE_ONLINE = (
    "You chose the online service. A postcode table is installed on this "
    f"machine, so nothing needs to be sent: change {said('postcode_lookup')} "
    "to look postcodes up on this machine."
)


@dataclass(frozen=True)
class Level:
    """A size of area that postcodes can be placed in."""

    geography_type: str
    singular: str
    plural: str


NEIGHBOURHOOD = Level("LSOA", "neighbourhood", "neighbourhoods")
LOCAL_AUTHORITY = Level("LAD", "local authority", "local authorities")


@dataclass
class Trail:
    """What a run records as it goes."""

    working: list[Step] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    sent: list[str] = field(default_factory=list)
    sources: list[Source] = field(default_factory=list)
    choices: list[Choice] = field(default_factory=list)
    hidden: int = 0


# --- words for counts and rows ---------------------------------------------


def plural(count: int, one: str) -> str:
    """Say a count with its noun: "1 row", "3 rows"."""
    return f"{count} {one}" if count == 1 else f"{count} {one}s"


def where_rows(positions: list[int]) -> str:
    """Say which rows of the data are meant, so a person can find them.

    A position says where a row is and nothing about what it holds. The first
    row of data is row 1, whatever headings sit above it.
    """
    shown = [str(position) for position in positions[:ROWS_NAMED]]
    more = len(positions) - len(shown)
    if more:
        listed = f"rows {', '.join(shown)} and {more} more"
    elif len(shown) == 1:
        listed = f"row {shown[0]}"
    else:
        listed = f"rows {', '.join(shown[:-1])} and {shown[-1]}"
    return f"{listed}, counting from the first row of data"


def bad_counts(positions: list[int], what: str) -> str:
    """Say which rows hold a count or volume that cannot be added up."""
    return (
        f"{plural(len(positions), 'row')} had {what}: {where_rows(positions)}. "
        "Correct them and run the analysis again."
    )


# --- options ---------------------------------------------------------------


def read_threshold(options: dict[str, Any]) -> int:
    """Read and check the small-count threshold."""
    value = options.get("suppress_below")
    if isinstance(value, bool) or not isinstance(value, int):
        msg = f"{said('suppress_below')} must be a whole number."
        raise AnalysisInputError(msg, option="suppress_below")
    if value < MIN_SUPPRESS_BELOW:
        msg = (
            f"{said('suppress_below')} cannot be lower than "
            f"{MIN_SUPPRESS_BELOW}, so that counts of one or two people are "
            "always hidden."
        )
        raise AnalysisInputError(msg, option="suppress_below")
    return value


def read_min_share(options: dict[str, Any]) -> float:
    """Read and check the share a local authority needs to join the area."""
    value = options.get("catchment_min_share")
    if isinstance(value, bool) or not isinstance(value, int | float):
        msg = f"{said('catchment_min_share')} must be a number."
        raise AnalysisInputError(msg, option="catchment_min_share")
    if not 0 < value <= 1:
        msg = (
            f"{said('catchment_min_share')} must be above 0 and no more "
            "than 1, for example 0.05 for five per cent."
        )
        raise AnalysisInputError(msg, option="catchment_min_share")
    return float(value)


def use_postcode_table(options: dict[str, Any]) -> bool:
    """Decide whether postcodes are looked up in the table on this machine."""
    how = options.get("postcode_lookup")
    if how not in LOOKUP_CHOICES:
        msg = f"{said('postcode_lookup')} must be one of: {', '.join(LOOKUP_CHOICES)}."
        raise AnalysisInputError(msg, option="postcode_lookup")
    if how == "auto":
        return postcode_table_path() is not None
    return how == "offline"


def named_areas(
    wanted: Any, names: Mapping[str, str], listed_in: str
) -> tuple[tuple[str, ...], str]:
    """Turn the area a person named into local authority codes.

    Args:
        wanted: The 'catchment' option: a local authority name or code, a list
            of them, or 'England', 'Wales' or 'England and Wales'.
        names: Code to name, for every local authority the analysis has figures
            for.
        listed_in: What those figures are, for the message when a name is not
            among them, such as "need figures".

    Returns:
        The codes, sorted, and a label for the area.

    Raises:
        AnalysisInputError: If the option has the wrong shape, or names a place
            the figures do not list.
    """
    items = [wanted] if isinstance(wanted, str) else wanted
    if (
        not isinstance(items, list | tuple)
        or not items
        or not all(isinstance(item, str) and item.strip() for item in items)
    ):
        msg = (
            f"{said('catchment')} must be a local authority name or code, a "
            "list of them, or 'England', 'Wales' or 'England and Wales'."
        )
        raise AnalysisInputError(msg, option="catchment")
    cleaned = [item.strip() for item in items]
    whole = cleaned[0].casefold() if len(cleaned) == 1 else ""
    if whole == EVERYWHERE.casefold():
        return tuple(sorted(names)), EVERYWHERE
    if whole in COUNTRIES:
        codes = sorted(code for code in names if code[0] == COUNTRIES[whole])
        return tuple(codes), whole.capitalize()
    by_key = {code.casefold(): code for code in names}
    by_key.update({name.casefold(): code for code, name in names.items()})
    unknown = [item for item in cleaned if item.casefold() not in by_key]
    if unknown:
        msg = (
            f"These entries in {said('catchment')} are not local authorities "
            f"in the {listed_in}: {', '.join(unknown)}. {HOW_TO_NAME_A_PLACE}"
        )
        raise AnalysisInputError(msg, option="catchment")
    chosen = sorted({by_key[item.casefold()] for item in cleaned})
    return tuple(chosen), ", ".join(names[code] for code in chosen)


# --- reading the input -----------------------------------------------------


def count_by_postcode(
    values: list[Any],
    use_table: bool,
    trail: Trail,
    level: Level = NEIGHBOURHOOD,
) -> tuple[Counter[str], int]:
    """Place each row's postcode in an area and count rows per area.

    Args:
        values: The postcode column.
        use_table: Look postcodes up on this machine when True, and with
            postcodes.io when False.
        trail: Where the steps, warnings, sources and choices are recorded.
        level: The size of area to place postcodes in.

    Returns:
        Rows per area code, and the number of rows supplied.
    """
    placed = place_postcodes(values, use_table, trail, level)
    return Counter(code for code in placed if code is not None), len(values)


def place_postcodes(
    values: list[Any],
    use_table: bool,
    trail: Trail,
    level: Level = NEIGHBOURHOOD,
) -> list[str | None]:
    """Place each row's postcode in an area.

    Args:
        values: The postcode column.
        use_table: Look postcodes up on this machine when True, and with
            postcodes.io when False.
        trail: Where the steps, warnings, sources and choices are recorded.
        level: The size of area to place postcodes in.

    Returns:
        One area code per row, in row order. None where the row has no
        postcode, or one that is malformed or not found.
    """
    tidy, blank, malformed = read_postcode_column(values, trail)
    usable = [postcode for postcode in tidy if postcode is not None]
    distinct = sorted(set(usable))
    lookup = _look_up_on_this_machine if use_table else _look_up_online
    found_for, where = lookup(distinct, trail, level)
    placed = [None if postcode is None else found_for[postcode] for postcode in tidy]
    found = sum(1 for code in placed if code is not None)
    not_found = len(usable) - found
    trail.working.append(
        Step(
            title=f"Found the {level.singular} for each postcode",
            detail=(
                f"{len(distinct)} distinct postcodes were looked up {where}. "
                f"{not_found} rows had a postcode that was not found."
            ),
            rows_in=len(usable),
            rows_out=found,
        )
    )
    warn_left_out(blank, malformed, not_found, use_table, trail)
    return placed


def locate_postcodes(values: list[Any], trail: Trail) -> list[Position | None]:
    """Find where each row's postcode is, with postcodes.io.

    The distinct postcodes are sent to postcodes.io, and the trail says so.
    To place them on this machine instead, see
    :func:`uk_open_data.analyses._centres.locate_in_neighbourhoods`.

    Args:
        values: The postcode column.
        trail: Where the steps, warnings, sources and choices are recorded.

    Returns:
        Latitude and longitude per row, in row order. None where the row has
        no postcode, or one that is malformed or not found.
    """
    tidy, blank, malformed = read_postcode_column(values, trail)
    usable = [postcode for postcode in tidy if postcode is not None]
    distinct = sorted(set(usable))
    frame = nw.from_native(lookup_postcodes(distinct), eager_only=True)
    found_for = {
        postcode: None
        if is_blank(latitude) or is_blank(longitude)
        else (float(latitude), float(longitude))
        for postcode, latitude, longitude in zip(
            distinct,
            frame["latitude"].to_list(),
            frame["longitude"].to_list(),
            strict=True,
        )
    }
    trail.sources.append(replace(POSTCODES_IO, used_for="Finding where each site is."))
    trail.sent.append(
        f"{len(distinct)} distinct postcodes were sent to postcodes.io to find "
        "where they are. No other column left this machine."
    )
    trail.choices.append(
        Choice(
            id="postcode_lookup",
            label="How postcodes were placed",
            value="postcodes.io, an online service",
            reason=_online_reason(
                "No postcode table is installed on this machine. To send "
                "nothing, install one with `uk-open-data postcodes download` "
                "and keep the centres of neighbourhoods, or give a latitude "
                "and longitude for each row."
            ),
            option="postcode_lookup",
        )
    )
    placed = [None if postcode is None else found_for[postcode] for postcode in tidy]
    found = sum(1 for position in placed if position is not None)
    not_found = len(usable) - found
    trail.working.append(
        Step(
            title="Found where each postcode is",
            detail=(
                f"{len(distinct)} distinct postcodes were looked up with "
                f"postcodes.io. {not_found} rows had a postcode that was not "
                "found."
            ),
            rows_in=len(usable),
            rows_out=found,
        )
    )
    warn_left_out(blank, malformed, not_found, False, trail)
    return placed


def read_postcode_column(
    values: list[Any], trail: Trail
) -> tuple[list[str | None], int, int]:
    """Tidy the postcode column, and stop when no row can be used.

    Returns:
        The tidied postcode of each row, or None where it has none or one that
        is malformed. Then how many rows were blank, and how many malformed.
    """
    supplied = len(values)
    blank = sum(1 for value in values if is_blank(value))
    tidy = [tidy_postcode(value) for value in values]
    usable = sum(1 for postcode in tidy if postcode is not None)
    malformed = supplied - blank - usable
    trail.working.append(
        Step(
            title="Read the postcode column",
            detail=(
                f"{supplied} rows. {blank} had no postcode and {malformed} "
                "held something that is not shaped like a UK postcode. "
                "Those rows were left out and were not sent anywhere."
            ),
            rows_in=supplied,
            rows_out=usable,
        )
    )
    if not usable:
        msg = (
            "None of the rows holds something shaped like a UK postcode. "
            "Check that the right column was chosen for postcodes."
        )
        raise AnalysisInputError(msg, role="postcode")
    return tidy, blank, malformed


def _look_up_on_this_machine(
    postcodes: list[str], trail: Trail, level: Level
) -> tuple[dict[str, str | None], str]:
    """Look postcodes up in the installed table. Nothing is sent anywhere."""
    try:
        if level == LOCAL_AUTHORITY:
            codes = postcodes_to_local_authority(postcodes)
        else:
            codes = postcodes_to_lsoa(postcodes)
        info = postcode_table_info()
    except PostcodeTableError as error:
        raise AnalysisInputError(str(error)) from error
    edition = str(info["edition"])
    source = ons_postcode_lookup(edition, tuple(info["attribution"]))
    trail.sources.append(replace(source, used_for=_used_for(level)))
    trail.choices.append(
        Choice(
            id="postcode_lookup",
            label="How postcodes were placed",
            value=f"On this machine, from the ONS postcode lookup ({edition})",
            reason="A postcode table is installed, so no postcode was sent out.",
            option="postcode_lookup",
        )
    )
    where = f"on this machine, in the ONS postcode lookup ({edition})"
    return dict(zip(postcodes, codes, strict=True)), where


def _look_up_online(
    postcodes: list[str], trail: Trail, level: Level
) -> tuple[dict[str, str | None], str]:
    """Look postcodes up with postcodes.io, and record that they were sent."""
    looked_up = postcodes_to_geography(postcodes, level.geography_type)
    codes = nw.from_native(looked_up, eager_only=True)["geography_code"].to_list()
    trail.sources.append(replace(POSTCODES_IO, used_for=_used_for(level)))
    trail.sent.append(
        f"{len(postcodes)} distinct postcodes were sent to postcodes.io to find "
        f"their {level.plural}. No other column left this machine."
    )
    trail.choices.append(
        Choice(
            id="postcode_lookup",
            label="How postcodes were placed",
            value="postcodes.io, an online service",
            reason=_online_reason(
                "No postcode table is installed on this machine. Install one "
                "with `uk-open-data postcodes download` to keep postcodes here."
            ),
            option="postcode_lookup",
        )
    )
    found = {
        postcode: None if is_blank(code) else str(code)
        for postcode, code in zip(postcodes, codes, strict=True)
    }
    return found, "with postcodes.io"


def _online_reason(without_a_table: str) -> str:
    """Say why postcodes went to the online service.

    With a table installed, 'auto' would have used it, so the person chose
    the online service.

    Args:
        without_a_table: The reason to give when no table is installed.
    """
    if postcode_table_path() is None:
        return without_a_table
    return CHOSE_ONLINE


def _used_for(level: Level) -> str:
    """Say what a postcode source was used for."""
    return f"Finding the {level.singular} each postcode is in."


def warn_left_out(
    blank: int, malformed: int, not_found: int, use_table: bool, trail: Trail
) -> None:
    """Add a warning for each kind of row that could not be used."""
    if blank:
        trail.warnings.append(f"{plural(blank, 'row')} had no postcode.")
    if malformed:
        trail.warnings.append(
            f"{plural(malformed, 'row')} held something that is not shaped "
            "like a UK postcode."
        )
    if not_found and use_table:
        trail.warnings.append(
            f"{plural(not_found, 'row')} had a postcode that was not found. "
            "It may be mistyped, or outside England and Wales."
        )
    elif not_found:
        trail.warnings.append(
            f"{plural(not_found, 'row')} had a postcode that was not found. "
            "It may be mistyped or no longer in use."
        )


def count_by_neighbourhood(
    codes: list[Any], counts: list[Any], trail: Trail
) -> tuple[Counter[str], int]:
    """Total the counts given for each neighbourhood code.

    Returns:
        People per neighbourhood code, and the number of people supplied.
    """
    totals: Counter[str] = Counter()
    blank = 0
    bad: list[int] = []
    for row, (code, raw) in enumerate(zip(codes, counts, strict=True), start=1):
        count = to_count(raw)
        if is_blank(code):
            blank += 1
        elif count is None:
            bad.append(row)
        else:
            totals[str(code).strip().upper()] += count
    if bad:
        raise AnalysisInputError(bad_counts(bad, NOT_A_COUNT), role="count")
    if blank:
        trail.warnings.append(f"{plural(blank, 'row')} had no neighbourhood code.")
    supplied = sum(totals.values())
    trail.working.append(
        Step(
            title="Read the neighbourhood counts",
            detail=(
                f"{len(codes)} rows covering {len(totals)} neighbourhoods and "
                f"{supplied} people. {blank} rows had no code and were left out."
            ),
            rows_in=len(codes),
            rows_out=len(codes) - blank,
        )
    )
    return totals, supplied


# --- sums ------------------------------------------------------------------


def percent(part: float, whole: float) -> float | None:
    """Return a percentage to one decimal place, or None when there is no whole."""
    return round(100 * part / whole, 1) if whole else None


def before_rounding(part: float, whole: float, per: float = 100) -> float | None:
    """Return a share or a rate as it was before rounding, for a figure's ``exact``.

    Give it only for a figure that is shown. A figure hidden to protect a
    small count has no exact value either.
    """
    return per * part / whole if whole else None
