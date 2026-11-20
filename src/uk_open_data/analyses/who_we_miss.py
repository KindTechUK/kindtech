"""Who we are missing: who do we reach less than their share of the people here?

Takes the group each person a charity helped belongs to (ethnic group or sex),
counts people by group, and sets their shares against the shares of residents
of the charity's area in the 2021 Census. It is the method of the Sobus case
study as a function.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

import narwhals as nw

import uk_open_data
from uk_open_data._kept import kept_file, read_kept, write_kept
from uk_open_data.analyses._answers import AREA, names, number
from uk_open_data.analyses._inputs import is_blank, to_count
from uk_open_data.analyses._labels import LABELS, said
from uk_open_data.analyses._model import (
    Analysis,
    AnalysisInfo,
    AnalysisInput,
    AnalysisInputError,
    AnalysisResult,
    Chart,
    ChartSeries,
    Check,
    Choice,
    Figure,
    InputMode,
    Option,
    OptionChoice,
    Privacy,
    Role,
    Step,
    Table,
)
from uk_open_data.analyses._privacy import SECOND_COUNT_NOTE, cells_to_hide
from uk_open_data.analyses._steps import (
    COUNTRIES,
    EVERYWHERE,
    LOCAL_AUTHORITY,
    NOT_A_COUNT,
    POSTCODE_LOOKUP,
    SUPPRESS_BELOW,
    Trail,
    bad_counts,
    before_rounding,
    named_areas,
    percent,
    place_postcodes,
    read_min_share,
    read_threshold,
    use_postcode_table,
)
from uk_open_data.analyses.sources import nomis_table
from uk_open_data.ons import load_ons

ANALYSIS_ID = "who-we-miss"
ANALYSIS_VERSION = "0.1"
# People matched to no group are left out of every share, so they are shown
# beside the people who were matched.
KEY_FIGURES = ("groups_under_represented", "people_matched", "people_not_matched")
RESIDENTS_FOLDER = "residents"
RESIDENTS_FILE_FORMAT = "kindtech-residents-1"
# Nomis code for a count of people, as opposed to a percentage.
COUNT_MEASURE = 20100
# Below this many people, a gap between shares can easily be chance.
FEW_PEOPLE = 100
# Words that mark a label as "not known", whatever else it says.
NOT_KNOWN = frozenset(
    {
        "unknown",
        "prefer",
        "refused",
        "declined",
        "withheld",
        "missing",
        "stated",
        "recorded",
    }
)


@dataclass(frozen=True)
class _Group:
    """One census group, and the words that mark it in a charity's own labels."""

    key: str
    census_prefix: str
    words: frozenset[str]


@dataclass(frozen=True)
class _Characteristic:
    """Something the census counts residents by."""

    id: str
    label: str
    dataset: str
    dimension: str
    groups: tuple[_Group, ...]
    caveat: str

    @property
    def keys(self) -> tuple[str, ...]:
        """The group names, in census order."""
        return tuple(group.key for group in self.groups)


def _words(text: str) -> frozenset[str]:
    return frozenset(text.split())


# Census 2021 table TS021 lists the five high-level groups in this order.
ETHNIC_GROUP = _Characteristic(
    id="ethnic_group",
    label="Ethnic group",
    dataset="NM_2041_1",
    dimension="c2021_eth_20",
    groups=(
        _Group("Asian", "Asian", _words("asian indian pakistani bangladeshi chinese")),
        _Group("Black", "Black", _words("black african caribbean")),
        _Group("Mixed", "Mixed", _words("mixed multiple dual")),
        _Group("White", "White", _words("white irish gypsy traveller roma")),
        _Group("Other", "Other ethnic group", _words("arab")),
    ),
    caveat=(
        "The five groups are broad. A group that looks well reached can hold "
        "smaller communities that are not."
    ),
)
SEX = _Characteristic(
    id="sex",
    label="Sex",
    dataset="NM_2028_1",
    dimension="c_sex",
    groups=(
        _Group("Female", "Female", _words("f female woman women girl girls")),
        _Group("Male", "Male", _words("m male man men boy boys")),
    ),
    caveat=(
        "The census recorded sex as female or male. People your data "
        "describes differently cannot be set against it and are left out."
    ),
)
CHARACTERISTICS = {item.id: item for item in (ETHNIC_GROUP, SEX)}

INFO = AnalysisInfo(
    id=ANALYSIS_ID,
    title="Who we are missing",
    question="Who do we reach less than their share of the people who live here?",
    summary=(
        "Counts the people you helped by ethnic group or by sex and sets "
        "their shares against the shares of residents of your area in the "
        "2021 Census. It shows which groups you reach less than you would "
        "expect."
    ),
    version=ANALYSIS_VERSION,
    roles=(
        Role(
            name="group",
            description=(
                "The group each person belongs to, in your own words, such as "
                "their ethnic group."
            ),
            example="Black Caribbean",
            # A label can be the same as a census group name, and the result
            # names those groups. It repeats no other label.
            reported=True,
            reported_values=tuple(
                key for item in CHARACTERISTICS.values() for key in item.keys
            ),
        ),
        Role(
            name="postcode",
            description="The home postcode of each person or case, one per row.",
            example="SE13 7VC",
        ),
        Role(
            name="count",
            description="How many people are in the group on that row.",
            example="12",
            amount=True,
        ),
    ),
    input_modes=(
        InputMode(
            name="postcodes",
            description="One row per person, with their group and home postcode.",
            roles=("group", "postcode"),
        ),
        InputMode(
            name="group_counts",
            description="One row per group, with a count of people.",
            roles=("group", "count"),
            aggregated=True,
        ),
        InputMode(
            name="people",
            description="One row per person, with their group and no location.",
            roles=("group",),
        ),
    ),
    options=(
        SUPPRESS_BELOW,
        POSTCODE_LOOKUP,
        Option(
            name="characteristic",
            label=LABELS["characteristic"],
            description="What the column of groups holds.",
            default=ETHNIC_GROUP.id,
            choices=tuple(
                OptionChoice(item.id, item.label) for item in CHARACTERISTICS.values()
            ),
        ),
        Option(
            name="groups",
            label=LABELS["groups"],
            description=(
                "Which census group each of your own labels belongs to, as "
                "your label to census group. Labels left out are matched by "
                "their wording."
            ),
            default=None,
            private=True,
        ),
        Option(
            name="catchment",
            label=LABELS["catchment"],
            description=(
                "The area you serve: a list of local authority names or codes, "
                "or 'England', 'Wales' or 'England and Wales'. With postcodes "
                "it can be left empty, and the analysis uses the local authorities "
                "where most of your people live. Without postcodes it must be "
                "given."
            ),
            default=None,
        ),
        Option(
            name="catchment_min_share",
            label=LABELS["catchment_min_share"],
            description=(
                "When the area you serve is not given, a local authority "
                "joins it if it holds at least this share of the people "
                "located."
            ),
            default=0.05,
        ),
        Option(
            name="under_represented_below",
            label=LABELS["under_represented_below"],
            description=(
                "A group is under-represented when its share of your people "
                "is below this fraction of its share of residents."
            ),
            default=0.8,
        ),
    ),
    coverage=EVERYWHERE,
)

CAVEATS = (
    "A gap is not proof of a barrier. Groups differ in age and in need, so a "
    "service for older people, say, will not match all residents.",
    "Residents are everyone counted in the area on census day, 21 March 2021, "
    "of every age. The make-up of some areas has changed since.",
    "With few people, a gap between two shares can be chance.",
)

CHART = Chart(
    id="people_against_residents",
    title="Your people and the residents of your area, by group",
    table="by_group",
    category_column="group",
    series=(
        ChartSeries("share_of_people", "Your people", "percent"),
        ChartSeries("share_of_residents", "Residents", "percent"),
    ),
)


@dataclass(frozen=True)
class _Residents:
    """Residents by group in every local authority, from the census."""

    names: dict[str, str]
    counts: dict[str, tuple[float, ...]]
    note: str | None = None


@dataclass(frozen=True)
class _Catchment:
    """The area the charity serves, as a set of local authorities."""

    codes: tuple[str, ...]
    label: str
    reason: str


def run(analysis_input: AnalysisInput) -> AnalysisResult:
    """Run the analysis. Use :func:`uk_open_data.analyses.run_analysis` to call it."""
    options = analysis_input.options
    threshold = read_threshold(options)
    cut = _cut(options)
    min_share = read_min_share(options)
    characteristic = _characteristic(options)
    by_hand = _by_hand(options, characteristic)
    trail = Trail()
    residents = _load_residents(characteristic, trail)
    mode = analysis_input.mode.name
    labels = analysis_input.values["group"]
    if mode == "group_counts":
        weights = _weights(analysis_input.values["count"])
    else:
        weights = [1] * len(labels)
    supplied = sum(weights)
    places = None
    if mode == "postcodes":
        places = place_postcodes(
            analysis_input.values["postcode"],
            use_postcode_table(options),
            trail,
            LOCAL_AUTHORITY,
        )
    catchment = _catchment(
        options.get("catchment"), residents, places, weights, min_share
    )
    if places is not None:
        weights = _keep_catchment(places, weights, catchment, trail)
    people, not_matched = _count_groups(
        labels, weights, characteristic, by_hand, threshold, trail
    )
    lived = _residents_of(catchment, residents)
    hide = cells_to_hide(people, threshold)
    rows = _group_rows(characteristic, people, lived, hide, cut)
    trail.hidden += sum(hide)
    trail.working.append(
        Step(
            title="Set your people against residents",
            detail=(
                f"Area: {catchment.label}. {catchment.reason} It had "
                f"{round(sum(lived)):,} residents in the census. For each "
                "group, its share of your people was divided by its share of "
                "residents. A group is under-represented when the result is "
                f"below {cut}."
            ),
        )
    )
    trail.working.append(
        Step(
            title="Hid small counts",
            detail=(
                f"Counts from 1 to {threshold - 1} for a group were hidden, "
                "along with anything that would let them be worked out. "
                f"{trail.hidden} cells were hidden."
            ),
        )
    )
    return AnalysisResult(
        analysis_id=ANALYSIS_ID,
        analysis_version=ANALYSIS_VERSION,
        package_version=uk_open_data.__version__,
        run_on=date.today().isoformat(),
        input_mode=mode,
        figures=tuple(
            _figures(supplied, sum(weights), people, not_matched, lived, rows)
        ),
        tables=(_group_table(rows),),
        map=None,
        working=tuple(trail.working),
        choices=(
            *trail.choices,
            *_choices(characteristic, catchment, cut, threshold),
        ),
        checks=_checks(mode, characteristic, catchment),
        caveats=(*CAVEATS, characteristic.caveat),
        warnings=tuple(trail.warnings),
        sources=tuple(trail.sources),
        privacy=_privacy(threshold, trail),
        charts=(CHART,),
        answer=_answer(rows),
        key_figures=KEY_FIGURES,
    )


# --- options ---------------------------------------------------------------


def _cut(options: dict[str, Any]) -> float:
    """Read and check the fraction below which a group is under-represented."""
    value = options.get("under_represented_below")
    if isinstance(value, bool) or not isinstance(value, int | float):
        msg = f"{said('under_represented_below')} must be a number."
        raise AnalysisInputError(msg, option="under_represented_below")
    if not 0 < value <= 1:
        msg = (
            f"{said('under_represented_below')} must be above 0 and no more "
            "than 1, for example 0.8 for four fifths."
        )
        raise AnalysisInputError(msg, option="under_represented_below")
    return float(value)


def _characteristic(options: dict[str, Any]) -> _Characteristic:
    """Read and check what the group column holds."""
    wanted = options.get("characteristic")
    if not isinstance(wanted, str) or wanted not in CHARACTERISTICS:
        msg = f"{said('characteristic')} must be one of: {', '.join(CHARACTERISTICS)}."
        raise AnalysisInputError(msg, option="characteristic")
    return CHARACTERISTICS[wanted]


def _by_hand(
    options: dict[str, Any], characteristic: _Characteristic
) -> dict[str, str]:
    """Read the labels a person matched to census groups themselves.

    Returns:
        Label, tidied, to census group name.
    """
    given = options.get("groups")
    if given is None:
        return {}
    known = {key.casefold(): key for key in characteristic.keys}
    if not isinstance(given, Mapping) or not all(
        isinstance(label, str) and isinstance(group, str)
        for label, group in given.items()
    ):
        msg = (
            f"{said('groups')} must map each of your labels to one of: "
            f"{', '.join(characteristic.keys)}."
        )
        raise AnalysisInputError(msg, option="groups")
    wrong = sum(1 for group in given.values() if group.strip().casefold() not in known)
    if wrong:
        msg = (
            f"{wrong} entries in {said('groups')} do not name a census "
            f"group. The groups are: {', '.join(characteristic.keys)}."
        )
        raise AnalysisInputError(msg, option="groups")
    return {
        _tidy(label): known[group.strip().casefold()] for label, group in given.items()
    }


# --- residents -------------------------------------------------------------


def _load_residents(characteristic: _Characteristic, trail: Trail) -> _Residents:
    """Load residents by group for every local authority in England and Wales."""
    used_for = f"Residents by {characteristic.label.lower()}, for comparison."
    source = nomis_table(characteristic.dataset, used_for)
    try:
        residents = _read_kept(characteristic)
    except (KeyError, TypeError, ValueError) as error:
        msg = (
            "The census figures kept on this machine could not be read. Fetch "
            "them again with uk_open_data.analyses.who_we_miss.download_residents()."
        )
        raise AnalysisInputError(msg) from error
    if residents is not None:
        source = replace(
            source,
            edition=f"{source.edition}. A copy kept on this machine, {residents.note}",
        )
        where = "A copy kept on this machine was used, so nothing was fetched."
    else:
        try:
            residents = _fetch_residents(characteristic.id)
        except ValueError as error:
            msg = f"The census figures could not be loaded from Nomis. {error}"
            raise AnalysisInputError(msg) from error
        where = "Fetched from Nomis."
    trail.sources.append(source)
    trail.working.append(
        Step(
            title="Loaded the census figures",
            detail=(
                f"Residents by {characteristic.label.lower()} in "
                f"{len(residents.counts)} local authorities in England and "
                f"Wales. From {source.name}. {where}"
            ),
        )
    )
    return residents


@lru_cache(maxsize=8)
def _fetch_residents(characteristic_id: str) -> _Residents:
    """Fetch residents by group from Nomis, once per process.

    The groups are found by the names Nomis gives them, not by code, so the
    figures cannot be put under the wrong name.

    Raises:
        ValueError: If the table has no count by local authority, or does not
            name every group the analysis expects.
    """
    characteristic = CHARACTERISTICS[characteristic_id]
    name_column = f"{characteristic.dimension}_name"
    wanted = ("geography_code", "geography_name", name_column, "obs_value")
    loaded = load_ons(
        characteristic.dataset,
        geography_type="LAD",
        time="latest",
        measures=COUNT_MEASURE,
        select=list(wanted),
    )
    frame = nw.from_native(loaded, eager_only=True)
    if any(name not in frame.columns for name in wanted):
        msg = "The table has no count of each group for each local authority."
        raise ValueError(msg)
    # For each local authority and group: the group's own row when Nomis has
    # one, and the sum of its detailed rows when not.
    own: dict[tuple[str, int], float] = {}
    detailed: Counter[tuple[str, int]] = Counter()
    names: dict[str, str] = {}
    found: set[int] = set()
    columns = [frame[name].to_list() for name in wanted]
    for code, name, category, value in zip(*columns, strict=True):
        key = str(code)
        head, _, rest = str(category).partition(":")
        position = _group_position(characteristic, head)
        if key[:1] not in COUNTRIES.values() or position is None or is_blank(value):
            continue
        names[key] = str(name)
        found.add(position)
        if rest:
            detailed[key, position] += float(value)
        else:
            own[key, position] = float(value)
    if len(found) != len(characteristic.groups):
        msg = "The table does not name every group this analysis compares."
        raise ValueError(msg)
    positions = range(len(characteristic.groups))
    return _Residents(
        names=names,
        counts={
            code: tuple(own.get((code, i), detailed[code, i]) for i in positions)
            for code in names
        },
    )


def _group_position(characteristic: _Characteristic, census_name: str) -> int | None:
    """Return which group a census category name belongs to, or None."""
    tidy = census_name.strip().casefold()
    for position, group in enumerate(characteristic.groups):
        if tidy.startswith(group.census_prefix.casefold()):
            return position
    return None


def _read_kept(characteristic: _Characteristic) -> _Residents | None:
    """Read the census figures kept on this machine, or None when none are."""
    kept = read_kept(RESIDENTS_FOLDER, characteristic.id, RESIDENTS_FILE_FORMAT)
    if kept is None:
        return None
    if kept["groups"] != list(characteristic.keys):
        raise ValueError("wrong groups")
    size = len(characteristic.groups)
    counts = {
        str(code): tuple(float(kept_count) for kept_count in by_group)
        for code, _, by_group in kept["residents"]
    }
    if any(len(by_group) != size for by_group in counts.values()):
        raise ValueError("wrong number of groups")
    return _Residents(
        names={str(code): str(name) for code, name, _ in kept["residents"]},
        counts=counts,
        note=kept["note"],
    )


def residents_path(characteristic: str = ETHNIC_GROUP.id) -> Path | None:
    """Return where census figures are kept on this machine, or None.

    Args:
        characteristic: ``ethnic_group`` or ``sex``.
    """
    path = kept_file(RESIDENTS_FOLDER, characteristic)
    return path if characteristic in CHARACTERISTICS and path.is_file() else None


def keep_residents(
    characteristic: str,
    residents: Iterable[tuple[str, str, Mapping[str, float]]],
    note: str,
) -> Path:
    """Keep residents by group on this machine, so the analysis does not fetch them.

    The analysis reads the copy instead of asking Nomis, so a server or a
    demonstration works without the network. The copy lives in the data folder
    (see :func:`uk_open_data.postcodes.offline.data_dir`).

    Args:
        characteristic: ``ethnic_group`` or ``sex``.
        residents: Local authority code, name, and residents by group, one per
            local authority. The groups are named as the analysis names them, for
            example ``{"Asian": 100, "Black": 80, ...}``.
        note: Where the figures came from, in a few words. It is shown with
            the source in every result that uses the copy.

    Returns:
        The path of the file written.

    Raises:
        ValueError: If the characteristic is unknown, or a local authority
            does not have a count for every group.
    """
    chosen = _known(characteristic)
    rows = []
    for code, name, by_group in residents:
        if set(by_group) != set(chosen.keys):
            msg = f"Every local authority needs a count for: {', '.join(chosen.keys)}."
            raise ValueError(msg)
        rows.append([code, name, [by_group[key] for key in chosen.keys]])
    content = {
        "characteristic": chosen.id,
        "dataset": chosen.dataset,
        "groups": list(chosen.keys),
        "residents": rows,
    }
    return write_kept(RESIDENTS_FOLDER, chosen.id, RESIDENTS_FILE_FORMAT, note, content)


def download_residents(characteristic: str = ETHNIC_GROUP.id) -> Path:
    """Fetch residents by group from Nomis and keep them on this machine.

    Run this once when a server is built. Only public figures are fetched.

    Args:
        characteristic: ``ethnic_group`` or ``sex``.

    Returns:
        The path of the file written.

    Raises:
        ValueError: If the characteristic is unknown, or Nomis does not return
            a count of each group for each local authority.
    """
    chosen = _known(characteristic)
    clear_residents_cache()
    fetched = _fetch_residents(chosen.id)
    content = {
        "characteristic": chosen.id,
        "dataset": chosen.dataset,
        "groups": list(chosen.keys),
        "residents": [
            [code, fetched.names[code], list(counts)]
            for code, counts in fetched.counts.items()
        ],
    }
    note = f"fetched from Nomis on {date.today().isoformat()}."
    return write_kept(RESIDENTS_FOLDER, chosen.id, RESIDENTS_FILE_FORMAT, note, content)


def clear_residents_cache() -> None:
    """Forget the census figures fetched earlier in this process."""
    _fetch_residents.cache_clear()


def _known(characteristic: str) -> _Characteristic:
    """Return a characteristic by its id, or say which ones there are."""
    if characteristic not in CHARACTERISTICS:
        msg = (
            f"No characteristic called '{characteristic}'. Known ones: "
            f"{', '.join(CHARACTERISTICS)}."
        )
        raise ValueError(msg)
    return CHARACTERISTICS[characteristic]


# --- reading the input -----------------------------------------------------


def _weights(counts: list[Any]) -> list[int]:
    """Read the count column, so each row stands for that many people."""
    weights = [to_count(raw) for raw in counts]
    bad = [row for row, weight in enumerate(weights, start=1) if weight is None]
    if bad:
        raise AnalysisInputError(bad_counts(bad, NOT_A_COUNT), role="count")
    return [weight or 0 for weight in weights]


def _tidy(label: Any) -> str:
    """Return a label in lower case with single spaces."""
    return " ".join(str(label).casefold().split())


def _match(label: str, characteristic: _Characteristic) -> str | None:
    """Match one of a charity's own labels to a census group by its wording.

    A label that names two groups, such as "White and Black Caribbean", is
    Mixed. A label that names none is Other when it says "other", and is not
    matched when it does not.
    """
    words = frozenset(re.findall(r"[a-z]+", label))
    if not words or words & NOT_KNOWN:
        return None
    named = [group.key for group in characteristic.groups if words & group.words]
    if len(named) == 1:
        return named[0]
    if characteristic is not ETHNIC_GROUP:
        return None
    if named:
        return "Mixed"
    return "Other" if "other" in words else None


def _count_groups(
    labels: list[Any],
    weights: list[int],
    characteristic: _Characteristic,
    by_hand: dict[str, str],
    threshold: int,
    trail: Trail,
) -> tuple[list[int], int]:
    """Count people by census group.

    Returns:
        People per group in census order, and people whose label matched no
        group.
    """
    per_label: Counter[str] = Counter()
    blank = 0
    for label, weight in zip(labels, weights, strict=True):
        if not weight:
            continue
        if is_blank(label):
            blank += weight
        else:
            per_label[_tidy(label)] += weight
    counts: Counter[str] = Counter()
    not_matched = blank
    set_by_hand = 0
    for label, people in per_label.items():
        group = by_hand.get(label) or _match(label, characteristic)
        set_by_hand += label in by_hand
        if group is None:
            not_matched += people
        else:
            counts[group] += people
    matched = sum(counts.values())
    trail.working.append(
        Step(
            title="Matched your labels to census groups",
            detail=(
                f"{len(per_label)} distinct labels. {set_by_hand} were set in "
                f"{said('groups')} and the rest were matched by their "
                f"wording. {matched} people were matched to a group and "
                f"{not_matched} were not, {blank} of them with no label."
            ),
            rows_in=matched + not_matched,
            rows_out=matched,
        )
    )
    if not_matched:
        trail.warnings.append(
            f"{not_matched} people have no label, or a label that matched no "
            f"census group. They are left out of the shares. Use {said('groups')} "
            "to say which group a label belongs to."
        )
    if matched < threshold:
        msg = _too_few_matched(not_matched, threshold)
        raise AnalysisInputError(msg, role="group")
    if matched < FEW_PEOPLE:
        trail.warnings.append(
            f"Fewer than {FEW_PEOPLE} people were matched to a group. With so "
            "few, a gap between two shares can be chance."
        )
    return [counts[key] for key in characteristic.keys], not_matched


def _too_few_matched(not_matched: int, threshold: int) -> str:
    """Say why too few people were matched: few were given, or few fitted."""
    check = (
        f"Check the column of groups, {said('characteristic')} and {said('groups')}."
    )
    if not_matched < threshold:
        return (
            f"Fewer than {threshold} people could be matched to a census "
            "group, which is too few to give figures that do not point at "
            f"individuals. {check}"
        )
    return (
        f"{not_matched} people have no label, or a label that matched no "
        f"census group, so too few are left to give figures. {check}"
    )


# --- the catchment ---------------------------------------------------------


def _catchment(
    wanted: Any,
    residents: _Residents,
    places: list[str | None] | None,
    weights: list[int],
    min_share: float,
) -> _Catchment:
    """Work out the area served, from the option or from where people live."""
    if wanted is not None:
        codes, label = named_areas(wanted, residents.names, "census figures")
        return _Catchment(codes, label, "You gave the area.")
    if places is None:
        msg = (
            f"Fill in {said('catchment')}: a list of local authority names or "
            "codes, or 'England', 'Wales' or 'England and Wales'. Without "
            "postcodes the analysis cannot work it out."
        )
        raise AnalysisInputError(msg, option="catchment")
    per_authority: Counter[str] = Counter()
    for place, weight in zip(places, weights, strict=True):
        if place in residents.counts:
            per_authority[place] += weight
    total = sum(per_authority.values())
    chosen = sorted(
        code for code, n in per_authority.items() if total and n / total >= min_share
    )
    if not chosen:
        return _Catchment(
            codes=tuple(sorted(residents.counts)),
            label=EVERYWHERE,
            reason=(
                f"No local authority holds as much as {min_share:.0%} of the "
                "people located, so the whole of England and Wales is used."
            ),
        )
    return _Catchment(
        codes=tuple(chosen),
        label=", ".join(residents.names[code] for code in chosen),
        reason=(
            f"Each of these local authorities holds at least {min_share:.0%} "
            "of the people located."
        ),
    )


def _keep_catchment(
    places: list[str | None],
    weights: list[int],
    catchment: _Catchment,
    trail: Trail,
) -> list[int]:
    """Give no weight to people who live outside the catchment."""
    inside = set(catchment.codes)
    kept = [
        weight if place in inside else 0
        for place, weight in zip(places, weights, strict=True)
    ]
    located = sum(1 for place in places if place is not None)
    trail.working.append(
        Step(
            title="Kept the people who live in the area you serve",
            detail=(
                f"{sum(kept)} of the {located} people located live in "
                f"{catchment.label}. The rest are left out, because they are "
                "set against the residents of the area you serve."
            ),
            rows_in=located,
            rows_out=sum(kept),
        )
    )
    if sum(kept) < located:
        trail.warnings.append(
            f"{located - sum(kept)} people live outside the area you serve, "
            "or in a local authority the census figures do not list (for "
            "example one whose boundary has changed), and are left out. "
            f"Change {said('catchment')} to include them."
        )
    return kept


def _residents_of(catchment: _Catchment, residents: _Residents) -> list[float]:
    """Total the catchment's residents by group."""
    if not catchment.codes:
        msg = (
            f"The census figures list no local authority in {catchment.label}. "
            f"Check {said('catchment')}."
        )
        raise AnalysisInputError(msg, option="catchment")
    by_group = zip(*(residents.counts[code] for code in catchment.codes), strict=True)
    return [sum(column) for column in by_group]


# --- the table and figures -------------------------------------------------


def _group_rows(
    characteristic: _Characteristic,
    people: list[int],
    lived: list[float],
    hide: list[bool],
    cut: float,
) -> list[dict[str, Any]]:
    """Build one row per census group."""
    rows = []
    for i, key in enumerate(characteristic.keys):
        share = percent(people[i], sum(people))
        share_of_residents = percent(lived[i], sum(lived))
        ratio = None
        if share is not None and share_of_residents:
            ratio = round(share / share_of_residents, 2)
        rows.append(
            {
                "group": key,
                "people": None if hide[i] else people[i],
                "share_of_people": None if hide[i] else share,
                "residents": round(lived[i]),
                "share_of_residents": share_of_residents,
                "representation": None if hide[i] else ratio,
                "under_represented": (
                    None if hide[i] or ratio is None else ratio < cut
                ),
                "suppressed": hide[i],
            }
        )
    return rows


def _group_table(rows: list[dict[str, Any]]) -> Table:
    """People and residents by census group."""
    return Table(
        id="by_group",
        title="Your people and the residents of your area, by group",
        columns=(
            "group",
            "people",
            "share_of_people",
            "residents",
            "share_of_residents",
            "representation",
            "under_represented",
            "suppressed",
        ),
        rows=rows,
    )


def _figures(
    supplied: int,
    considered: int,
    people: list[int],
    not_matched: int,
    lived: list[float],
    rows: list[dict[str, Any]],
) -> list[Figure]:
    """Build the headline figures."""
    hidden = sum(1 for row in rows if row["suppressed"])
    note = ""
    if hidden:
        note = f"{hidden} groups have a hidden count and are not judged."
    return [
        Figure("people_supplied", "People in the data you gave", supplied, "people"),
        Figure(
            "people_in_catchment",
            "People set against the residents of the area you serve",
            considered,
            "people",
            note=(
                "With postcodes, the people who live in the area you serve. "
                "Without, everyone in your data."
            ),
        ),
        Figure(
            "people_matched",
            "People matched to a census group",
            sum(people),
            "people",
            note="The shares below are of these people.",
        ),
        Figure(
            "people_not_matched",
            "People with no label, or one that matched no census group",
            not_matched,
            "people",
        ),
        Figure(
            "residents",
            "Residents of the area you serve in the 2021 Census",
            round(sum(lived)),
            "people",
        ),
        Figure(
            "groups_under_represented",
            "Groups you reach less than their share of residents",
            sum(1 for row in rows if row["under_represented"]),
            "groups",
            note=note,
        ),
        *_shares_behind_the_answer(people, lived, rows),
    ]


def _shares_behind_the_answer(
    people: list[int], lived: list[float], rows: list[dict[str, Any]]
) -> list[Figure]:
    """Give the two shares the answer quotes, so each has its exact value.

    They are the shares of the first group the answer names. Its count is
    shown, or the group would not be judged, so the exact shares give away
    nothing the table does not.
    """
    under = _under(rows)
    if not under or under[0]["people"] == 0:
        return []
    first = rows.index(under[0])
    group = under[0]["group"]
    return [
        Figure(
            "share_of_people_first_group",
            f"Share of your people in the first of those groups, {group}",
            under[0]["share_of_people"],
            "percent",
            exact=before_rounding(people[first], sum(people)),
        ),
        Figure(
            "share_of_residents_first_group",
            f"Share of residents in that group, {group}",
            under[0]["share_of_residents"],
            "percent",
            exact=before_rounding(lived[first], sum(lived)),
        ),
    ]


# --- what the person needs to know -----------------------------------------


def _answer(rows: list[dict[str, Any]]) -> str:
    """Name the groups reached less than their share of residents."""
    judged = [row for row in rows if row["under_represented"] is not None]
    under = _under(rows)
    against = f"Set against the people who live in {AREA}, you reach"
    hidden = sum(1 for row in rows if row["suppressed"])
    if not judged:
        return (
            f"No group can be set against the people who live in {AREA}: every "
            "count is hidden."
        )
    if not under:
        answer = f"{against} none of the {len(judged)} groups less than its share."
    elif len(under) == 1:
        answer = f"{against} one group less than its share: {under[0]['group']}."
    else:
        answer = (
            f"{against} {len(under)} of the {len(judged)} groups less than their "
            f"share: {names([row['group'] for row in under])}."
        )
    answer += _shares_of_the_first(under) + _groups_with_nobody(under)
    if hidden == 1:
        answer += " One more group has a hidden count and is not judged."
    elif hidden:
        answer += f" {hidden} more groups have a hidden count and are not judged."
    return answer


def _under(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """List the groups reached less than their share, in the answer's order.

    A group with nobody may be one the charity does not record, so the
    groups it does reach come first.
    """
    return sorted(
        (row for row in rows if row["under_represented"]),
        key=lambda row: (row["people"] == 0, row["representation"]),
    )


def _shares_of_the_first(under: list[dict[str, Any]]) -> str:
    """Give the two shares of the first group named, when it has any people."""
    if not under or under[0]["people"] == 0:
        return ""
    first = under[0]
    subject = "It" if len(under) == 1 else f"The first, {first['group']},"
    # The count goes with the share, so a share that rests on a handful of
    # people is not read as a firm finding.
    return (
        f" {subject} is {number(first['people'])} of your people, "
        f"{number(first['share_of_people'])}%, against "
        f"{number(first['share_of_residents'])}% of the people who live there."
    )


def _groups_with_nobody(under: list[dict[str, Any]]) -> str:
    """Say which of the groups named have nobody in the data."""
    nobody = [row["group"] for row in under if row["people"] == 0]
    if not nobody:
        return ""
    if len(under) == 1:
        return " Nobody in your data is recorded in that group."
    return f" Nobody in your data is recorded as {names(nobody, last='or')}."


def _choices(
    characteristic: _Characteristic,
    catchment: _Catchment,
    cut: float,
    threshold: int,
) -> tuple[Choice, ...]:
    """List the choices the analysis made."""
    return (
        Choice(
            id="characteristic",
            label="What people are grouped by",
            value=characteristic.label,
            reason="It is what you chose, or the usual choice if you chose nothing.",
            option="characteristic",
        ),
        Choice(
            id="groups",
            label="Groups compared",
            value=list(characteristic.keys),
            reason=(
                "These are the groups the 2021 Census publishes for every "
                "local authority. Your labels were matched to them by their "
                f"wording, unless {said('groups')} set them."
            ),
            option="groups",
        ),
        Choice(
            id="catchment",
            label=LABELS["catchment"],
            value=catchment.label,
            reason=catchment.reason,
            option="catchment",
        ),
        Choice(
            id="under_represented_below",
            label="What counts as under-represented",
            value=cut,
            reason=(
                "A share of your people below four fifths of the share of "
                "residents is a common first test of a gap."
            ),
            option="under_represented_below",
        ),
        Choice(
            id="suppress_below",
            label="Smallest count shown",
            value=threshold,
            reason="Smaller counts could point at individuals, so they are hidden.",
            option="suppress_below",
        ),
    )


def _checks(
    mode: str, characteristic: _Characteristic, catchment: _Catchment
) -> tuple[Check, ...]:
    """List what a person must confirm before using the figures."""
    if mode == "group_counts":
        first = Check(
            id="counts_are_people",
            question="Does each count stand for people, with nobody counted twice?",
            why="The counts are added up as they are.",
        )
    else:
        first = Check(
            id="one_row_one_person",
            question="Does each row stand for one person?",
            why=(
                "Every row is counted once. If a person appears on several "
                "rows, for example once per visit, they are counted each time."
            ),
        )
    return (
        first,
        Check(
            id="labels_matched",
            question=(
                "Were your labels matched to the right groups: "
                f"{', '.join(characteristic.keys)}?"
            ),
            why=(
                "Labels were matched by their wording, which can be wrong for "
                "codes and short forms. Compare the counts with your own, and "
                f"set any label in {said('groups')}."
            ),
        ),
        Check(
            id="self_described",
            question="Did people describe themselves?",
            why=(
                "The census records what people said about themselves. A "
                "group recorded by staff may not match it."
            ),
        ),
        Check(
            id="catchment",
            question=f"Is this the area you serve: {catchment.label}?",
            why=(
                "Your people are set against everyone who lives in this area. "
                "A different area has a different make-up."
            ),
        ),
        Check(
            id="period",
            question="Does the data cover the period you are reporting on?",
            why="The analysis cannot tell which dates the rows are from.",
        ),
    )


def _privacy(threshold: int, trail: Trail) -> Privacy:
    """Summarise how the result protects people."""
    return Privacy(
        suppress_below=threshold,
        cells_suppressed=trail.hidden,
        row_level_output=False,
        sent_to_third_parties=tuple(trail.sent),
        notes=(
            "A count is hidden when it is small and is about a group.",
            SECOND_COUNT_NOTE,
            "The result names census groups, never the labels in your data.",
            "The number of people matched to no group is shown even when it "
            "is small, because it says nothing about which group they are in.",
            "The census figures are public counts and are shown in full.",
            "A second run with a different area gives a second set of "
            "counts. Publish one, because a small count can be worked out by "
            "taking one from the other.",
        ),
    )


ANALYSIS = Analysis(info=INFO, run=run)
