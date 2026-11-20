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
from typing import Any

import uk_open_data
from uk_open_data.analyses._answers import (
    HIDDEN,
    IN_NEED,
    NeedWords,
    high_need_places,
    look_first,
    need_words,
    not_counted,
    number,
    sentence_case,
    shown_first,
    values,
)
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
    MapLayer,
    MapSpec,
    Option,
    OptionChoice,
    Privacy,
    Role,
    Step,
    Table,
)
from uk_open_data.analyses._need import (
    DEFAULT_TOP,
    FEW_AREAS,
    MAX_TOP,
    MEASURES,
    NEED_BANDS,
    RESIDENTS,
    Authority,
    Compared,
    Measure,
    band_by_need,
    choose_compared,
    equal_parts,
    few_in_need_bands,
    few_places,
    guess_compared,
    high_need_cut,
    load_need,
    load_residents,
    need_per_1000,
    not_listed_rows,
    read_measure,
    read_top,
)
from uk_open_data.analyses._need import clear_need_cache as clear_need_cache
from uk_open_data.analyses._need import download_need_figures as download_need_figures
from uk_open_data.analyses._need import keep_need_figures as keep_need_figures
from uk_open_data.analyses._need import need_figures_path as need_figures_path
from uk_open_data.analyses._privacy import (
    SECOND_COUNT_NOTE,
    cells_to_hide,
    group_hidden,
)
from uk_open_data.analyses._steps import (
    EVERYWHERE,
    HOW_TO_NAME_A_PLACE,
    LOCAL_AUTHORITY,
    NOT_A_COUNT,
    POSTCODE_LOOKUP,
    SUPPRESS_BELOW,
    Trail,
    bad_counts,
    before_rounding,
    count_by_postcode,
    percent,
    plural,
    read_min_share,
    read_threshold,
    use_postcode_table,
)

ANALYSIS_ID = "need-reach"
ANALYSIS_VERSION = "0.2"
KEY_FIGURES = (
    "share_of_people_in_high_need_areas",
    "share_of_need_in_high_need_areas",
    "high_need_areas_without_people",
    # These two stand in when a figure above is hidden.
    "reach_per_100_in_need",
    "people_in_catchment",
)
# With one place compared every share is 100%, so the rate and the counts
# behind it are shown instead.
KEY_FIGURES_FOR_ONE_PLACE = (
    "reach_per_100_in_need",
    "people_in_catchment",
    "people_in_need",
)
LOWEST = "your lowest reach"
# The label and the note of the map's need layer when it is shaded by rate.
NEED_BY_RATE = (
    "People in need for each 1,000 residents",
    "Local authorities in five equal groups by people in need for each 1,000 "
    "residents, so a large place is not darker for its size alone.",
)
LARGE_PLACE_DARKER = (
    " A large place is likely to be darker than a small one with the same rate."
)
NO_REACH = "None, or count hidden"
REACH_BANDS = (NO_REACH, "Lower reach", "Middle reach", "Higher reach")
# Where people go when their local authority is not in the need figures. The
# next step counts them as left out.
UNLISTED = "unlisted"


INFO = AnalysisInfo(
    id=ANALYSIS_ID,
    title="Need against reach",
    question="Where is need high and our presence low?",
    summary=(
        "Counts the people you helped in each local authority and sets them "
        "against the number of people in need there. It lists the places "
        "where need is high and you reach few people."
    ),
    version=ANALYSIS_VERSION,
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
            label=LABELS["need"],
            description=(
                "The need to compare your reach with: one of "
                "the measures listed, or a table Nomis publishes by local "
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
            label=LABELS["catchment"],
            description=(
                "The area you serve, with the places in it that you do not "
                "reach yet: a list of local authority names or codes, or "
                "'England', 'Wales' or 'England and Wales'. Left empty, the "
                "analysis uses the local authorities where most of your "
                "people live."
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
            name="top",
            label=LABELS["top"],
            description=(
                f"How many high-need, low-reach places to list, from 1 to {MAX_TOP}."
            ),
            default=DEFAULT_TOP,
        ),
    ),
    coverage=EVERYWHERE,
)

LOW_REACH = (
    "Low reach is not the same as unmet need. Another organisation may already "
    "serve a place where you reach few people."
)
CAVEATS = (
    LOW_REACH,
    "Need is a count of people, so a large local authority is more likely to "
    "be listed as high need than a small one with the same rate.",
    "Reach sets the people you helped against everyone counted as in need. "
    "The people you helped may not all be in that group.",
)
# Every resident is not a need, so these say what the count is instead.
CAVEATS_FOR_RESIDENTS = (
    LOW_REACH,
    "The places listed are the ones with the most residents. That says where "
    "most people live, not where need is highest.",
)


def _charts(words: NeedWords) -> tuple[Chart, ...]:
    """The two charts of the places listed, in the words that fit the measure."""
    counted = sentence_case(words.noun)
    reached = f"People reached per 100 {words.per}"
    return (
        Chart(
            id="need_in_priority_areas",
            title=f"{counted} in the places listed",
            table="priority_areas",
            category_column="geography_name",
            series=(ChartSeries("people_in_need", counted, "people"),),
        ),
        Chart(
            id="reach_in_priority_areas",
            title=f"{reached} in the places listed",
            table="priority_areas",
            category_column="geography_name",
            series=(ChartSeries("people_per_100_in_need", reached, "per_100"),),
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
    # People in need for each 1,000 residents, or None when residents are not known.
    need_rate: float | None
    need_band: str
    reach_band: str

    @property
    def reach(self) -> float | None:
        """People per 100 in need, or None when it cannot be shown."""
        if self.hidden:
            return None
        return _per_100(self.people, self.authority.need)


def run(analysis_input: AnalysisInput) -> AnalysisResult:
    """Run the analysis. Use :func:`uk_open_data.analyses.run_analysis` to call it."""
    options = analysis_input.options
    threshold = read_threshold(options)
    top = read_top(options)
    min_share = read_min_share(options)
    measure = read_measure(options.get("need"))
    trail = Trail()
    authorities = load_need(measure, trail)
    residents = _residents(measure, trail)
    if analysis_input.mode.name == "postcodes":
        counts, supplied = count_by_postcode(
            analysis_input.values["postcode"],
            use_postcode_table(options),
            trail,
            LOCAL_AUTHORITY,
        )
    else:
        counts, supplied = _count_by_authority(
            analysis_input.values["local_authority"],
            analysis_input.values["count"],
            authorities,
            trail,
        )
    located = _keep_listed(counts, authorities, threshold, trail)
    compared = _choose_area(options.get("catchment"), located, authorities, min_share)
    words = need_words(measure.id == RESIDENTS.id)
    rows = _rows(located, authorities, compared, residents, threshold, words, trail)
    by_rate = rows[0].need_rate is not None
    figures = _figures(supplied, sum(located.values()), rows, words, measure, threshold)
    tables = (
        _priority_table(rows, top, threshold, words, trail),
        _authority_table(rows, words),
    )
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
    return AnalysisResult(
        analysis_id=ANALYSIS_ID,
        analysis_version=ANALYSIS_VERSION,
        package_version=uk_open_data.__version__,
        run_on=date.today().isoformat(),
        input_mode=analysis_input.mode.name,
        figures=tuple(figures),
        tables=tables,
        map=_map_spec(by_rate, words, rows),
        working=tuple(trail.working),
        choices=(
            *trail.choices,
            *_choices(measure, compared, top, threshold, by_rate),
        ),
        checks=_checks(analysis_input.mode.name, measure, compared),
        caveats=(*_caveats(words), measure.caveat),
        warnings=tuple(trail.warnings),
        sources=tuple(trail.sources),
        privacy=_privacy(threshold, trail),
        charts=_charts(words),
        answer=_answer(figures, tables[0], words, compared.guessed),
        key_figures=shown_first(
            figures, KEY_FIGURES_FOR_ONE_PLACE if len(rows) == 1 else KEY_FIGURES
        ),
    )


def _residents(measure: Measure, trail: Trail) -> dict[str, float] | None:
    """Load residents to shade the map by a rate, when that can be done.

    When the need is every resident there is no rate to work out. When the
    need figures came from a copy kept on this machine, residents are taken
    from a kept copy too and never fetched, so the run stays off the network.
    """
    if measure.id == RESIDENTS.id:
        return None
    return load_residents(trail, fetch=need_figures_path(measure.id) is None)


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
    blank = supplied = 0
    bad: list[int] = []
    not_listed: list[int] = []
    for row, (place, raw) in enumerate(zip(places, counts, strict=True), start=1):
        count = to_count(raw)
        if is_blank(place):
            blank += 1
        elif count is None:
            bad.append(row)
        else:
            supplied += count
            code = by_key.get(str(place).strip().casefold())
            if code is None:
                not_listed.append(row)
            totals[code or UNLISTED] += count
    unknown = len(not_listed)
    if bad:
        raise AnalysisInputError(bad_counts(bad, NOT_A_COUNT), role="count")
    if blank:
        trail.warnings.append(f"{plural(blank, 'row')} had no local authority.")
    if unknown:
        trail.warnings.append(not_listed_rows(not_listed))
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
        raise AnalysisInputError(_too_few_placed(outside, threshold))
    return located


def _too_few_placed(outside: int, threshold: int) -> str:
    """Say why too few people could be placed: few were given, or few fitted."""
    if outside < threshold:
        return (
            f"Fewer than {threshold} people could be placed in a local "
            "authority in England or Wales, which is too few to give figures "
            "that do not point at individuals."
        )
    return (
        f"{outside} people are in a place the need figures do not list, or "
        "outside England and Wales, so too few are left to give figures. "
        f"Check the places in your data. {HOW_TO_NAME_A_PLACE}"
    )


def _choose_area(
    wanted: Any,
    located: dict[str, int],
    authorities: dict[str, Authority],
    min_share: float,
) -> Compared:
    """Work out the area to compare, from the option or from where people live."""
    if wanted is None:
        return guess_compared(located, authorities, min_share)
    return choose_compared(wanted, authorities)


# --- the comparison --------------------------------------------------------


def _rows(
    located: dict[str, int],
    authorities: dict[str, Authority],
    compared: Compared,
    residents: dict[str, float] | None,
    threshold: int,
    words: NeedWords,
    trail: Trail,
) -> list[_Row]:
    """Build one row per local authority compared, with small counts marked."""
    if not compared.codes:
        msg = (
            f"The need figures list no local authority in {compared.label}. "
            f"Check {said('catchment')}."
        )
        raise AnalysisInputError(msg, option="catchment")
    people = [located.get(code, 0) for code in compared.codes]
    need = [authorities[code].need for code in compared.codes]
    n_located = sum(located.values())
    n_inside = sum(people)
    with_people = sum(1 for n in people if n > 0)
    trail.working.append(
        Step(
            title="Set the area you serve",
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
            f"Fewer than {threshold} of the people located live in the area "
            f"you serve ({compared.label}), which is too few to give figures "
            f"that do not point at individuals. Check {said('catchment')}."
        )
        raise AnalysisInputError(msg, option="catchment")
    _warn_about_area(n_located - n_inside, with_people, compared, trail)
    cut = high_need_cut(need)
    high = [amount >= cut and amount > 0 for amount in need]
    # When one small count needs a second count hidden with it, the smallest
    # is taken, wherever it is. The table of places matters more here than the
    # share in high-need places, which is hidden when it would give one away.
    hide = cells_to_hide(people, threshold)
    # The map shades need by a rate where it can, so that a large place is
    # not darker for its size alone.
    rates = need_per_1000(compared.codes, authorities, residents)
    need_bands = band_by_need(need if rates is None else rates)
    reach_bands = _reach_bands(people, need, hide)
    trail.working.append(
        Step(
            title=f"Set reach against {words.topic}",
            detail=(
                "For each local authority, the people you helped were divided "
                f"by the number of {words.noun} and multiplied by 100. A "
                f"local authority {words.rule} when its count of "
                f"{words.noun} is in the top quarter of the area (at or "
                f"above {round(cut):,})."
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
            need_rate=None if rates is None else rates[i],
            need_band=need_bands[i],
            reach_band=reach_bands[i],
        )
        for i, code in enumerate(compared.codes)
    ]


def _warn_about_area(
    outside: int, with_people: int, compared: Compared, trail: Trail
) -> None:
    """Warn when the area looks too wide, too narrow or too small."""
    if outside:
        trail.warnings.append(
            f"{outside} people live outside the area you serve and are left "
            f"out. Change {said('catchment')} to include them."
        )
    if compared.guessed:
        trail.warnings.append(
            "The area you serve was worked out from where your people live, "
            "so it holds only places you already reach. To see places you do "
            f"not reach, fill in {said('catchment')}."
        )
    if not compared.named and with_people * FEW_AREAS < len(compared.codes):
        trail.warnings.append(
            f"No area was given, so all {len(compared.codes)} local "
            f"authorities in {compared.label} are looked at, and your people "
            f"live in {with_people} of them. If you serve a smaller area, "
            f"fill in {said('catchment')}, so that places you could not reach "
            "are not listed as gaps."
        )
    if len(compared.codes) == 1:
        trail.warnings.append(
            "Only one local authority is compared, so there is no other place "
            "to set it against and 'high need' says nothing."
        )
    elif len(compared.codes) < len(NEED_BANDS):
        trail.warnings.append(
            f"Only {len(compared.codes)} local authorities are compared, so "
            "'high need' says little. It means the top quarter, and at least "
            "one place."
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


def _priority_table(
    rows: list[_Row], top: int, threshold: int, words: NeedWords, trail: Trail
) -> Table:
    """The high-need local authorities with the lowest reach.

    A hidden count is ranked as the largest a hidden small count can be. That
    number comes from the threshold alone, so the order gives nothing away.

    The title says what the list is in order of and no more. Which of its
    places to look at first is for the answer to say, because a place high on
    a short list can still have more reach than the area as a whole.
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
            title=f"Listed the places with {words.high} and low reach",
            detail=(
                f"The {len(high)} places with {words.high} were put in "
                f"order of reach, lowest first, and then by {words.topic}, "
                f"highest first. The first {len(ranked)} are listed. A hidden count "
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
        title=f"Places with {words.high}, your lowest reach first",
        headings=words.headings(),
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


def _authority_table(rows: list[_Row], words: NeedWords) -> Table:
    """Every local authority in the area, for the map and for a closer look."""
    return Table(
        id="by_local_authority",
        title=(
            f"{sentence_case(words.topic)} and reach in every local authority "
            "in the area you serve"
        ),
        headings=words.headings(),
        columns=(
            "geography_code",
            "geography_name",
            "people_in_need",
            "people_in_need_per_1000_residents",
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
                "people_in_need_per_1000_residents": row.need_rate,
                "need_band": row.need_band,
                "high_need": row.high_need,
                "reach_band": row.reach_band,
            }
            for row in rows
        ],
        detail=True,
    )


def _by_count(words: NeedWords) -> tuple[str, str]:
    """The label and the note of the need layer when it is shaded by count."""
    note = f"Local authorities in five equal groups by {words.noun}."
    if words is IN_NEED:
        note += LARGE_PLACE_DARKER
    return sentence_case(words.noun), note


def _caveats(words: NeedWords) -> tuple[str, ...]:
    """What the figures cannot say, in the words that fit the measure."""
    return CAVEATS if words is IN_NEED else CAVEATS_FOR_RESIDENTS


def _map_spec(by_rate: bool, words: NeedWords, rows: list[_Row]) -> MapSpec:
    """Describe the map of need and reach.

    Need is shaded by people in need for each 1,000 residents when
    ``by_rate`` is true, and by the count of people in need when it is not.
    Each note says how few places were grouped, when there are fewer than
    the key has groups.
    """
    need_label, need_note = NEED_BY_RATE if by_rate else _by_count(words)
    reached = sum(row.reach_band != NO_REACH for row in rows)
    return MapSpec(
        title=f"{sentence_case(words.topic)} and reach, by local authority",
        geography_type="LAD",
        geography_year=2023,
        table="by_local_authority",
        code_column="geography_code",
        layers=(
            MapLayer(
                id="need",
                label=need_label,
                value_column="need_band",
                kind="ordinal",
                note=need_note + few_in_need_bands(len(rows)),
                categories=NEED_BANDS,
            ),
            MapLayer(
                id="reach",
                label=f"People reached per 100 {words.per}",
                value_column="reach_band",
                kind="ordinal",
                note=(
                    "Local authorities with a count that can be shown are in "
                    "three equal groups. The lowest band holds places with "
                    "nobody and places with a hidden count."
                    + few_places(reached, len(REACH_BANDS) - 1)
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
    words: NeedWords,
    measure: Measure,
    threshold: int,
) -> list[Figure]:
    """Build the headline figures, in the words that fit the measure."""
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
            "People who live in the area you serve",
            in_catchment,
            "people",
            note="The figures below are about these people.",
        ),
        Figure(
            "areas_compared",
            "Local authorities in the area you serve",
            len(rows),
            "areas",
        ),
        Figure(
            "people_in_need",
            f"{words.counted} in the area you serve ({measure.label})",
            round(sum(need)),
            "people",
        ),
        Figure(
            "reach_per_100_in_need",
            f"People you reached per 100 {words.noun}, across the area",
            _per_100(in_catchment, sum(need)),
            "per_100",
            exact=before_rounding(in_catchment, sum(need)),
        ),
        Figure(
            "high_need_areas",
            f"Local authorities with {words.high}",
            len(high),
            "areas",
            note=f"The top quarter of the places in it, by {words.noun}.",
        ),
        Figure(
            "high_need_areas_without_people",
            f"{sentence_case(words.places)} where you reached nobody",
            sum(1 for i in high if people[i] == 0),
            "areas",
        ),
        _share_in_high_need(rows, high, words, threshold),
        Figure(
            "share_of_need_in_high_need_areas",
            f"Share of {words.noun} who live in {words.places}",
            percent(sum(need[i] for i in high), sum(need)),
            "percent",
            note="The comparison for the share of your people.",
            exact=before_rounding(sum(need[i] for i in high), sum(need)),
        ),
    ]


def _share_in_high_need(
    rows: list[_Row], high: tuple[int, ...], words: NeedWords, threshold: int
) -> Figure:
    """The share of people in high-need places, hidden when it gives a cell away."""
    figure_id = "share_of_people_in_high_need_areas"
    label = f"Share of your people who live in {words.places}"
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
    return Figure(
        figure_id,
        label,
        percent(part, sum(people)),
        "percent",
        exact=before_rounding(part, sum(people)),
    )


# --- what the person needs to know -----------------------------------------


def _answer(
    figures: list[Figure], priority: Table, words: NeedWords, guessed: bool
) -> str:
    """Say where need is high and how much of the charity's reach is there.

    When the area was worked out from where the people live, the sentence
    opens by saying so, because a door may show the sentence and no warning.
    """
    shown = values(figures)
    overall = shown["reach_per_100_in_need"]
    left_out = not_counted(
        shown["people_supplied"], shown["people_located"], shown["people_in_catchment"]
    )
    if shown["areas_compared"] == 1:
        return _answer_for_one_place(overall, words.per) + left_out
    places = high_need_places(shown["high_need_areas"], words.high)
    ours = shown["share_of_people_in_high_need_areas"]
    if ours is None:
        # The rate across the area is not hidden, so it carries the answer.
        mine = (
            f"the share of your people who do is {HIDDEN}. Across the area you "
            f"reached {number(overall)} people per 100 {words.per}."
        )
    else:
        mine = f"{number(ours)}% of your people do."
    first = look_first(priority, LOWEST, "people_per_100_in_need", overall, words.high)
    opening = (
        f"In the {shown['areas_compared']} local authorities where most of your "
        "people live, "
        if guessed
        else ""
    )
    return (
        f"{opening}{number(shown['share_of_need_in_high_need_areas'])}% of "
        f"{words.people} live in {places}, and {mine}{first}{left_out}"
    )


def _answer_for_one_place(reach: float | None, per: str) -> str:
    """Say that one place alone cannot be set against any other."""
    answer = (
        "Only one local authority is compared, so the analysis cannot say "
        "where need is high and your reach is low."
    )
    if reach is None:
        return answer
    return f"{answer} Across it you reached {number(reach)} people per 100 {per}."


def _choices(
    measure: Measure, compared: Compared, top: int, threshold: int, by_rate: bool
) -> tuple[Choice, ...]:
    """List the choices the analysis made."""
    words = need_words(measure.id == RESIDENTS.id)
    shading = Choice(
        id="map_need",
        label=f"How the map shades {words.topic}",
        value=_by_count(words)[0],
        reason=(
            "The need is every resident, so there is no rate to work out."
            if measure.id == RESIDENTS.id
            else "The need figures are kept on this machine and no copy of the "
            "residents is kept beside them, so there is nothing to set the "
            "count against. Keep the residents too and the map goes by rate."
        ),
    )
    if by_rate:
        shading = Choice(
            id="map_need",
            label="How the map shades need",
            value=NEED_BY_RATE[0],
            reason=(
                "A count would make the largest places darkest whatever their "
                "need. The list of places still goes by the count."
            ),
        )
    return (
        Choice(
            id="need",
            label=LABELS["need"],
            value=measure.label,
            reason=measure.reason,
            option="need",
        ),
        Choice(
            id="high_need",
            label=f"What counts as {words.high}",
            value=f"In the top quarter of the area you serve, by {words.noun}",
            reason=(
                "A quarter keeps the list to the places that stand out. The "
                "Smart Works study, which this follows, used the top half."
            ),
        ),
        Choice(
            id="catchment",
            label=LABELS["catchment"],
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
        shading,
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
            why="The analysis cannot tell which dates the rows are from.",
        ),
        Check(
            id="need_fits",
            question=f"Are these the people you are trying to reach: {measure.label}?",
            why=(
                "Reach is only meaningful against the people you are trying "
                f"to help. Change {said('need')} if another measure fits "
                "better."
            ),
        ),
        Check(
            id="catchment",
            question=f"Is this the area you serve: {compared.label}?",
            why=(
                "A place you could never reach is not a gap. Change "
                f"{said('catchment')} if it is not."
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


ANALYSIS = Analysis(info=INFO, run=run)
