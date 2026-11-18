"""Need against reach: where is need high and our presence low?

Takes the home postcodes of the people a charity helped (or counts already
totalled by local authority), sets them against a count of people in need in
each local authority of England and Wales, and lists the places where need is
high and the charity reaches few people.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import date
from functools import lru_cache
from pathlib import Path
from statistics import median
from typing import Any

import narwhals as nw

import kindtech
from kindtech.lenses._inputs import is_blank, to_count
from kindtech.lenses._model import (
    Chart,
    ChartSeries,
    Check,
    Choice,
    Figure,
    InputMode,
    Lens,
    LensInfo,
    LensInput,
    LensInputError,
    LensResult,
    MapLayer,
    MapSpec,
    Option,
    Privacy,
    Role,
    Step,
    Table,
)
from kindtech.lenses._privacy import cells_to_hide, group_hidden
from kindtech.lenses._steps import (
    LOCAL_AUTHORITY,
    POSTCODE_LOOKUP,
    SUPPRESS_BELOW,
    Trail,
    count_by_postcode,
    percent,
    read_threshold,
    use_postcode_table,
)
from kindtech.lenses.sources import nomis_table
from kindtech.ons import load_ons
from kindtech.postcodes.offline import data_dir

LENS_ID = "need-reach"
LENS_VERSION = "0.1"
EVERYWHERE = "England and Wales"
COUNTRIES = {"england": "E", "wales": "W"}
DEFAULT_TOP = 10
MAX_TOP = 50
# When people live in fewer than one in this many of the areas compared, the
# lens suggests naming a smaller area.
FEW_AREAS = 10
NEED_BANDS = (
    "Lowest fifth",
    "Second fifth",
    "Middle fifth",
    "Fourth fifth",
    "Highest fifth",
)
NO_REACH = "None, or count hidden"
REACH_BANDS = (NO_REACH, "Lower reach", "Middle reach", "Higher reach")
RESERVED_FILTERS = ("geography", "geography_type", "select")
# Where people go when their local authority is not in the need figures. The
# next step counts them as left out.
UNLISTED = "unlisted"
NEED_FOLDER = "need"
NEED_FILE_FORMAT = "kindtech-need-1"


@dataclass(frozen=True)
class _Measure:
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


def _unemployed(measure_id: str, label: str, sexes: tuple[int, ...]) -> _Measure:
    """Describe an unemployment measure from the 2021 Census."""
    return _Measure(
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


MEASURES = {
    measure.id: measure
    for measure in (
        _unemployed("unemployed", "Unemployed people aged 16 to 64", (1, 2)),
        _unemployed("unemployed_women", "Unemployed women aged 16 to 64", (1,)),
        _unemployed("unemployed_men", "Unemployed men aged 16 to 64", (2,)),
    )
}

INFO = LensInfo(
    id=LENS_ID,
    title="Need against reach",
    question="Where is need high and our presence low?",
    summary=(
        "Counts the people you helped in each local authority and sets them "
        "against the number of people in need there. It lists the places "
        "where need is high and you reach few people."
    ),
    version=LENS_VERSION,
    roles=(
        Role(
            name="postcode",
            description="The home postcode of each person or case, one per row.",
            example="SE13 7VC",
        ),
        Role(
            name="local_authority",
            description=(
                "A local authority, as its name or its code, when the data is "
                "already totalled by local authority."
            ),
            example="Lewisham",
            reported=True,
        ),
        Role(
            name="count",
            description="How many people live in the local authority on that row.",
            example="12",
        ),
    ),
    input_modes=(
        InputMode(
            name="postcodes",
            description="One row per person or case, with a home postcode.",
            roles=("postcode",),
        ),
        InputMode(
            name="area_counts",
            description="One row per local authority, with a count of people.",
            roles=("local_authority", "count"),
            aggregated=True,
        ),
    ),
    options=(
        SUPPRESS_BELOW,
        POSTCODE_LOOKUP,
        Option(
            name="need",
            description=(
                "The need to compare your reach with. One of: "
                f"{', '.join(MEASURES)}. Or a table Nomis publishes by local "
                "authority, as {'dataset': a Nomis dataset id, 'label': what "
                "it counts, 'filters': the categories to add up}."
            ),
            default="unemployed",
        ),
        Option(
            name="catchment",
            description=(
                "The area you could serve: a list of local authority names or "
                "codes, or 'England', 'Wales' or 'England and Wales'. Left "
                "empty, every local authority in England and Wales is compared."
            ),
            default=None,
        ),
        Option(
            name="top",
            description=(
                f"How many high-need, low-reach places to list, from 1 to {MAX_TOP}."
            ),
            default=DEFAULT_TOP,
        ),
    ),
    coverage=EVERYWHERE,
)

CAVEATS = (
    "Low reach is not the same as unmet need. Another organisation may already "
    "serve a place where you reach few people.",
    "Need is a count of people, so a large local authority is more likely to "
    "be listed as high need than a small one with the same rate.",
    "Reach sets the people you helped against everyone counted as in need. "
    "The people you helped may not all be in that group.",
)


CHARTS = (
    Chart(
        id="need_in_priority_areas",
        title="People in need, in the places to look at first",
        table="priority_areas",
        category_column="geography_name",
        series=(ChartSeries("people_in_need", "People in need", "people"),),
    ),
    Chart(
        id="reach_in_priority_areas",
        title="People you reached per 100 in need, in the same places",
        table="priority_areas",
        category_column="geography_name",
        series=(
            ChartSeries(
                "people_per_100_in_need", "People reached per 100 in need", "per_100"
            ),
        ),
        note="No bar is drawn where a count is hidden.",
    ),
)


@dataclass(frozen=True)
class _Authority:
    """One local authority and the people in need there."""

    code: str
    name: str
    need: float


@dataclass(frozen=True)
class _Compared:
    """The local authorities the charity's reach is compared across."""

    codes: tuple[str, ...]
    label: str
    reason: str
    named: bool


@dataclass(frozen=True)
class _Row:
    """One local authority in the comparison."""

    authority: _Authority
    people: int
    high_need: bool
    hidden: bool
    need_band: str
    reach_band: str

    @property
    def reach(self) -> float | None:
        """People per 100 in need, or None when it cannot be shown."""
        if self.hidden:
            return None
        return _per_100(self.people, self.authority.need)


def run(lens_input: LensInput) -> LensResult:
    """Run the lens. Use :func:`kindtech.lenses.run_lens` to call it."""
    options = lens_input.options
    threshold = read_threshold(options)
    top = _top(options)
    measure = _measure(options.get("need"))
    trail = Trail()
    authorities = _load_need(measure, trail)
    if lens_input.mode.name == "postcodes":
        counts, supplied = count_by_postcode(
            lens_input.values["postcode"],
            use_postcode_table(options),
            trail,
            LOCAL_AUTHORITY,
        )
    else:
        counts, supplied = _count_by_authority(
            lens_input.values["local_authority"],
            lens_input.values["count"],
            authorities,
            trail,
        )
    located = _keep_listed(counts, authorities, threshold, trail)
    compared = _choose_compared(options.get("catchment"), authorities)
    rows = _rows(located, authorities, compared, threshold, trail)
    figures = _figures(supplied, sum(located.values()), rows, measure, threshold)
    tables = (_priority_table(rows, top, threshold, trail), _authority_table(rows))
    trail.hidden += sum(row.hidden for row in rows)
    trail.hidden += sum(figure.suppressed for figure in figures)
    trail.working.append(
        Step(
            title="Hid small counts",
            detail=(
                f"Counts from 1 to {threshold - 1} for a named local authority "
                "were hidden, along with anything that would let them be "
                f"worked out. {trail.hidden} cells or figures were hidden."
            ),
        )
    )
    return LensResult(
        lens_id=LENS_ID,
        lens_version=LENS_VERSION,
        package_version=kindtech.__version__,
        run_on=date.today().isoformat(),
        input_mode=lens_input.mode.name,
        figures=tuple(figures),
        tables=tables,
        map=_map_spec(),
        working=tuple(trail.working),
        choices=(*trail.choices, *_choices(measure, compared, top, threshold)),
        checks=_checks(lens_input.mode.name, measure, compared),
        caveats=(*CAVEATS, measure.caveat),
        warnings=tuple(trail.warnings),
        sources=tuple(trail.sources),
        privacy=_privacy(threshold, trail),
        charts=CHARTS,
    )


# --- options ---------------------------------------------------------------


def _top(options: dict[str, Any]) -> int:
    """Read and check how many places to list."""
    value = options.get("top")
    if isinstance(value, bool) or not isinstance(value, int):
        raise LensInputError("The option 'top' must be a whole number.")
    if not 1 <= value <= MAX_TOP:
        raise LensInputError(f"The option 'top' must be from 1 to {MAX_TOP}.")
    return value


def _measure(wanted: Any) -> _Measure:
    """Turn the need option into a measure."""
    if isinstance(wanted, str) and wanted in MEASURES:
        return MEASURES[wanted]
    if isinstance(wanted, Mapping):
        return _custom_measure(wanted)
    msg = (
        f"The option 'need' must be one of: {', '.join(MEASURES)}. Or give a "
        "Nomis table as {'dataset': ..., 'label': ..., 'filters': {...}}."
    )
    raise LensInputError(msg)


def _custom_measure(wanted: Mapping[str, Any]) -> _Measure:
    """Check a need measure that names a Nomis table."""
    dataset = wanted.get("dataset")
    label = wanted.get("label")
    filters = wanted.get("filters", {})
    unknown = sorted(set(wanted) - {"dataset", "label", "filters"})
    problems = []
    if not isinstance(dataset, str) or not dataset.strip():
        problems.append("The option 'need' must give a Nomis 'dataset' id.")
    if not isinstance(label, str) or not label.strip():
        problems.append(
            "The option 'need' must give a 'label' that says what is counted."
        )
    if not isinstance(filters, Mapping) or any(
        not isinstance(name, str) or name.lower() in RESERVED_FILTERS
        for name in filters
    ):
        problems.append(
            "The 'filters' of the option 'need' must be category names and "
            f"codes, and cannot set {', '.join(RESERVED_FILTERS)}."
        )
    if unknown:
        problems.append(
            f"The option 'need' has no entry called {', '.join(unknown)}. It "
            "takes 'dataset', 'label' and 'filters'."
        )
    if problems:
        raise LensInputError(problems)
    return _Measure(
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


# --- need ------------------------------------------------------------------


def _load_need(measure: _Measure, trail: Trail) -> dict[str, _Authority]:
    """Load people in need by local authority, for England and Wales.

    A copy kept on this machine is used when there is one. Otherwise the
    figures are fetched from Nomis.
    """
    source = nomis_table(measure.dataset, f"People in need: {measure.label}.")
    kept = _read_kept(measure.id) if measure.id in MEASURES else None
    if kept is not None:
        rows, note = kept
        source = replace(
            source, edition=f"{source.edition}. A copy kept on this machine, {note}"
        )
        where = "A copy kept on this machine was used, so nothing was fetched."
    else:
        try:
            filters = json.dumps(measure.filters, sort_keys=True)
            rows = _fetch_need(measure.dataset, filters)
        except (TypeError, ValueError) as error:
            msg = f"The need figures could not be loaded from Nomis. {error}"
            raise LensInputError(msg) from error
        where = "Fetched from Nomis."
    if not rows:
        msg = (
            "The need figures list no local authority in England or Wales. "
            "Check the 'need' option."
        )
        raise LensInputError(msg)
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
        code: _Authority(code=code, name=name, need=need) for code, name, need in rows
    }


def _read_kept(need: str) -> tuple[tuple[tuple[str, str, float], ...], str] | None:
    """Read the need figures kept on this machine, with the note that goes with them.

    Returns:
        The figures and a note that says where they came from, or None when no
        copy is kept.
    """
    path = need_figures_path(need)
    if path is None:
        return None
    try:
        kept = json.loads(path.read_text(encoding="utf-8"))
        if kept["format"] != NEED_FILE_FORMAT:
            raise ValueError(kept["format"])
        rows = tuple(
            (str(code), str(name), float(people))
            for code, name, people in kept["figures"]
        )
        return rows, str(kept["note"])
    except (KeyError, TypeError, ValueError) as error:
        msg = (
            "The need figures kept on this machine could not be read. Fetch "
            "them again with kindtech.lenses.need_reach.download_need_figures()."
        )
        raise LensInputError(msg) from error


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
    query: dict[str, Any] = {"time": "latest", **json.loads(filters)}
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
        need: One of the needs the lens has built in, such as ``unemployed``.
    """
    path = data_dir() / NEED_FOLDER / f"{need}.json"
    return path if need in MEASURES and path.is_file() else None


def keep_need_figures(
    need: str,
    figures: Iterable[tuple[str, str, float]],
    note: str,
) -> Path:
    """Keep a need's figures on this machine, so the lens does not fetch them.

    The lens reads the copy instead of asking Nomis, so a server or a
    demonstration works without the network. The copy lives in the data folder
    (see :func:`kindtech.postcodes.offline.data_dir`).

    Args:
        need: One of the needs the lens has built in, such as ``unemployed``.
        figures: Local authority code, name and people in need, one per local
            authority.
        note: Where the figures came from, in a few words. It is shown with
            the source in every result that uses the copy.

    Returns:
        The path of the file written.

    Raises:
        ValueError: If the need is not one the lens has built in.
    """
    if need not in MEASURES:
        msg = f"No need called '{need}'. Known needs: {', '.join(MEASURES)}."
        raise ValueError(msg)
    measure = MEASURES[need]
    kept = {
        "format": NEED_FILE_FORMAT,
        "need": need,
        "label": measure.label,
        "dataset": measure.dataset,
        "note": note,
        "figures": [[code, name, people] for code, name, people in figures],
    }
    path = data_dir() / NEED_FOLDER / f"{need}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(kept, indent=1) + "\n", encoding="utf-8")
    return path


def download_need_figures(need: str = "unemployed") -> Path:
    """Fetch a need's figures from Nomis and keep them on this machine.

    Run this once when a server is built, and again when Nomis publishes new
    figures. Only public figures are fetched.

    Args:
        need: One of the needs the lens has built in, such as ``unemployed``.

    Returns:
        The path of the file written.

    Raises:
        ValueError: If the need is not one the lens has built in, or Nomis
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


# --- reading the input -----------------------------------------------------


def _count_by_authority(
    places: list[Any],
    counts: list[Any],
    authorities: dict[str, _Authority],
    trail: Trail,
) -> tuple[Counter[str], int]:
    """Total the counts given for each local authority name or code."""
    by_key = {code.casefold(): code for code in authorities}
    by_key.update({area.name.casefold(): code for code, area in authorities.items()})
    totals: Counter[str] = Counter()
    blank = bad = unknown = supplied = 0
    for place, raw in zip(places, counts, strict=True):
        count = to_count(raw)
        if is_blank(place):
            blank += 1
        elif count is None:
            bad += 1
        else:
            supplied += count
            code = by_key.get(str(place).strip().casefold())
            unknown += code is None
            totals[code or UNLISTED] += count
    if bad:
        msg = (
            f"{bad} rows have a count that is not a whole number of zero or "
            "more. Correct those rows and run the lens again."
        )
        raise LensInputError(msg)
    if blank:
        trail.warnings.append(f"{blank} rows had no local authority.")
    if unknown:
        trail.warnings.append(
            f"{unknown} rows named a local authority that the need figures do "
            "not list. Use the names or codes that Nomis uses."
        )
    trail.working.append(
        Step(
            title="Read the local authority counts",
            detail=(
                f"{len(places)} rows holding {supplied} people. {blank} rows "
                f"had no local authority and were left out. {unknown} rows "
                "named a place the need figures do not list."
            ),
            rows_in=len(places),
            rows_out=len(places) - blank,
        )
    )
    return totals, supplied


def _keep_listed(
    counts: Counter[str],
    authorities: dict[str, _Authority],
    threshold: int,
    trail: Trail,
) -> dict[str, int]:
    """Keep the people placed in a local authority the need figures list."""
    located = {code: n for code, n in counts.items() if code in authorities and n > 0}
    n_located = sum(located.values())
    total = sum(counts.values())
    outside = total - n_located
    trail.working.append(
        Step(
            title="Joined people to the need figures",
            detail=(
                f"{n_located} people live in a local authority the need "
                f"figures list. {outside} live outside England and Wales, or "
                "in a local authority the figures do not list."
            ),
            rows_in=total,
            rows_out=n_located,
        )
    )
    if outside:
        trail.warnings.append(
            f"{outside} people were placed outside England and Wales, or in a "
            "local authority the need figures do not list (for example one "
            "whose boundary has changed). They are left out."
        )
    if n_located < threshold:
        msg = (
            f"Fewer than {threshold} people could be placed in a local "
            "authority in England or Wales, which is too few to give figures "
            "that do not point at individuals."
        )
        raise LensInputError(msg)
    return located


# --- the comparison --------------------------------------------------------


def _choose_compared(wanted: Any, authorities: dict[str, _Authority]) -> _Compared:
    """Work out which local authorities to compare, from the catchment option."""
    if wanted is None:
        return _Compared(
            codes=tuple(sorted(authorities)),
            label=EVERYWHERE,
            reason=(
                "No catchment was given, so every local authority in England "
                "and Wales is compared."
            ),
            named=False,
        )
    items = [wanted] if isinstance(wanted, str) else wanted
    if not isinstance(items, list | tuple) or not all(
        isinstance(item, str) and item.strip() for item in items
    ):
        msg = (
            "The option 'catchment' must be a local authority name or code, a "
            "list of them, or 'England', 'Wales' or 'England and Wales'."
        )
        raise LensInputError(msg)
    cleaned = [item.strip() for item in items]
    whole = cleaned[0].casefold() if len(cleaned) == 1 else ""
    if whole == EVERYWHERE.casefold():
        return _Compared(
            codes=tuple(sorted(authorities)),
            label=EVERYWHERE,
            reason="You set the catchment.",
            named=True,
        )
    if whole in COUNTRIES:
        return _Compared(
            codes=tuple(
                sorted(code for code in authorities if code[0] == COUNTRIES[whole])
            ),
            label=whole.capitalize(),
            reason="You set the catchment.",
            named=True,
        )
    by_key = {code.casefold(): code for code in authorities}
    by_key.update({area.name.casefold(): code for code, area in authorities.items()})
    unknown = [item for item in cleaned if item.casefold() not in by_key]
    if unknown:
        msg = (
            "These catchment entries are not local authorities in the need "
            f"figures: {', '.join(unknown)}. Use the names or codes that "
            "Nomis uses."
        )
        raise LensInputError(msg)
    chosen = sorted({by_key[item.casefold()] for item in cleaned})
    return _Compared(
        codes=tuple(chosen),
        label=", ".join(authorities[code].name for code in chosen),
        reason="You set the catchment.",
        named=True,
    )


def _rows(
    located: dict[str, int],
    authorities: dict[str, _Authority],
    compared: _Compared,
    threshold: int,
    trail: Trail,
) -> list[_Row]:
    """Build one row per local authority compared, with small counts marked."""
    if not compared.codes:
        msg = (
            f"The need figures list no local authority in {compared.label}. "
            "Check the 'catchment' option."
        )
        raise LensInputError(msg)
    people = [located.get(code, 0) for code in compared.codes]
    need = [authorities[code].need for code in compared.codes]
    n_located = sum(located.values())
    n_inside = sum(people)
    with_people = sum(1 for n in people if n > 0)
    trail.working.append(
        Step(
            title="Set the area to compare",
            detail=(
                f"Area: {compared.label}. {compared.reason} {n_inside} of the "
                f"{n_located} people located live in it, in {with_people} of "
                f"its {len(people)} local authorities."
            ),
            rows_in=n_located,
            rows_out=n_inside,
        )
    )
    if n_inside < threshold:
        msg = (
            f"Fewer than {threshold} of the people located live in the "
            f"catchment ({compared.label}), which is too few to give figures "
            "that do not point at individuals. Check the 'catchment' option."
        )
        raise LensInputError(msg)
    _warn_about_area(n_located - n_inside, with_people, compared, trail)
    cut = median(need)
    high = [amount >= cut and amount > 0 for amount in need]
    # When one small count needs a second count hidden with it, the smallest
    # is taken, wherever it is. The table of places matters more here than the
    # share in high-need places, which is hidden when it would give one away.
    hide = cells_to_hide(people, threshold)
    need_bands = _need_bands(need)
    reach_bands = _reach_bands(people, need, hide)
    trail.working.append(
        Step(
            title="Set reach against need",
            detail=(
                "For each local authority, the people you helped were divided "
                "by the people in need and multiplied by 100. A local "
                "authority is high need when its count of people in need is "
                f"at or above the middle value of the area ({round(cut):,})."
            ),
            rows_in=n_inside,
            rows_out=n_inside,
        )
    )
    return [
        _Row(
            authority=authorities[code],
            people=people[i],
            high_need=high[i],
            hidden=hide[i],
            need_band=need_bands[i],
            reach_band=reach_bands[i],
        )
        for i, code in enumerate(compared.codes)
    ]


def _warn_about_area(
    outside: int, with_people: int, compared: _Compared, trail: Trail
) -> None:
    """Warn when the area compared looks too wide, too narrow or too small."""
    if outside:
        trail.warnings.append(
            f"{outside} people live outside the catchment and are left out. "
            "Change the 'catchment' option to include them."
        )
    if not compared.named and with_people * FEW_AREAS < len(compared.codes):
        trail.warnings.append(
            f"Your people live in {with_people} of the {len(compared.codes)} "
            "local authorities compared. If you serve a smaller area, name it "
            "with the 'catchment' option, so that places you could not reach "
            "are not listed as gaps."
        )
    if len(compared.codes) < len(NEED_BANDS):
        trail.warnings.append(
            f"Only {len(compared.codes)} local authorities are compared, so "
            "'high need' says little. It means at or above the middle value."
        )


def _per_100(people: int, need: float) -> float | None:
    """Return people per 100 in need, or None when nobody is in need."""
    return round(100 * people / need, 2) if need else None


def _equal_parts(values: list[float], parts: int) -> dict[int, int]:
    """Split positions into equal parts by value, lowest first.

    Returns:
        Position in ``values`` to part number, from 0.
    """
    order = sorted(range(len(values)), key=lambda i: (values[i], i))
    return {i: rank * parts // len(order) for rank, i in enumerate(order)}


def _need_bands(need: list[float]) -> list[str]:
    """Put each local authority in a fifth of the area by people in need."""
    part = _equal_parts(need, len(NEED_BANDS))
    return [NEED_BANDS[part[i]] for i in range(len(need))]


def _reach_bands(people: list[int], need: list[float], hide: list[bool]) -> list[str]:
    """Put each local authority with a count that can be shown in a third.

    A local authority with nobody, or with a hidden count, goes in one band, so
    the map does not tell a few people from none.
    """
    shown = [i for i, n in enumerate(people) if n > 0 and not hide[i] and need[i] > 0]
    part = _equal_parts([people[i] / need[i] for i in shown], 3)
    bands = [NO_REACH] * len(people)
    for position, i in enumerate(shown):
        bands[i] = REACH_BANDS[1 + part[position]]
    return bands


# --- tables ----------------------------------------------------------------


def _table_row(row: _Row) -> dict[str, Any]:
    """The columns both tables share."""
    return {
        "geography_code": row.authority.code,
        "geography_name": row.authority.name,
        "people_in_need": round(row.authority.need),
        "people": None if row.hidden else row.people,
        "people_per_100_in_need": row.reach,
        "suppressed": row.hidden,
    }


def _priority_table(rows: list[_Row], top: int, threshold: int, trail: Trail) -> Table:
    """The high-need local authorities with the lowest reach.

    A hidden count is ranked as the largest a hidden small count can be. That
    number comes from the threshold alone, so the order gives nothing away.
    """

    def reach_at_most(row: _Row) -> float:
        people = threshold - 1 if row.hidden else row.people
        return people / row.authority.need

    high = [row for row in rows if row.high_need]
    ranked = sorted(
        high,
        key=lambda row: (reach_at_most(row), -row.authority.need, row.authority.code),
    )[:top]
    trail.working.append(
        Step(
            title="Listed the places with high need and low reach",
            detail=(
                f"The {len(high)} high-need local authorities were put in "
                "order of reach, lowest first, and then by need, highest "
                f"first. The first {len(ranked)} are listed. A hidden count "
                f"is ranked as {threshold - 1} people, the most a hidden small "
                "count can be."
            ),
        )
    )
    if any(row.hidden and row.people >= threshold for row in ranked):
        trail.warnings.append(
            "One count was hidden only to protect another, and its local "
            "authority is ranked as if it had few people. Check the list "
            "against your own records."
        )
    return Table(
        id="priority_areas",
        title="High need and low reach: the places to look at first",
        columns=(
            "rank",
            "geography_code",
            "geography_name",
            "people_in_need",
            "people",
            "people_per_100_in_need",
            "suppressed",
        ),
        rows=[{"rank": rank, **_table_row(row)} for rank, row in enumerate(ranked, 1)],
    )


def _authority_table(rows: list[_Row]) -> Table:
    """Every local authority compared, for the map and for a closer look."""
    return Table(
        id="by_local_authority",
        title="Need and reach in every local authority compared",
        columns=(
            "geography_code",
            "geography_name",
            "people_in_need",
            "need_band",
            "high_need",
            "people",
            "people_per_100_in_need",
            "reach_band",
            "suppressed",
        ),
        rows=[
            {
                **_table_row(row),
                "need_band": row.need_band,
                "high_need": row.high_need,
                "reach_band": row.reach_band,
            }
            for row in rows
        ],
        detail=True,
    )


def _map_spec() -> MapSpec:
    """Describe the map of need and reach."""
    return MapSpec(
        title="Need and reach, by local authority",
        geography_type="LAD",
        geography_year=2023,
        table="by_local_authority",
        code_column="geography_code",
        layers=(
            MapLayer(
                id="need",
                label="People in need",
                value_column="need_band",
                kind="ordinal",
                note="Local authorities in five equal groups by people in need.",
                categories=NEED_BANDS,
            ),
            MapLayer(
                id="reach",
                label="People reached per 100 in need",
                value_column="reach_band",
                kind="ordinal",
                note=(
                    "Local authorities with a count that can be shown are in "
                    "three equal groups. The lowest band holds places with "
                    "nobody and places with a hidden count."
                ),
                categories=REACH_BANDS,
            ),
        ),
    )


# --- figures ---------------------------------------------------------------


def _figures(
    supplied: int,
    located: int,
    rows: list[_Row],
    measure: _Measure,
    threshold: int,
) -> list[Figure]:
    """Build the headline figures."""
    people = [row.people for row in rows]
    need = [row.authority.need for row in rows]
    high = tuple(i for i, row in enumerate(rows) if row.high_need)
    in_catchment = sum(people)
    return [
        Figure("people_supplied", "People in the data you gave", supplied, "people"),
        Figure(
            "people_located",
            "People placed in a local authority in England or Wales",
            located,
            "people",
        ),
        Figure(
            "people_in_catchment",
            "People who live in the area compared",
            in_catchment,
            "people",
            note="The figures below are about these people.",
        ),
        Figure("areas_compared", "Local authorities compared", len(rows), "areas"),
        Figure(
            "people_in_need",
            f"People in need in the area compared: {measure.label}",
            round(sum(need)),
            "people",
        ),
        Figure(
            "reach_per_100_in_need",
            "People you reached per 100 people in need, across the area",
            _per_100(in_catchment, sum(need)),
            "per_100",
        ),
        Figure(
            "high_need_areas",
            "Local authorities with high need",
            len(high),
            "areas",
            note="At or above the middle value of people in need.",
        ),
        Figure(
            "high_need_areas_without_people",
            "High-need local authorities where you reached nobody",
            sum(1 for i in high if people[i] == 0),
            "areas",
        ),
        _share_in_high_need(rows, high, threshold),
        Figure(
            "share_of_need_in_high_need_areas",
            "Share of people in need who live in high-need local authorities",
            percent(sum(need[i] for i in high), sum(need)),
            "percent",
            note="The comparison for the share of your people.",
        ),
    ]


def _share_in_high_need(
    rows: list[_Row], high: tuple[int, ...], threshold: int
) -> Figure:
    """The share of people in high-need places, hidden when it gives a cell away."""
    figure_id = "share_of_people_in_high_need_areas"
    label = "Share of your people who live in high-need local authorities"
    people = [row.people for row in rows]
    hide = [row.hidden for row in rows]
    if group_hidden(people, hide, high, threshold):
        return Figure(
            figure_id,
            label,
            None,
            "percent",
            note="Hidden to protect a small count.",
            suppressed=True,
        )
    part = sum(people[i] for i in high)
    return Figure(figure_id, label, percent(part, sum(people)), "percent")


# --- what the person needs to know -----------------------------------------


def _choices(
    measure: _Measure, compared: _Compared, top: int, threshold: int
) -> tuple[Choice, ...]:
    """List the choices the lens made."""
    return (
        Choice(
            id="need",
            label="Measure of need",
            value=measure.label,
            reason=measure.reason,
            option="need",
        ),
        Choice(
            id="high_need",
            label="What counts as high need",
            value="At or above the middle value of people in need, in the area",
            reason="It splits the area in half, as the Smart Works study did.",
        ),
        Choice(
            id="catchment",
            label="Area compared",
            value=compared.label,
            reason=compared.reason,
            option="catchment",
        ),
        Choice(
            id="top",
            label="Places listed",
            value=top,
            reason="A short list is easier to act on.",
            option="top",
        ),
        Choice(
            id="suppress_below",
            label="Smallest count shown",
            value=threshold,
            reason="Smaller counts could point at individuals, so they are hidden.",
            option="suppress_below",
        ),
    )


def _checks(mode: str, measure: _Measure, compared: _Compared) -> tuple[Check, ...]:
    """List what a person must confirm before using the figures."""
    if mode == "postcodes":
        first = Check(
            id="one_row_one_person",
            question="Does each row stand for one person?",
            why=(
                "Every row is counted once. If a person appears on several "
                "rows, for example once per visit, they are counted each time."
            ),
        )
    else:
        first = Check(
            id="counts_are_people",
            question="Does each count stand for people, with nobody counted twice?",
            why="The counts are added up as they are.",
        )
    return (
        first,
        Check(
            id="home_location",
            question="Is the location where each person lives?",
            why=(
                "Need is counted where people live. A postcode for a service, "
                "school or hostel would put people in the wrong place."
            ),
        ),
        Check(
            id="period",
            question="Does the data cover the period you are reporting on?",
            why="The lens cannot tell which dates the rows are from.",
        ),
        Check(
            id="need_fits",
            question=f"Is this the need you work on: {measure.label}?",
            why=(
                "Reach is only meaningful against the people you are trying "
                "to help. Change the 'need' option if another measure fits "
                "better."
            ),
        ),
        Check(
            id="catchment",
            question=f"Is this the area you could serve: {compared.label}?",
            why=(
                "A place you could never reach is not a gap. Name the area "
                "with the 'catchment' option."
            ),
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
            "A count is hidden when it is small and is about a named local authority.",
            "The map shows reach in bands, and the lowest band holds places "
            "with nobody and places with a hidden count.",
            "The need figures are public counts and are shown in full.",
        ),
    )


LENS = Lens(info=INFO, run=run)
