"""Need against reach: where is need high and our presence low?

Takes the home postcodes of the people a charity helped (or counts already
totalled by local authority), sets them against a count of people in need in
each local authority of England and Wales, and lists the places where need is
high and the charity reaches few people.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date
from statistics import median
from typing import Any

import uk_open_data
from uk_open_data.lenses._inputs import is_blank, to_count
from uk_open_data.lenses._model import (
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
    OptionChoice,
    Privacy,
    Role,
    Step,
    Table,
)
from uk_open_data.lenses._need import (
    DEFAULT_TOP,
    FEW_AREAS,
    MAX_TOP,
    MEASURES,
    NEED_BANDS,
    Authority,
    Compared,
    Measure,
    band_by_need,
    choose_compared,
    equal_parts,
    load_need,
    read_measure,
    read_top,
)
from uk_open_data.lenses._need import clear_need_cache as clear_need_cache
from uk_open_data.lenses._need import download_need_figures as download_need_figures
from uk_open_data.lenses._need import keep_need_figures as keep_need_figures
from uk_open_data.lenses._need import need_figures_path as need_figures_path
from uk_open_data.lenses._privacy import SECOND_COUNT_NOTE, cells_to_hide, group_hidden
from uk_open_data.lenses._steps import (
    EVERYWHERE,
    LOCAL_AUTHORITY,
    POSTCODE_LOOKUP,
    SUPPRESS_BELOW,
    Trail,
    count_by_postcode,
    percent,
    read_threshold,
    use_postcode_table,
)

LENS_ID = "need-reach"
LENS_VERSION = "0.1"
NO_REACH = "None, or count hidden"
REACH_BANDS = (NO_REACH, "Lower reach", "Middle reach", "Higher reach")
# Where people go when their local authority is not in the need figures. The
# next step counts them as left out.
UNLISTED = "unlisted"


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
            amount=True,
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
            # The built-in needs. A table of your own is given as a mapping.
            choices=tuple(
                OptionChoice(measure.id, measure.label) for measure in MEASURES.values()
            ),
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
class _Row:
    """One local authority in the comparison."""

    authority: Authority
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
    """Run the lens. Use :func:`uk_open_data.lenses.run_lens` to call it."""
    options = lens_input.options
    threshold = read_threshold(options)
    top = read_top(options)
    measure = read_measure(options.get("need"))
    trail = Trail()
    authorities = load_need(measure, trail)
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
    compared = choose_compared(options.get("catchment"), authorities)
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
        package_version=uk_open_data.__version__,
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


# --- reading the input -----------------------------------------------------


def _count_by_authority(
    places: list[Any],
    counts: list[Any],
    authorities: dict[str, Authority],
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
    authorities: dict[str, Authority],
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


def _rows(
    located: dict[str, int],
    authorities: dict[str, Authority],
    compared: Compared,
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
    need_bands = band_by_need(need)
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
    outside: int, with_people: int, compared: Compared, trail: Trail
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


def _reach_bands(people: list[int], need: list[float], hide: list[bool]) -> list[str]:
    """Put each local authority with a count that can be shown in a third.

    A local authority with nobody, or with a hidden count, goes in one band, so
    the map does not tell a few people from none.
    """
    shown = [i for i, n in enumerate(people) if n > 0 and not hide[i] and need[i] > 0]
    part = equal_parts([people[i] / need[i] for i in shown], 3)
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
    measure: Measure,
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
    measure: Measure, compared: Compared, top: int, threshold: int
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


def _checks(mode: str, measure: Measure, compared: Compared) -> tuple[Check, ...]:
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
            SECOND_COUNT_NOTE,
            "The map shows reach in bands, and the lowest band holds places "
            "with nobody and places with a hidden count.",
            "The need figures are public counts and are shown in full.",
        ),
    )


LENS = Lens(info=INFO, run=run)
