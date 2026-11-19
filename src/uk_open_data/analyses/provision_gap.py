"""Provision gap: where is provision thin against need across a region?

Takes a charity's sites or services, each with a location and how much it
provides, totals the provision in each local authority, and sets it against
the people who live there or a count of people in need. It follows the method
of the Starlight case study, by local authority.

The analysis is about sites and what they provide, not about people, so it hides
no count. Counts of people belong in the need against reach analysis.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date
from typing import Any

import uk_open_data
from uk_open_data.analyses._answers import (
    IN_NEED,
    NeedWords,
    high_need_places,
    look_first,
    need_words,
    number,
    sentence_case,
    values,
)
from uk_open_data.analyses._inputs import is_blank
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
    high_need_cut,
    load_need,
    not_listed_rows,
    read_measure,
    read_top,
)
from uk_open_data.analyses._steps import (
    EVERYWHERE,
    HOW_TO_NAME_A_PLACE,
    LOCAL_AUTHORITY,
    POSTCODE_LOOKUP,
    Trail,
    bad_counts,
    before_rounding,
    percent,
    place_postcodes,
    plural,
    use_postcode_table,
)

ANALYSIS_ID = "provision-gap"
ANALYSIS_VERSION = "0.2"
KEY_FIGURES = (
    "share_of_provision_in_high_need_areas",
    "share_of_need_in_high_need_areas",
    "high_need_areas_without_provision",
)
LOWEST = "the thinnest provision"
NO_PROVISION = "None"
PROVISION_BANDS = (
    NO_PROVISION,
    "Lower provision",
    "Middle provision",
    "Higher provision",
)

INFO = AnalysisInfo(
    id=ANALYSIS_ID,
    title="Provision gap",
    question="Where is provision thin against need across a region?",
    summary=(
        "Totals what your sites or services provide in each local authority "
        "and sets it against the people who live there, or a count of people "
        "in need. It lists the high-need local authorities with the least "
        "provision per 1,000 people."
    ),
    version=ANALYSIS_VERSION,
    roles=(
        Role(
            name="postcode",
            description="The postcode of each site or service, one per row.",
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
            name="volume",
            description=(
                "How much the site or the area provides, as a number: "
                "sessions, places, boxes or hours. Not a count of people."
            ),
            example="120",
            amount=True,
        ),
    ),
    input_modes=(
        InputMode(
            name="sites",
            description=(
                "One row per site or service, with its postcode and how much it "
                "provides."
            ),
            roles=("postcode", "volume"),
        ),
        InputMode(
            name="area_volumes",
            description="One row per local authority, with how much is provided there.",
            roles=("local_authority", "volume"),
            aggregated=True,
        ),
        InputMode(
            name="site_list",
            description="One row per site or service, with its postcode alone.",
            roles=("postcode",),
        ),
    ),
    options=(
        POSTCODE_LOOKUP,
        Option(
            name="need",
            label=LABELS["need"],
            description=(
                "The people to set your provision against: one of "
                "the measures listed, or a table Nomis publishes by local "
                "authority, as {'dataset': a Nomis dataset id, 'label': what "
                "it counts, 'filters': the categories to add up}."
            ),
            default=RESIDENTS.id,
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
                "'England', 'Wales' or 'England and Wales'. Left empty, every "
                "local authority in England and Wales is compared."
            ),
            default=None,
        ),
        Option(
            name="top",
            label=LABELS["top"],
            description=(
                "How many high-need, low-provision places to list, from 1 to "
                f"{MAX_TOP}."
            ),
            default=DEFAULT_TOP,
        ),
    ),
    coverage=EVERYWHERE,
)

CAVEATS = (
    "Thin provision is not the same as unmet need. Another organisation may "
    "already provide in a place where you provide little.",
    "Provision is counted where a site is. People travel, so a site can serve "
    "the local authority next door.",
)
LARGE_PLACES_LISTED = (
    "Need is a count of people, so a large local authority is more likely to "
    "be listed as high need than a small one with the same rate."
)
# Every resident is not a need, so this says what the count is instead.
MOST_RESIDENTS_LISTED = (
    "The places listed are the ones with the most residents. That says where "
    "most people live, not where need is highest."
)


def _charts(words: NeedWords) -> tuple[Chart, ...]:
    """The two charts of the places listed, in the words that fit the measure."""
    counted = sentence_case(words.noun)
    return (
        Chart(
            id="need_in_priority_areas",
            title=f"{counted} in the places listed",
            table="priority_areas",
            category_column="geography_name",
            series=(ChartSeries("people_in_need", counted, "people"),),
        ),
        Chart(
            id="provision_in_priority_areas",
            title=f"Provision per 1,000 {words.noun} in the places listed",
            table="priority_areas",
            category_column="geography_name",
            series=(
                ChartSeries(
                    "volume_per_1000_in_need",
                    f"Provision per 1,000 {words.noun}",
                    "per_1000",
                ),
            ),
        ),
    )


@dataclass(frozen=True)
class _Row:
    """One local authority in the comparison."""

    authority: Authority
    volume: float
    high_need: bool
    need_band: str
    provision_band: str

    @property
    def rate(self) -> float | None:
        """Volume per 1,000 people in need, or None when nobody is in need."""
        return _per_1000(self.volume, self.authority.need)


def run(analysis_input: AnalysisInput) -> AnalysisResult:
    """Run the analysis. Use :func:`uk_open_data.analyses.run_analysis` to call it."""
    options = analysis_input.options
    top = read_top(options)
    measure = read_measure(options.get("need"))
    mode = analysis_input.mode.name
    trail = Trail()
    authorities = load_need(measure, trail)
    if mode == "area_volumes":
        volumes, supplied = _volume_by_authority(
            analysis_input.values["local_authority"],
            analysis_input.values["volume"],
            authorities,
            trail,
        )
    else:
        postcodes = analysis_input.values["postcode"]
        amounts = (
            _amounts(analysis_input.values["volume"])
            if mode == "sites"
            else [1.0] * len(postcodes)
        )
        volumes, supplied = _volume_by_postcode(
            postcodes, amounts, use_postcode_table(options), trail
        )
    located = _keep_listed(volumes, authorities, trail)
    compared = choose_compared(options.get("catchment"), authorities)
    words = need_words(measure.id == RESIDENTS.id)
    rows = _rows(located, authorities, compared, words, trail)
    figures = _figures(supplied, sum(located.values()), rows, words, measure)
    tables = (_priority_table(rows, top, words, trail), _authority_table(rows, words))
    return AnalysisResult(
        analysis_id=ANALYSIS_ID,
        analysis_version=ANALYSIS_VERSION,
        package_version=uk_open_data.__version__,
        run_on=date.today().isoformat(),
        input_mode=mode,
        figures=tuple(figures),
        tables=tables,
        map=_map_spec(words, rows),
        working=tuple(trail.working),
        choices=(*trail.choices, *_choices(measure, words, compared, top)),
        checks=_checks(mode, measure, compared),
        caveats=(*CAVEATS, _how_listed(words), measure.caveat),
        warnings=tuple(trail.warnings),
        sources=tuple(trail.sources),
        privacy=Privacy(
            suppress_below=None,
            cells_suppressed=0,
            row_level_output=False,
            sent_to_third_parties=tuple(trail.sent),
            notes=(
                "This analysis is about sites and what they provide, not about "
                "people, so it hides no count.",
                "The result holds totals for local authorities. It names no "
                "site and repeats no postcode.",
                "Where a local authority holds one site, the provision shown "
                "for it is that site's.",
                "The need figures are public counts and are shown in full.",
            ),
        ),
        charts=_charts(words),
        answer=_answer(figures, tables[0], measure),
        key_figures=KEY_FIGURES,
    )


# --- reading the input -----------------------------------------------------


def _amount(raw: Any) -> float | None:
    """Read one volume: a number of zero or more, or None when it is not one."""
    if isinstance(raw, bool) or is_blank(raw):
        return None
    try:
        amount = float(str(raw).replace(",", "").strip())
    except ValueError:
        return None
    return amount if 0 <= amount < float("inf") else None


def _amounts(raw: list[Any]) -> list[float]:
    """Read the volume column, and stop when a row has no usable number."""
    amounts = [_amount(value) for value in raw]
    bad = [row for row, amount in enumerate(amounts, start=1) if amount is None]
    if bad:
        what = "provision that is not a number of zero or more"
        raise AnalysisInputError(bad_counts(bad, what), role="volume")
    return [amount or 0.0 for amount in amounts]


def _volume_by_postcode(
    postcodes: list[Any], amounts: list[float], use_table: bool, trail: Trail
) -> tuple[Counter[str], float]:
    """Place each site in a local authority and total the volume there.

    Returns:
        Volume per local authority code, and the volume supplied.
    """
    placed = place_postcodes(postcodes, use_table, trail, LOCAL_AUTHORITY)
    totals: Counter[str] = Counter()
    for code, amount in zip(placed, amounts, strict=True):
        if code is not None:
            totals[code] += amount
    not_placed = sum(
        amount for code, amount in zip(placed, amounts, strict=True) if code is None
    )
    if not_placed:
        trail.warnings.append(
            f"Provision of {_tidy(not_placed):,} is at sites that could not be "
            "placed, and is left out."
        )
    return totals, sum(amounts)


def _volume_by_authority(
    places: list[Any],
    raw: list[Any],
    authorities: dict[str, Authority],
    trail: Trail,
) -> tuple[Counter[str], float]:
    """Total the volume given for each local authority name or code."""
    amounts = _amounts(raw)
    by_key = {code.casefold(): code for code in authorities}
    by_key.update({area.name.casefold(): code for code, area in authorities.items()})
    totals: Counter[str] = Counter()
    blank = 0
    not_listed: list[int] = []
    for row, (place, amount) in enumerate(zip(places, amounts, strict=True), start=1):
        if is_blank(place):
            blank += 1
            continue
        code = by_key.get(str(place).strip().casefold())
        if code is None:
            not_listed.append(row)
        totals[code or ""] += amount
    unknown = len(not_listed)
    if blank:
        trail.warnings.append(f"{plural(blank, 'row')} had no local authority.")
    if unknown:
        trail.warnings.append(not_listed_rows(not_listed))
    trail.working.append(
        Step(
            title="Read the provision by local authority",
            detail=(
                f"{len(places)} rows holding provision of "
                f"{_tidy(sum(amounts)):,}. {blank} rows had no local "
                f"authority and were left out. {unknown} rows named a place "
                "the need figures do not list."
            ),
            rows_in=len(places),
            rows_out=len(places) - blank,
        )
    )
    return totals, sum(amounts)


def _keep_listed(
    volumes: Counter[str], authorities: dict[str, Authority], trail: Trail
) -> dict[str, float]:
    """Keep the volume placed in a local authority the need figures list."""
    located: dict[str, float] = {
        code: amount
        for code, amount in volumes.items()
        if code in authorities and amount > 0
    }
    inside = sum(located.values())
    outside = sum(volumes.values()) - inside
    trail.working.append(
        Step(
            title="Joined provision to the need figures",
            detail=(
                f"Provision of {_tidy(inside):,} is in a local authority the "
                f"need figures list. {_tidy(outside):,} is outside England "
                "and Wales, or in a local authority the figures do not list."
            ),
        )
    )
    if outside:
        trail.warnings.append(
            f"Provision of {_tidy(outside):,} was placed outside England and "
            "Wales, or in a local authority the need figures do not list "
            "(for example one whose boundary has changed). It is left out."
        )
    if not located:
        msg = (
            "None of the provision could be placed in a local authority in "
            "England or Wales. Check the column that says where each row is. "
            f"{HOW_TO_NAME_A_PLACE} A postcode must be a full one in England "
            "or Wales."
        )
        raise AnalysisInputError(msg)
    return located


# --- the comparison --------------------------------------------------------


def _rows(
    located: dict[str, float],
    authorities: dict[str, Authority],
    compared: Compared,
    words: NeedWords,
    trail: Trail,
) -> list[_Row]:
    """Build one row per local authority compared."""
    if not compared.codes:
        msg = (
            f"The need figures list no local authority in {compared.label}. "
            f"Check {said('catchment')}."
        )
        raise AnalysisInputError(msg, option="catchment")
    volume = [located.get(code, 0.0) for code in compared.codes]
    need = [authorities[code].need for code in compared.codes]
    inside = sum(volume)
    with_provision = sum(1 for amount in volume if amount > 0)
    trail.working.append(
        Step(
            title="Set the area you serve",
            detail=(
                f"Area: {compared.label}. {compared.reason} Of the provision "
                f"of {_tidy(sum(located.values())):,} placed, {_tidy(inside):,} "
                f"is in it, in {with_provision} of its {len(volume)} local "
                "authorities."
            ),
        )
    )
    if not inside:
        msg = (
            f"None of the provision is in the area you serve ({compared.label}). "
            f"Check {said('catchment')}."
        )
        raise AnalysisInputError(msg, option="catchment")
    _warn_about_area(sum(located.values()) - inside, with_provision, compared, trail)
    cut = high_need_cut(need)
    high = [amount >= cut and amount > 0 for amount in need]
    need_bands = band_by_need(need)
    provision_bands = _provision_bands(volume, need)
    trail.working.append(
        Step(
            title=f"Set provision against {words.topic}",
            detail=(
                "For each local authority, the provision was divided by "
                f"the number of {words.noun} and multiplied by 1,000. A "
                f"local authority {words.rule} when its count of "
                f"{words.noun} is in the top quarter of the area (at or "
                f"above {round(cut):,})."
            ),
        )
    )
    return [
        _Row(
            authority=authorities[code],
            volume=volume[i],
            high_need=high[i],
            need_band=need_bands[i],
            provision_band=provision_bands[i],
        )
        for i, code in enumerate(compared.codes)
    ]


def _warn_about_area(
    outside: float, with_provision: int, compared: Compared, trail: Trail
) -> None:
    """Warn when the area looks too wide, too narrow or too small."""
    if outside:
        trail.warnings.append(
            f"Provision of {_tidy(outside):,} is outside the area you serve and "
            f"is left out. Change {said('catchment')} to include it."
        )
    if not compared.named and with_provision * FEW_AREAS < len(compared.codes):
        trail.warnings.append(
            f"No area was given, so all {len(compared.codes)} local "
            f"authorities in {compared.label} are looked at, and you provide "
            f"in {with_provision} of them. If you serve a smaller area, fill "
            f"in {said('catchment')}, so that places you could not reach are "
            "not listed as gaps."
        )
    if len(compared.codes) < len(NEED_BANDS):
        trail.warnings.append(
            f"Only {len(compared.codes)} local authorities are compared, so "
            "'high need' says little. It means the top quarter, and at least "
            "one place."
        )


def _per_1000(volume: float, need: float) -> float | None:
    """Return volume per 1,000 people in need, or None when nobody is in need."""
    return round(1000 * volume / need, 2) if need else None


def _tidy(amount: float) -> float | int:
    """Return a volume as a whole number when it is one, for showing."""
    rounded = round(amount, 2)
    return int(rounded) if rounded == int(rounded) else rounded


def _provision_bands(volume: list[float], need: list[float]) -> list[str]:
    """Put each local authority with provision in a third by its rate."""
    shown = [i for i, amount in enumerate(volume) if amount > 0 and need[i] > 0]
    part = equal_parts([volume[i] / need[i] for i in shown], 3)
    bands = [NO_PROVISION] * len(volume)
    for position, i in enumerate(shown):
        bands[i] = PROVISION_BANDS[1 + part[position]]
    return bands


# --- tables ----------------------------------------------------------------


def _table_row(row: _Row) -> dict[str, Any]:
    """The columns both tables share."""
    return {
        "geography_code": row.authority.code,
        "geography_name": row.authority.name,
        "people_in_need": round(row.authority.need),
        "volume": _tidy(row.volume),
        "volume_per_1000_in_need": row.rate,
    }


def _priority_table(
    rows: list[_Row], top: int, words: NeedWords, trail: Trail
) -> Table:
    """The high-need local authorities with the least provision."""
    high = [row for row in rows if row.high_need]
    ranked = sorted(
        high,
        key=lambda row: (
            row.volume / row.authority.need,
            -row.authority.need,
            row.authority.code,
        ),
    )[:top]
    trail.working.append(
        Step(
            title=f"Listed the places with {words.high} and thin provision",
            detail=(
                f"The {len(high)} places with {words.high} were put in "
                f"order of provision per 1,000 {words.noun}, lowest "
                f"first, and then by {words.topic}, highest first. The first "
                f"{len(ranked)} are listed."
            ),
        )
    )
    return Table(
        id="priority_areas",
        title=f"Places with {words.high}, thinnest provision first",
        headings=words.headings(),
        columns=(
            "rank",
            "geography_code",
            "geography_name",
            "people_in_need",
            "volume",
            "volume_per_1000_in_need",
        ),
        rows=[{"rank": rank, **_table_row(row)} for rank, row in enumerate(ranked, 1)],
    )


def _authority_table(rows: list[_Row], words: NeedWords) -> Table:
    """Every local authority compared, for the map and for a closer look."""
    return Table(
        id="by_local_authority",
        headings=words.headings(),
        title=(
            f"{sentence_case(words.topic)} and provision in every local "
            "authority in the area you serve"
        ),
        columns=(
            "geography_code",
            "geography_name",
            "people_in_need",
            "need_band",
            "high_need",
            "volume",
            "volume_per_1000_in_need",
            "provision_band",
        ),
        rows=[
            {
                **_table_row(row),
                "need_band": row.need_band,
                "high_need": row.high_need,
                "provision_band": row.provision_band,
            }
            for row in rows
        ],
        detail=True,
    )


def _how_listed(words: NeedWords) -> str:
    """The caveat about what puts a place on the list, for the measure."""
    return LARGE_PLACES_LISTED if words is IN_NEED else MOST_RESIDENTS_LISTED


def _map_spec(words: NeedWords, rows: list[_Row]) -> MapSpec:
    """Describe the map of need and provision, in the words for the measure.

    Each note says how few places were grouped, when there are fewer than
    the key has groups.
    """
    provided = sum(row.provision_band != NO_PROVISION for row in rows)
    return MapSpec(
        title=f"{sentence_case(words.topic)} and provision, by local authority",
        geography_type="LAD",
        geography_year=2023,
        table="by_local_authority",
        code_column="geography_code",
        layers=(
            MapLayer(
                id="need",
                label=sentence_case(words.noun),
                value_column="need_band",
                kind="ordinal",
                note=(
                    f"Local authorities in five equal groups by {words.noun}."
                    f"{few_in_need_bands(len(rows))}"
                ),
                categories=NEED_BANDS,
            ),
            MapLayer(
                id="provision",
                label=f"Provision per 1,000 {words.noun}",
                value_column="provision_band",
                kind="ordinal",
                note=(
                    "Local authorities where you provide are in three equal "
                    "groups. The lowest band holds places where you provide "
                    "nothing." + few_places(provided, len(PROVISION_BANDS) - 1)
                ),
                categories=PROVISION_BANDS,
            ),
        ),
    )


# --- figures ---------------------------------------------------------------


def _figures(
    supplied: float,
    located: float,
    rows: list[_Row],
    words: NeedWords,
    measure: Measure,
) -> list[Figure]:
    """Build the headline figures, in the words that fit the measure."""
    volume = [row.volume for row in rows]
    need = [row.authority.need for row in rows]
    high = [i for i, row in enumerate(rows) if row.high_need]
    in_catchment = sum(volume)
    return [
        Figure(
            "volume_supplied",
            "Provision in the data you gave",
            _tidy(supplied),
            "count",
        ),
        Figure(
            "volume_located",
            "Provision placed in a local authority in England or Wales",
            _tidy(located),
            "count",
        ),
        Figure(
            "volume_in_catchment",
            "Provision in the area you serve",
            _tidy(in_catchment),
            "count",
            note="The figures below are about this provision.",
        ),
        Figure(
            "areas_compared",
            "Local authorities in the area you serve",
            len(rows),
            "areas",
        ),
        Figure(
            "areas_without_provision",
            "Local authorities where you provide nothing",
            sum(1 for amount in volume if not amount),
            "areas",
        ),
        Figure(
            "people_in_need",
            f"{words.counted} in the area you serve ({measure.label})",
            round(sum(need)),
            "people",
        ),
        Figure(
            "volume_per_1000_in_need",
            f"Provision per 1,000 {words.noun}, across the area",
            _per_1000(in_catchment, sum(need)),
            "per_1000",
            exact=before_rounding(in_catchment, sum(need), 1000),
        ),
        Figure(
            "high_need_areas",
            f"Local authorities with {words.high}",
            len(high),
            "areas",
            note=f"The top quarter of the places in it, by {words.noun}.",
        ),
        Figure(
            "high_need_areas_without_provision",
            f"{sentence_case(words.places)} where you provide nothing",
            sum(1 for i in high if not volume[i]),
            "areas",
        ),
        Figure(
            "share_of_provision_in_high_need_areas",
            f"Share of your provision that is in {words.places}",
            percent(sum(volume[i] for i in high), in_catchment),
            "percent",
            exact=before_rounding(sum(volume[i] for i in high), in_catchment),
        ),
        Figure(
            "share_of_need_in_high_need_areas",
            f"Share of {words.noun} who live in those local authorities",
            percent(sum(need[i] for i in high), sum(need)),
            "percent",
            note="Compare this with the share of your provision.",
            exact=before_rounding(sum(need[i] for i in high), sum(need)),
        ),
    ]


# --- what the person needs to know -----------------------------------------


def _answer(figures: list[Figure], priority: Table, measure: Measure) -> str:
    """Say where need is high and how much of the provision is there."""
    shown = values(figures)
    words = need_words(measure.id == RESIDENTS.id)
    places = high_need_places(shown["high_need_areas"], words.high)
    first = look_first(
        priority,
        LOWEST,
        "volume_per_1000_in_need",
        shown["volume_per_1000_in_need"],
        words.high,
    )
    return (
        f"{number(shown['share_of_need_in_high_need_areas'])}% of {words.people} "
        f"live in {places}, and "
        f"{number(shown['share_of_provision_in_high_need_areas'])}% of your "
        f"provision is there.{first}"
    )


def _choices(
    measure: Measure, words: NeedWords, compared: Compared, top: int
) -> tuple[Choice, ...]:
    """List the choices the analysis made."""
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
            reason="A quarter keeps the list to the places that stand out.",
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
    )


def _checks(mode: str, measure: Measure, compared: Compared) -> tuple[Check, ...]:
    """List what a person must confirm before using the figures."""
    if mode == "site_list":
        first = Check(
            id="sites_alike",
            question="Do your sites each provide about the same amount?",
            why=(
                "With no column for how much each site provides, every site "
                "counts as one. Add one if some sites provide much more than "
                "others."
            ),
        )
    else:
        first = Check(
            id="volume_is_provision",
            question=(
                "Is the provision a count of sessions, places, boxes or hours, "
                "and not of people?"
            ),
            why=(
                "This analysis shows provision as it is. Counts of people "
                "belong in the need against reach analysis, which hides small "
                "counts."
            ),
        )
    return (
        first,
        Check(
            id="everything_listed",
            question="Does the data list everything you provide in the area?",
            why="A site left out makes its local authority look like a gap.",
        ),
        Check(
            id="period",
            question="Does the data cover the period you are reporting on?",
            why="The analysis cannot tell which dates the rows are from.",
        ),
        Check(
            id="need_fits",
            question=f"Are these the people you provide for: {measure.label}?",
            why=(
                "Provision is only meaningful against the people it is for. "
                f"Change {said('need')} if another measure fits better."
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


ANALYSIS = Analysis(info=INFO, run=run)
