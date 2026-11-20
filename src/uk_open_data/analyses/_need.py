"""People in need by local authority, shared by the analyses that compare places.

The need figures come from Nomis, are held in memory once fetched, and can be
kept as a file on this machine. The helpers here also choose the local
authorities an analysis compares and put them in bands by need.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

import narwhals as nw

from uk_open_data._kept import kept_file, read_kept, write_kept
from uk_open_data.analyses._inputs import is_blank
from uk_open_data.analyses._labels import LABELS, said
from uk_open_data.analyses._model import AnalysisInputError, Source, Step
from uk_open_data.analyses._steps import (
    COUNTRIES,
    EVERYWHERE,
    HOW_TO_NAME_A_PLACE,
    Trail,
    named_areas,
    plural,
    where_rows,
)
from uk_open_data.analyses.sources import nomis_table
from uk_open_data.ons import load_ons

DEFAULT_TOP = 10
MAX_TOP = 50
# When people live in fewer than one in this many of the areas compared, the
# analysis suggests naming a smaller area.
FEW_AREAS = 10
# One local authority in this many is high need: the top quarter.
HIGH_NEED_ONE_IN = 4
NEED_BANDS = (
    "Lowest fifth",
    "Second fifth",
    "Middle fifth",
    "Fourth fifth",
    "Highest fifth",
)
RESERVED_FILTERS = ("geography", "geography_type", "select")
# The Nomis code for a count, as opposed to a percentage.
COUNT_MEASURE = 20100
NEED_FOLDER = "need"
NEED_FILE_FORMAT = "kindtech-need-1"
# Figures by local authority: code, name and a count of people.
_Rows = tuple[tuple[str, str, float], ...]


@dataclass(frozen=True)
class Measure:
    """A count of people in need that Nomis publishes by local authority."""

    id: str
    label: str
    dataset: str
    filters: Mapping[str, Any]
    reason: str
    caveat: str


# Census 2021 table RM024, economic activity status by sex by age. Status 2 is
# unemployed people who are not full-time students. Full-time students who
# were looking for work are status 4 and are not counted. Sex 1 is female and
# 2 is male. Ages 2 to 5 are the bands from 16 to 64.
_RM024 = "NM_2124_1"
_WORKING_AGE = (2, 3, 4, 5)
_NOT_STUDENTS = "not counting full-time students"


def _unemployed(measure_id: str, label: str, sexes: tuple[int, ...]) -> Measure:
    """Describe an unemployment measure from the 2021 Census."""
    return Measure(
        id=measure_id,
        label=f"{label}, {_NOT_STUDENTS}",
        dataset=_RM024,
        filters={
            "c2021_eastat_7": 2,
            "c_sex": list(sexes),
            "c2021_age_7": list(_WORKING_AGE),
        },
        reason="The census counts every local authority, with nothing hidden.",
        caveat=(
            "The need figures describe census day, 21 March 2021. Unemployment "
            "was affected by the pandemic then and has changed since. Full-time "
            "students who were looking for work are not counted."
        ),
    )


# Census 2021 table TS008, sex. Sex 0 is everyone.
RESIDENTS = Measure(
    id="residents",
    label="Residents of every age",
    dataset="NM_2028_1",
    filters={"c_sex": 0},
    reason="The census counts every local authority, with nothing hidden.",
    caveat=(
        "The residents are everyone counted on census day, 21 March 2021, of "
        "every age. Not all of them need what you offer."
    ),
)

MEASURES = {
    measure.id: measure
    for measure in (
        _unemployed("unemployed", "Unemployed people aged 16 to 64", (1, 2)),
        _unemployed("unemployed_women", "Unemployed women aged 16 to 64", (1,)),
        _unemployed("unemployed_men", "Unemployed men aged 16 to 64", (2,)),
        RESIDENTS,
    )
}


@dataclass(frozen=True)
class Authority:
    """One local authority and the people in need there."""

    code: str
    name: str
    need: float


@dataclass(frozen=True)
class Compared:
    """The local authorities the charity's reach is compared across."""

    codes: tuple[str, ...]
    label: str
    reason: str
    named: bool
    # True when the area was worked out from where the people live.
    guessed: bool = False


# --- options ---------------------------------------------------------------


def read_top(options: dict[str, Any]) -> int:
    """Read and check how many places to list."""
    value = options.get("top")
    if isinstance(value, bool) or not isinstance(value, int):
        msg = f"{said('top')} must be a whole number."
        raise AnalysisInputError(msg, option="top")
    if not 1 <= value <= MAX_TOP:
        msg = f"{said('top')} must be from 1 to {MAX_TOP}."
        raise AnalysisInputError(msg, option="top")
    return value


def read_measure(wanted: Any) -> Measure:
    """Turn the need option into a measure."""
    if isinstance(wanted, str) and wanted in MEASURES:
        return MEASURES[wanted]
    if isinstance(wanted, Mapping):
        return _custom_measure(wanted)
    msg = (
        f"{said('need')} must be one of: {', '.join(MEASURES)}. Or give a "
        "Nomis table as {'dataset': ..., 'label': ..., 'filters': {...}}."
    )
    raise AnalysisInputError(msg, option="need")


def _custom_measure(wanted: Mapping[str, Any]) -> Measure:
    """Check a need measure that names a Nomis table."""
    dataset = wanted.get("dataset")
    label = wanted.get("label")
    filters = wanted.get("filters", {})
    unknown = sorted(set(wanted) - {"dataset", "label", "filters"})
    problems = []
    if not isinstance(dataset, str) or not dataset.strip():
        problems.append(f"{said('need')} must give a Nomis 'dataset' id.")
    if not isinstance(label, str) or not label.strip():
        problems.append(
            f"{said('need')} must give a 'label' that says what is counted."
        )
    if not isinstance(filters, Mapping) or any(
        not isinstance(name, str) or name.lower() in RESERVED_FILTERS
        for name in filters
    ):
        problems.append(
            f"The 'filters' of {said('need')} must be category names and "
            f"codes, and cannot set {', '.join(RESERVED_FILTERS)}."
        )
    if unknown:
        problems.append(
            f"{said('need')} has no entry called {', '.join(unknown)}. It "
            "takes 'dataset', 'label' and 'filters'."
        )
    if problems:
        raise AnalysisInputError(problems, option="need")
    return Measure(
        id="custom",
        label=str(label).strip(),
        dataset=str(dataset).strip(),
        filters=dict(filters),
        reason="You chose this table.",
        caveat=(
            "The need figures are the latest that Nomis holds for the table "
            "you chose. Check that their date suits your data."
        ),
    )


def not_listed_rows(positions: list[int]) -> str:
    """Say which rows name a local authority that the need figures do not list."""
    return (
        f"{plural(len(positions), 'row')} named a local authority that the "
        f"need figures do not list: {where_rows(positions)}. "
        f"{HOW_TO_NAME_A_PLACE}"
    )


# --- need figures ----------------------------------------------------------


def load_need(measure: Measure, trail: Trail) -> dict[str, Authority]:
    """Load people in need by local authority, for England and Wales.

    A copy kept on this machine is used when there is one. Otherwise the
    figures are fetched from Nomis.
    """
    source = nomis_table(measure.dataset, f"{LABELS['need']}: {measure.label}.")
    kept = _read_kept(measure.id) if measure.id in MEASURES else None
    rows, source, where = _kept_or_fetched(measure, source, kept)
    if not rows:
        msg = (
            "The need figures list no local authority in England or Wales. "
            f"Check {said('need')}."
        )
        raise AnalysisInputError(msg, option="need")
    trail.sources.append(source)
    trail.working.append(
        Step(
            title="Loaded the need figures",
            detail=(
                f"{measure.label}: {round(sum(need for _, _, need in rows)):,} "
                f"people in {len(rows)} local authorities in England and "
                f"Wales. From {source.name}. {where}"
            ),
        )
    )
    return {
        code: Authority(code=code, name=name, need=need) for code, name, need in rows
    }


def load_residents(trail: Trail, fetch: bool) -> dict[str, float] | None:
    """Load residents by local authority, to turn a count of need into a rate.

    A copy kept on this machine is used when there is one. Otherwise the
    residents are fetched from Nomis when ``fetch`` is true. When it is not,
    None is returned, so a run that was kept off the network stays off it.

    Returns:
        Residents by local authority code, or None when there are none to use.
    """
    kept = _read_kept(RESIDENTS.id)
    if kept is None and not fetch:
        return None
    source = nomis_table(RESIDENTS.dataset, "Residents, to set people in need against.")
    rows, source, where = _kept_or_fetched(RESIDENTS, source, kept)
    trail.sources.append(source)
    trail.working.append(
        Step(
            title="Loaded the residents",
            detail=(
                f"{round(sum(people for _, _, people in rows)):,} residents in "
                f"{len(rows)} local authorities, to turn people in need into a "
                f"rate for the map. From {source.name}. {where}"
            ),
        )
    )
    return {code: people for code, _, people in rows}


def _kept_or_fetched(
    measure: Measure, source: Source, kept: tuple[_Rows, str] | None
) -> tuple[_Rows, Source, str]:
    """Take the figures from a kept copy, or fetch them from Nomis.

    Returns:
        The figures, the source as it should be cited, and a sentence that
        says where the figures came from.
    """
    if kept is not None:
        rows, note = kept
        cited = replace(
            source, edition=f"{source.edition}. A copy kept on this machine, {note}"
        )
        return (
            rows,
            cited,
            "A copy kept on this machine was used, so nothing was fetched.",
        )
    try:
        rows = _fetch_need(measure.dataset, json.dumps(measure.filters, sort_keys=True))
    except (TypeError, ValueError) as error:
        msg = f"The need figures could not be loaded from Nomis. {error}"
        raise AnalysisInputError(msg) from error
    return rows, source, "Fetched from Nomis."


def need_per_1000(
    codes: Sequence[str],
    authorities: dict[str, Authority],
    residents: dict[str, float] | None,
) -> list[float] | None:
    """People in need for each 1,000 residents, in the order of ``codes``.

    Returns:
        None when residents are not known for every place, so a map is never
        shaded by a mix of rates and counts.
    """
    if residents is None or any(not residents.get(code) for code in codes):
        return None
    return [round(1000 * authorities[code].need / residents[code], 1) for code in codes]


def _read_kept(need: str) -> tuple[_Rows, str] | None:
    """Read the need figures kept on this machine, with the note that goes with them.

    Returns:
        The figures and a note that says where they came from, or None when no
        copy is kept.
    """
    try:
        kept = read_kept(NEED_FOLDER, need, NEED_FILE_FORMAT)
        if kept is None:
            return None
        rows = tuple(
            (str(code), str(name), float(people))
            for code, name, people in kept["figures"]
        )
        return rows, kept["note"]
    except (KeyError, TypeError, ValueError) as error:
        msg = (
            "The need figures kept on this machine could not be read. Fetch "
            "them again with uk_open_data.analyses.need_reach.download_need_figures()."
        )
        raise AnalysisInputError(msg) from error


@lru_cache(maxsize=32)
def _fetch_need(dataset: str, filters: str) -> tuple[tuple[str, str, float], ...]:
    """Fetch one need measure from Nomis, once per process.

    Args:
        dataset: The Nomis dataset id.
        filters: The category filters, as JSON text so they can be a cache key.

    Returns:
        Local authority code, name and people in need, for England and Wales.

    Raises:
        ValueError: If Nomis has no such table, or it has no count by local
            authority.
    """
    # Nomis gives every measure of a table unless one is named, and some
    # tables hold a percentage beside each count. The analysis adds the rows up,
    # so it asks for counts alone, unless the filters name another measure.
    query: dict[str, Any] = {
        "time": "latest",
        "measures": COUNT_MEASURE,
        **json.loads(filters),
    }
    loaded = load_ons(
        dataset,
        geography_type="LAD",
        select=["geography_code", "geography_name", "obs_value"],
        **query,
    )
    frame = nw.from_native(loaded, eager_only=True)
    wanted = ("geography_code", "geography_name", "obs_value")
    if any(name not in frame.columns for name in wanted):
        msg = "The table has no count for each local authority."
        raise ValueError(msg)
    totals: dict[str, float] = {}
    names: dict[str, str] = {}
    columns = [frame[name].to_list() for name in wanted]
    for code, name, value in zip(*columns, strict=True):
        key = str(code)
        if key[:1] not in COUNTRIES.values() or is_blank(value):
            continue
        totals[key] = totals.get(key, 0.0) + float(value)
        names[key] = str(name)
    return tuple((code, names[code], need) for code, need in totals.items())


def need_figures_path(need: str = "unemployed") -> Path | None:
    """Return where a need's figures are kept on this machine, or None.

    Args:
        need: One of the needs the analysis has built in, such as ``unemployed``.
    """
    path = kept_file(NEED_FOLDER, need)
    return path if need in MEASURES and path.is_file() else None


def keep_need_figures(
    need: str,
    figures: Iterable[tuple[str, str, float]],
    note: str,
) -> Path:
    """Keep a need's figures on this machine, so the analysis does not fetch them.

    The analysis reads the copy instead of asking Nomis, so a server or a
    demonstration works without the network. The copy lives in the data folder
    (see :func:`uk_open_data.postcodes.offline.data_dir`).

    Args:
        need: One of the needs the analysis has built in, such as ``unemployed``.
        figures: Local authority code, name and people in need, one per local
            authority.
        note: Where the figures came from, in a few words. It is shown with
            the source in every result that uses the copy.

    Returns:
        The path of the file written.

    Raises:
        ValueError: If the need is not one the analysis has built in.
    """
    if need not in MEASURES:
        msg = f"No need called '{need}'. Known needs: {', '.join(MEASURES)}."
        raise ValueError(msg)
    measure = MEASURES[need]
    content = {
        "need": need,
        "label": measure.label,
        "dataset": measure.dataset,
        "figures": [[code, name, people] for code, name, people in figures],
    }
    return write_kept(NEED_FOLDER, need, NEED_FILE_FORMAT, note, content)


def download_need_figures(need: str = "unemployed") -> Path:
    """Fetch a need's figures from Nomis and keep them on this machine.

    Run this once when a server is built, and again when Nomis publishes new
    figures. Only public figures are fetched.

    Args:
        need: One of the needs the analysis has built in, such as ``unemployed``.

    Returns:
        The path of the file written.

    Raises:
        ValueError: If the need is not one the analysis has built in, or Nomis
            does not return a count for each local authority.
    """
    if need not in MEASURES:
        msg = f"No need called '{need}'. Known needs: {', '.join(MEASURES)}."
        raise ValueError(msg)
    measure = MEASURES[need]
    clear_need_cache()
    rows = _fetch_need(measure.dataset, json.dumps(measure.filters, sort_keys=True))
    note = f"fetched from Nomis on {date.today().isoformat()}."
    return keep_need_figures(need, rows, note)


def clear_need_cache() -> None:
    """Forget the need figures fetched earlier in this process.

    Need figures are fetched from Nomis once for each need and then kept in
    memory, so a server answers later runs without the network. Call this to
    fetch them again.
    """
    _fetch_need.cache_clear()


# --- the area compared -----------------------------------------------------


def choose_compared(wanted: Any, authorities: dict[str, Authority]) -> Compared:
    """Work out which local authorities to compare, from the area given."""
    if wanted is None:
        return Compared(
            codes=tuple(sorted(authorities)),
            label=EVERYWHERE,
            reason=(
                "No area was given, so every local authority in England and "
                "Wales is compared."
            ),
            named=False,
        )
    names = {code: area.name for code, area in authorities.items()}
    codes, label = named_areas(wanted, names, "need figures")
    return Compared(codes=codes, label=label, reason="You gave the area.", named=True)


def guess_compared(
    located: dict[str, int], authorities: dict[str, Authority], min_share: float
) -> Compared:
    """Take the area served to be the local authorities where most people live.

    A local authority joins the area when it holds at least ``min_share`` of
    the people located. When none does, every local authority is compared.
    """
    total = sum(located.values())
    chosen = [
        code
        for code, n in sorted(located.items(), key=lambda item: (-item[1], item[0]))
        if total and n / total >= min_share
    ]
    if not chosen:
        return Compared(
            codes=tuple(sorted(authorities)),
            label=EVERYWHERE,
            reason=(
                f"No local authority holds as much as {min_share:.0%} of the "
                "people located, so every local authority in England and "
                "Wales is compared."
            ),
            named=False,
        )
    return Compared(
        codes=tuple(sorted(chosen)),
        label=", ".join(authorities[code].name for code in chosen),
        reason=(
            f"Each of these local authorities holds at least {min_share:.0%} "
            "of the people located."
        ),
        named=False,
        guessed=True,
    )


def high_need_cut(need: list[float]) -> float:
    """Return the count at or above which a local authority is high need.

    High need is the top quarter of the places compared, and at least one
    place. With ``n`` places the cut is the count of the place ranked
    ``n / 4`` from the top, rounded up, so places that tie with it are high
    need too.
    """
    places = -(-len(need) // HIGH_NEED_ONE_IN)
    return sorted(need, reverse=True)[places - 1]


# Said in a map's note, because a key lists every group whatever the map has.
FEW_PLACES = (
    " With fewer places than groups, the lowest place is in the lowest group "
    "and the highest in the highest."
)
ONE_PLACE = " One place alone is in the middle group."


def few_places(places: int, parts: int) -> str:
    """The words a map's note needs when it has fewer places than groups.

    Nothing is said of a map with a place for every group, where the words
    would only puzzle a reader.
    """
    if places == 1:
        return ONE_PLACE
    return FEW_PLACES if 1 < places < parts else ""


def equal_parts(values: list[float], parts: int) -> dict[int, int]:
    """Split positions into equal parts by value, lowest first.

    With fewer values than parts, each value is a part of its own, spread
    from the lowest part to the highest. So the highest value is in the top
    part, and a key that runs from low to high is true of the map. One value
    alone goes in the middle part: there is nothing to set it against.

    Returns:
        Position in ``values`` to part number, from 0.
    """
    order = sorted(range(len(values)), key=lambda i: (values[i], i))
    if len(order) == 1:
        return {order[0]: parts // 2}
    if len(order) < parts:
        last = len(order) - 1
        return {i: round(rank * (parts - 1) / last) for rank, i in enumerate(order)}
    return {i: rank * parts // len(order) for rank, i in enumerate(order)}


def band_by_need(need: list[float]) -> list[str]:
    """Put each local authority in a fifth of the area by people in need."""
    part = equal_parts(need, len(NEED_BANDS))
    return [NEED_BANDS[part[i]] for i in range(len(need))]


def few_in_need_bands(places: int) -> str:
    """What the note of a map shaded by :func:`band_by_need` says of few places."""
    return few_places(places, len(NEED_BANDS))
