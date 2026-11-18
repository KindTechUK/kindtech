"""Reach against deprivation: are we reaching the most deprived neighbourhoods?

Takes the postcodes of the people a charity helped (or counts already totalled
by neighbourhood), places each in a 2021 Lower layer Super Output Area, and sets
the result against the English Indices of Deprivation 2025.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date
from typing import Any

import narwhals as nw

import kindtech
from kindtech.imd import load_imd
from kindtech.lenses._inputs import is_blank
from kindtech.lenses._model import (
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
from kindtech.lenses._privacy import (
    band_labels,
    cells_to_hide,
    count_band,
    group_hidden,
)
from kindtech.lenses._registry import register_lens
from kindtech.lenses._steps import (
    POSTCODE_LOOKUP,
    SUPPRESS_BELOW,
    Trail,
    count_by_neighbourhood,
    count_by_postcode,
    percent,
    read_threshold,
    use_postcode_table,
)
from kindtech.lenses.sources import IOD_2025

LENS_ID = "reach-deprivation"
LENS_VERSION = "0.1"
DECILES = tuple(range(1, 11))
MOST_DEPRIVED = (0, 1)  # positions of deciles 1 and 2
ELSEWHERE = tuple(range(2, 10))  # positions of deciles 3 to 10
ENGLAND = "England"

INFO = LensInfo(
    id=LENS_ID,
    title="Reach against deprivation",
    question="Are we reaching people in the most deprived neighbourhoods?",
    summary=(
        "Places the people you helped in their neighbourhoods and shows how "
        "many live in the most deprived parts of England. It also compares "
        "your reach in the most deprived neighbourhoods of your area with your "
        "reach in the rest of it."
    ),
    version=LENS_VERSION,
    roles=(
        Role(
            name="postcode",
            description="The home postcode of each person or case, one per row.",
            example="SE13 7VC",
        ),
        Role(
            name="lsoa_code",
            description=(
                "A 2021 Lower layer Super Output Area code, when the data is "
                "already totalled by neighbourhood."
            ),
            example="E01003189",
        ),
        Role(
            name="count",
            description="How many people live in the neighbourhood on that row.",
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
            name="neighbourhood_counts",
            description="One row per neighbourhood, with a count of people.",
            roles=("lsoa_code", "count"),
            aggregated=True,
        ),
    ),
    options=(
        SUPPRESS_BELOW,
        POSTCODE_LOOKUP,
        Option(
            name="catchment",
            description=(
                "The area you serve: a list of local authority names or codes, "
                "or 'England'. Left empty, the lens uses the local authorities "
                "where most of your people live."
            ),
            default=None,
        ),
        Option(
            name="catchment_min_share",
            description=(
                "When the catchment is not given, a local authority joins it "
                "if it holds at least this share of the people located."
            ),
            default=0.05,
        ),
    ),
    coverage="England",
)

CAVEATS = (
    "Deprivation is measured for neighbourhoods, not people. Someone who lives "
    "in a deprived neighbourhood is not necessarily deprived, and the reverse.",
    "Deciles rank neighbourhoods within England only. They cannot be compared "
    "with the indices for Wales, Scotland or Northern Ireland.",
    "Reach per 1,000 uses all residents of all ages. If you serve one group, "
    "such as older people, the true reach among that group is higher.",
)


@dataclass(frozen=True)
class _Area:
    """One neighbourhood from the deprivation index."""

    code: str
    name: str
    lad_code: str
    lad_name: str
    decile: int
    residents: float


@dataclass(frozen=True)
class _Catchment:
    """The area the charity serves, as a set of local authorities."""

    lad_codes: frozenset[str]
    names: tuple[str, ...]
    reason: str
    whole_country: bool = False

    @property
    def label(self) -> str:
        """The catchment in words."""
        return ENGLAND if self.whole_country else ", ".join(self.names)


def run(lens_input: LensInput) -> LensResult:
    """Run the lens. Use :func:`kindtech.lenses.run_lens` to call it."""
    threshold = read_threshold(lens_input.options)
    min_share = _min_share(lens_input.options)
    trail = Trail()
    if lens_input.mode.name == "postcodes":
        counts, supplied = count_by_postcode(
            lens_input.values["postcode"],
            use_postcode_table(lens_input.options),
            trail,
        )
    else:
        counts, supplied = count_by_neighbourhood(
            lens_input.values["lsoa_code"], lens_input.values["count"], trail
        )
    areas = _load_areas()
    trail.sources.append(IOD_2025)
    located = _keep_english(counts, areas, threshold, trail)
    catchment = _choose_catchment(
        located, areas, lens_input.options.get("catchment"), min_share
    )
    in_catchment = _keep_catchment(located, areas, catchment, threshold, trail)

    people = _by_decile(in_catchment, areas)
    residents = _residents_by_decile(areas, catchment)
    hide = cells_to_hide(people, threshold, groups=(MOST_DEPRIVED, ELSEWHERE))
    tables = [
        _decile_table(people, residents, hide, trail),
        _authority_table(located, areas, catchment, threshold, trail),
    ]
    map_spec = None
    if catchment.whole_country:
        trail.warnings.append(
            "No map was made because the catchment is the whole of England. "
            "Name the local authorities you serve to get one."
        )
    else:
        tables.append(_neighbourhood_table(in_catchment, areas, catchment, threshold))
        map_spec = _map_spec(threshold)
    figures = _figures(
        supplied, sum(located.values()), people, residents, hide, threshold
    )
    trail.hidden += sum(figure.suppressed for figure in figures)
    trail.working.append(
        Step(
            title="Hid small counts",
            detail=(
                f"Counts from 1 to {threshold - 1} for a named place or a "
                "deprivation decile were hidden, along with anything that "
                f"would let them be worked out. {trail.hidden} cells or "
                "figures were hidden."
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
        tables=tuple(tables),
        map=map_spec,
        working=tuple(trail.working),
        choices=(*trail.choices, *_choices(catchment, threshold)),
        checks=_checks(lens_input.mode.name, catchment),
        caveats=CAVEATS,
        warnings=tuple(trail.warnings),
        sources=tuple(trail.sources),
        privacy=_privacy(threshold, trail),
    )


# --- options ---------------------------------------------------------------


def _min_share(options: dict[str, Any]) -> float:
    """Read and check the share a local authority needs to join the catchment."""
    value = options.get("catchment_min_share")
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise LensInputError("The option 'catchment_min_share' must be a number.")
    if not 0 < value <= 1:
        msg = (
            "The option 'catchment_min_share' must be above 0 and no more "
            "than 1, for example 0.05 for five per cent."
        )
        raise LensInputError(msg)
    return float(value)


# --- deprivation -----------------------------------------------------------


def _load_areas() -> dict[str, _Area]:
    """Load the deprivation index as one record per neighbourhood."""
    frame = nw.from_native(load_imd(nation=ENGLAND, year=2025), eager_only=True)
    names = (
        "geography_code",
        "geography_name",
        "lad_code",
        "lad_name",
        "imd_decile",
        "population",
    )
    columns = [frame[name].to_list() for name in names]
    return {
        str(code): _Area(
            code=str(code),
            name=str(name),
            lad_code=str(lad_code),
            lad_name=str(lad_name),
            decile=int(decile),
            residents=0.0 if is_blank(residents) else float(residents),
        )
        for code, name, lad_code, lad_name, decile, residents in zip(
            *columns, strict=True
        )
    }


def _keep_english(
    counts: Counter[str], areas: dict[str, _Area], threshold: int, trail: Trail
) -> dict[str, int]:
    """Keep the people placed in a neighbourhood the index covers."""
    located = {code: n for code, n in counts.items() if code in areas and n > 0}
    n_located = sum(located.values())
    total = sum(counts.values())
    outside = total - n_located
    trail.working.append(
        Step(
            title="Joined neighbourhoods to the deprivation index",
            detail=(
                f"{n_located} people live in a neighbourhood covered by the "
                f"English Indices of Deprivation 2025. {outside} live outside "
                "England or have a code the index does not list."
            ),
            rows_in=total,
            rows_out=n_located,
        )
    )
    if outside:
        trail.warnings.append(
            f"{outside} people were placed outside England, or in a "
            "neighbourhood code the 2025 index does not list (for example a "
            "2011 code). This lens covers England only, so they are left out."
        )
    if n_located < threshold:
        msg = (
            f"Fewer than {threshold} people could be placed in an English "
            "neighbourhood, which is too few to give figures that do not "
            "point at individuals."
        )
        raise LensInputError(msg)
    return located


def _choose_catchment(
    located: dict[str, int],
    areas: dict[str, _Area],
    wanted: Any,
    min_share: float,
) -> _Catchment:
    """Work out the area served, from the option or from where people live."""
    if wanted is not None:
        return _named_catchment(wanted, areas)
    per_authority: Counter[str] = Counter()
    for code, n in located.items():
        per_authority[areas[code].lad_code] += n
    total = sum(per_authority.values())
    chosen = [lad for lad, n in per_authority.most_common() if n / total >= min_share]
    if not chosen:
        return _Catchment(
            lad_codes=frozenset(),
            names=(ENGLAND,),
            reason=(
                "No local authority holds as much as "
                f"{min_share:.0%} of the people located, so the whole of "
                "England is used."
            ),
            whole_country=True,
        )
    lad_names = _authority_names(areas)
    return _Catchment(
        lad_codes=frozenset(chosen),
        names=tuple(lad_names[lad] for lad in chosen),
        reason=(
            f"Each of these local authorities holds at least {min_share:.0%} "
            "of the people located."
        ),
    )


def _named_catchment(wanted: Any, areas: dict[str, _Area]) -> _Catchment:
    """Turn the catchment option into a set of local authorities."""
    items = [wanted] if isinstance(wanted, str) else wanted
    if not isinstance(items, list | tuple) or not all(
        isinstance(item, str) and item.strip() for item in items
    ):
        msg = (
            "The option 'catchment' must be a local authority name or code, a "
            "list of them, or 'England'."
        )
        raise LensInputError(msg)
    cleaned = [item.strip() for item in items]
    if [item.lower() for item in cleaned] == [ENGLAND.lower()]:
        return _Catchment(
            lad_codes=frozenset(),
            names=(ENGLAND,),
            reason="You set the catchment to the whole of England.",
            whole_country=True,
        )
    lad_names = _authority_names(areas)
    by_key = {code.lower(): code for code in lad_names}
    by_key.update({name.lower(): code for code, name in lad_names.items()})
    unknown = [item for item in cleaned if item.lower() not in by_key]
    if unknown:
        msg = (
            "These catchment entries are not English local authorities in the "
            f"2025 index: {', '.join(unknown)}. Use the names or codes as "
            "the index spells them."
        )
        raise LensInputError(msg)
    chosen = list(dict.fromkeys(by_key[item.lower()] for item in cleaned))
    return _Catchment(
        lad_codes=frozenset(chosen),
        names=tuple(lad_names[lad] for lad in chosen),
        reason="You set the catchment.",
    )


def _authority_names(areas: dict[str, _Area]) -> dict[str, str]:
    """Return local authority code to name for every authority in the index."""
    return {area.lad_code: area.lad_name for area in areas.values()}


def _inside(area: _Area, catchment: _Catchment) -> bool:
    """Return True when a neighbourhood is in the catchment."""
    return catchment.whole_country or area.lad_code in catchment.lad_codes


def _keep_catchment(
    located: dict[str, int],
    areas: dict[str, _Area],
    catchment: _Catchment,
    threshold: int,
    trail: Trail,
) -> dict[str, int]:
    """Keep the people who live in the catchment and record the step."""
    inside = {code: n for code, n in located.items() if _inside(areas[code], catchment)}
    n_located = sum(located.values())
    n_inside = sum(inside.values())
    trail.working.append(
        Step(
            title="Set the catchment",
            detail=(
                f"Catchment: {catchment.label}. {catchment.reason} "
                f"{n_inside} of the {n_located} people located live in it. "
                "The decile figures and the map cover these people."
            ),
            rows_in=n_located,
            rows_out=n_inside,
        )
    )
    if n_inside < threshold:
        msg = (
            f"Fewer than {threshold} of the people located live in the "
            f"catchment ({catchment.label}), which is too few to give figures "
            "that do not point at individuals. Check the 'catchment' option."
        )
        raise LensInputError(msg)
    if n_inside < n_located:
        trail.warnings.append(
            f"{n_located - n_inside} people live outside the catchment. They "
            "are counted in the local authority table but not in the decile "
            "figures. Change the 'catchment' option to include them."
        )
    return inside


def _by_decile(counts: dict[str, int], areas: dict[str, _Area]) -> list[int]:
    """Total people by deprivation decile, most deprived first."""
    totals = [0] * len(DECILES)
    for code, n in counts.items():
        totals[areas[code].decile - 1] += n
    return totals


def _residents_by_decile(areas: dict[str, _Area], catchment: _Catchment) -> list[float]:
    """Total catchment residents by deprivation decile, most deprived first."""
    totals = [0.0] * len(DECILES)
    for area in areas.values():
        if _inside(area, catchment):
            totals[area.decile - 1] += area.residents
    return totals


# --- tables ----------------------------------------------------------------


def _per_1000(people: int, residents: float) -> float | None:
    """Return people per 1,000 residents, or None when nobody lives there."""
    return round(1000 * people / residents, 2) if residents else None


def _decile_table(
    people: list[int], residents: list[float], hide: list[bool], trail: Trail
) -> Table:
    """People, residents and reach by deprivation decile, in the catchment."""
    total = sum(people)
    all_residents = sum(residents)
    rows = [
        {
            "imd_decile": decile,
            "people": None if hidden else n,
            "share_of_people": None if hidden else percent(n, total),
            "residents": round(lived),
            "share_of_residents": percent(lived, all_residents),
            "people_per_1000": None if hidden else _per_1000(n, lived),
            "suppressed": hidden,
        }
        for decile, n, lived, hidden in zip(
            DECILES, people, residents, hide, strict=True
        )
    ]
    trail.hidden += sum(hide)
    trail.working.append(
        Step(
            title="Counted people and residents by deprivation decile",
            detail=(
                "Decile 1 is the most deprived tenth of neighbourhoods in "
                "England and decile 10 the least. For each decile, the people "
                "you reached in the catchment were set against everyone who "
                "lives in its neighbourhoods of that decile (mid-2022 "
                "population)."
            ),
            rows_in=total,
            rows_out=total,
        )
    )
    return Table(
        id="by_decile",
        title="People and residents by deprivation decile, in the catchment",
        columns=(
            "imd_decile",
            "people",
            "share_of_people",
            "residents",
            "share_of_residents",
            "people_per_1000",
            "suppressed",
        ),
        rows=rows,
    )


def _authority_table(
    located: dict[str, int],
    areas: dict[str, _Area],
    catchment: _Catchment,
    threshold: int,
    trail: Trail,
) -> Table:
    """People by local authority, with small authorities grouped together.

    Catchment authorities are always named, and hidden when small. Other
    authorities are named only when they reach the threshold; the rest are
    added into one unnamed row, which is shown as it is because it names no
    place.
    """
    per_authority: Counter[str] = Counter()
    for code, n in located.items():
        per_authority[areas[code].lad_code] += n
    lad_names = _authority_names(areas)
    total = sum(per_authority.values())
    core = sorted(
        ((per_authority[lad], lad) for lad in catchment.lad_codes), reverse=True
    )
    hide_core = cells_to_hide([n for n, _ in core], threshold)
    trail.hidden += sum(hide_core)
    rest = [
        (n, lad)
        for lad, n in per_authority.most_common()
        if lad not in catchment.lad_codes
    ]
    named = [(n, lad) for n, lad in rest if n >= threshold]
    unnamed = [n for n, _ in rest if n < threshold]

    def row(n: int, lad: str, hidden: bool, inside: bool) -> dict[str, Any]:
        return {
            "lad_code": lad,
            "lad_name": lad_names[lad],
            "local_authorities": 1,
            "people": None if hidden else n,
            "share_of_people": None if hidden else percent(n, total),
            "in_catchment": inside,
            "suppressed": hidden,
        }

    rows = [
        row(n, lad, hidden, True)
        for (n, lad), hidden in zip(core, hide_core, strict=True)
    ]
    rows += [row(n, lad, False, catchment.whole_country) for n, lad in named]
    if unnamed:
        rows.append(
            {
                "lad_code": None,
                "lad_name": "Other local authorities",
                "local_authorities": len(unnamed),
                "people": sum(unnamed),
                "share_of_people": percent(sum(unnamed), total),
                "in_catchment": catchment.whole_country,
                "suppressed": False,
            }
        )
    return Table(
        id="by_local_authority",
        title="People by local authority",
        columns=(
            "lad_code",
            "lad_name",
            "local_authorities",
            "people",
            "share_of_people",
            "in_catchment",
            "suppressed",
        ),
        rows=rows,
    )


def _neighbourhood_table(
    in_catchment: dict[str, int],
    areas: dict[str, _Area],
    catchment: _Catchment,
    threshold: int,
) -> Table:
    """One row per catchment neighbourhood, with people in bands, for the map."""
    rows = [
        {
            "geography_code": area.code,
            "geography_name": area.name,
            "lad_name": area.lad_name,
            "imd_decile": area.decile,
            "residents": round(area.residents),
            "people_band": count_band(in_catchment.get(area.code, 0), threshold),
        }
        for area in sorted(areas.values(), key=lambda item: item.code)
        if _inside(area, catchment)
    ]
    return Table(
        id="by_neighbourhood",
        title="Catchment neighbourhoods: deprivation decile and people reached",
        columns=(
            "geography_code",
            "geography_name",
            "lad_name",
            "imd_decile",
            "residents",
            "people_band",
        ),
        rows=rows,
        detail=True,
    )


def _map_spec(threshold: int) -> MapSpec:
    """Describe the map of the catchment."""
    return MapSpec(
        title="Deprivation and people reached, by neighbourhood",
        geography_type="LSOA",
        geography_year=2021,
        table="by_neighbourhood",
        code_column="geography_code",
        layers=(
            MapLayer(
                id="deprivation",
                label="Deprivation decile",
                value_column="imd_decile",
                kind="sequential",
                note="1 is the most deprived tenth of neighbourhoods in England.",
                categories=DECILES,
                emphasis="low",
            ),
            MapLayer(
                id="people",
                label="People reached",
                value_column="people_band",
                kind="ordinal",
                note=(
                    "The lowest band includes zero, so a neighbourhood with a "
                    "few people looks the same as one with none."
                ),
                categories=tuple(band_labels(threshold)),
            ),
        ),
    )


# --- figures ---------------------------------------------------------------


def _figures(
    supplied: int,
    located: int,
    people: list[int],
    residents: list[float],
    hide: list[bool],
    threshold: int,
) -> list[Figure]:
    """Build the headline figures."""
    figures = [
        Figure("people_supplied", "People in the data you gave", supplied, "people"),
        Figure(
            "people_located",
            "People placed in an English neighbourhood",
            located,
            "people",
        ),
        Figure(
            "people_in_catchment",
            "People who live in the catchment",
            sum(people),
            "people",
            note="The decile figures below are about these people.",
        ),
        _share_figure(
            "share_most_deprived_10",
            "Share of your people in the catchment who live in the 10% most "
            "deprived neighbourhoods in England",
            people,
            hide,
            (0,),
            threshold,
        ),
        _share_figure(
            "share_most_deprived_20",
            "Share of your people in the catchment who live in the 20% most "
            "deprived neighbourhoods in England",
            people,
            hide,
            MOST_DEPRIVED,
            threshold,
        ),
        Figure(
            "catchment_share_most_deprived_20",
            "Share of catchment residents who live in the 20% most deprived "
            "neighbourhoods in England",
            percent(sum(residents[:2]), sum(residents)),
            "percent",
            note="The comparison for the share of your people.",
        ),
    ]
    return figures + _reach_figures(people, hide, residents, threshold)


def _share_figure(
    figure_id: str,
    label: str,
    people: list[int],
    hide: list[bool],
    positions: tuple[int, ...],
    threshold: int,
) -> Figure:
    """A share of the people located, hidden when it would give a cell away."""
    if group_hidden(people, hide, positions, threshold):
        return Figure(
            figure_id,
            label,
            None,
            "percent",
            note="Hidden to protect a small count.",
            suppressed=True,
        )
    part = sum(people[position] for position in positions)
    return Figure(figure_id, label, percent(part, sum(people)), "percent")


def _reach_figures(
    people: list[int], hide: list[bool], residents: list[float], threshold: int
) -> list[Figure]:
    """Reach per 1,000 in the most deprived fifth and in the rest."""
    groups = (
        (
            "reach_per_1000_most_deprived_20",
            "People reached per 1,000 residents in the catchment's "
            "neighbourhoods among the 20% most deprived in England",
            MOST_DEPRIVED,
        ),
        (
            "reach_per_1000_elsewhere",
            "People reached per 1,000 residents in the rest of the catchment",
            ELSEWHERE,
        ),
    )
    hidden = group_hidden(people, hide, MOST_DEPRIVED, threshold)
    return [
        _reach_figure(figure_id, label, people, residents, positions, hidden)
        for figure_id, label, positions in groups
    ]


def _reach_figure(
    figure_id: str,
    label: str,
    people: list[int],
    residents: list[float],
    positions: tuple[int, ...],
    hidden: bool,
) -> Figure:
    """One reach figure for a group of deciles."""
    if hidden:
        return Figure(
            figure_id,
            label,
            None,
            "per_1000",
            note="Hidden to protect a small count.",
            suppressed=True,
        )
    lived = sum(residents[position] for position in positions)
    if not lived:
        return Figure(
            figure_id,
            label,
            None,
            "per_1000",
            note="The catchment has no neighbourhoods of this kind.",
        )
    reached = sum(people[position] for position in positions)
    return Figure(figure_id, label, _per_1000(reached, lived), "per_1000")


# --- what the person needs to know -----------------------------------------


def _choices(catchment: _Catchment, threshold: int) -> tuple[Choice, ...]:
    """List the choices the lens made."""
    return (
        Choice(
            id="deprivation_measure",
            label="Measure of deprivation",
            value="English Indices of Deprivation 2025, overall index",
            reason="It is the current official measure for England.",
        ),
        Choice(
            id="most_deprived",
            label="What counts as most deprived",
            value="Deciles 1 and 2: the 20% most deprived neighbourhoods",
            reason="This is the cut most funders use.",
        ),
        Choice(
            id="catchment",
            label="Catchment",
            value=list(catchment.names),
            reason=catchment.reason,
            option="catchment",
        ),
        Choice(
            id="suppress_below",
            label="Smallest count shown",
            value=threshold,
            reason="Smaller counts could point at individuals, so they are hidden.",
            option="suppress_below",
        ),
    )


def _checks(mode: str, catchment: _Catchment) -> tuple[Check, ...]:
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
            id="home_postcode",
            question="Is the location where each person lives?",
            why=(
                "The figures describe the neighbourhoods people live in. A "
                "postcode for a service, school or hostel would mislead."
            ),
        ),
        Check(
            id="period",
            question="Does the data cover the period you are reporting on?",
            why="The lens cannot tell which dates the rows are from.",
        ),
        Check(
            id="catchment",
            question=f"Is this the area you serve: {catchment.label}?",
            why=(
                "Reach per 1,000 residents is worked out for this area. A "
                "different area gives different figures."
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
            "A count is hidden when it is small and is about a named place or "
            "a deprivation decile.",
            "The map shows people in bands, and the lowest band includes zero, "
            "so a neighbourhood with a few people looks the same as one with "
            "none.",
            "The number of people in local authorities that are not named is "
            "shown even when it is small, because it points at no place.",
        ),
    )


LENS = register_lens(Lens(info=INFO, run=run))
