"""Access and distance: how far are people from our nearest site?

Takes where a charity's sites or service points are, measures the straight-line
distance from the centre of each local authority of England and Wales to the
nearest one, and lists the places where the most people are far from a site.
It follows the method of the Material Focus case study.

The analysis is about sites, not about people, so it hides no count. Distance is
in a straight line: the package has no road or public transport times.

Site postcodes can be placed without leaving this machine. With a postcode
table installed and the centres of neighbourhoods kept, each site is placed at
the centre of its neighbourhood and no postcode is sent anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import uk_open_data
from uk_open_data.analyses._answers import (
    AREA,
    column,
    need_words,
    number,
    values,
)
from uk_open_data.analyses._centres import centres_path as centres_path
from uk_open_data.analyses._centres import clear_centres_cache as clear_centres_cache
from uk_open_data.analyses._centres import (
    distance_km,
    load_centres,
    locate_in_neighbourhoods,
)
from uk_open_data.analyses._centres import download_centres as download_centres
from uk_open_data.analyses._centres import keep_centres as keep_centres
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
    MAX_TOP,
    MEASURES,
    NEED_BANDS,
    RESIDENTS,
    Authority,
    Compared,
    Measure,
    band_by_need,
    choose_compared,
    few_in_need_bands,
    load_need,
    read_measure,
    read_top,
)
from uk_open_data.analyses._steps import (
    EVERYWHERE,
    POSTCODE_LOOKUP,
    Position,
    Trail,
    before_rounding,
    locate_postcodes,
    percent,
    use_postcode_table,
)

ANALYSIS_ID = "access-distance"
ANALYSIS_VERSION = "0.1"
KEY_FIGURES = (
    "average_distance_km",
    "share_of_people_within_reach",
    "areas_beyond_reach",
)
DEFAULT_WITHIN_KM = 10
MAX_WITHIN_KM = 500
# A position outside this box is not in the United Kingdom. A latitude and a
# longitude that were swapped fall outside it.
UK_LATITUDE = (49.0, 61.5)
UK_LONGITUDE = (-9.0, 2.5)
# Where each band of distance starts, in kilometres.
BAND_STARTS = (5, 10, 20, 40)
DISTANCE_BANDS = (
    "Under 5 km",
    "5 to under 10 km",
    "10 to under 20 km",
    "20 to under 40 km",
    "40 km or more",
)

INFO = AnalysisInfo(
    id=ANALYSIS_ID,
    title="Access and distance",
    question="How far are people from our nearest site, and where would a new "
    "site help most?",
    summary=(
        "Measures the straight-line distance from the centre of each local "
        "authority to your nearest site, and says what share of people are "
        "within reach. It lists the local authorities where the most people "
        "are far from a site."
    ),
    version=ANALYSIS_VERSION,
    roles=(
        Role(
            name="latitude",
            description="The latitude of each site, in degrees, one site per row.",
            example="51.4613",
        ),
        Role(
            name="longitude",
            description="The longitude of each site, in degrees. West is negative.",
            example="-0.0117",
        ),
        Role(
            name="postcode",
            description="The postcode of each site, one site per row.",
            example="SE13 7VC",
        ),
    ),
    input_modes=(
        InputMode(
            name="site_coordinates",
            description="One row per site, with its latitude and longitude.",
            roles=("latitude", "longitude"),
        ),
        InputMode(
            name="site_postcodes",
            description=(
                "One row per site, with its postcode. With a postcode table "
                "and the centres of neighbourhoods on this machine, each site "
                "is placed at the centre of its neighbourhood and no postcode "
                "is sent anywhere. Otherwise the postcodes are sent to "
                "postcodes.io."
            ),
            roles=("postcode",),
        ),
    ),
    options=(
        POSTCODE_LOOKUP,
        Option(
            name="need",
            label=LABELS["need"],
            description=(
                "The people to measure distance for: one of "
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
            name="within_km",
            label=LABELS["within_km"],
            description=(
                "How many kilometres from a site counts as within reach, "
                f"above 0 and up to {MAX_WITHIN_KM}."
            ),
            default=DEFAULT_WITHIN_KM,
        ),
        Option(
            name="top",
            label=LABELS["top"],
            description=(
                f"How many places far from a site to list, from 1 to {MAX_TOP}."
            ),
            default=DEFAULT_TOP,
        ),
    ),
    coverage=EVERYWHERE,
)

CAVEATS = (
    "Distance is in a straight line. Roads, rivers, hills and public transport "
    "can make a short distance a long journey.",
    "Distance is measured from the centre of each local authority, not from "
    "where each person lives. In a large local authority many people are much "
    "nearer or much farther than the figure says, and a site can be inside "
    "the place and still be far from its centre.",
    "The figures say how far people are from a site. They do not say how far "
    "the people you see travel, or whether anyone far away needs you.",
)

PLACED_IN_NEIGHBOURHOODS = (
    "Each site is placed at the centre of its neighbourhood, not at its "
    "postcode. In a town that moves a site by a few hundred metres. In the "
    "countryside it can move it by a few kilometres."
)

CHARTS = (
    Chart(
        id="people_in_priority_areas",
        title="People in the places listed",
        table="priority_areas",
        category_column="geography_name",
        series=(ChartSeries("people_in_need", "People", "people"),),
    ),
    Chart(
        id="distance_in_priority_areas",
        title="Distance from the centre of each place listed to your nearest site",
        table="priority_areas",
        category_column="geography_name",
        series=(ChartSeries("distance_km", "Kilometres", "km"),),
    ),
)


@dataclass(frozen=True)
class _Row:
    """One local authority in the comparison."""

    authority: Authority
    distance: float
    within_reach: bool
    need_band: str

    @property
    def distance_band(self) -> str:
        """The band of distance the local authority is in."""
        return DISTANCE_BANDS[sum(1 for start in BAND_STARTS if self.distance >= start)]


def run(analysis_input: AnalysisInput) -> AnalysisResult:
    """Run the analysis. Use :func:`uk_open_data.analyses.run_analysis` to call it."""
    options = analysis_input.options
    top = read_top(options)
    within = _within_km(options)
    measure = read_measure(options.get("need"))
    use_table = use_postcode_table(options)
    mode = analysis_input.mode.name
    trail = Trail()
    authorities = load_need(measure, trail)
    centres = load_centres(trail)
    if mode == "site_coordinates":
        sites, supplied = _read_positions(
            analysis_input.values["latitude"], analysis_input.values["longitude"], trail
        )
    else:
        postcodes = analysis_input.values["postcode"]
        locate = locate_in_neighbourhoods if use_table else locate_postcodes
        placed = locate(postcodes, trail)
        sites = _in_the_uk([p for p in placed if p is not None], trail)
        supplied = len(postcodes)
    compared = choose_compared(options.get("catchment"), authorities)
    rows = _rows(sites, authorities, centres, compared, within, trail)
    figures = _figures(supplied, len(sites), rows, measure, within)
    headings = need_words(measure.id == RESIDENTS.id).headings()
    tables = (
        _priority_table(rows, top, within, headings, trail),
        _authority_table(rows, headings),
    )
    return AnalysisResult(
        analysis_id=ANALYSIS_ID,
        analysis_version=ANALYSIS_VERSION,
        package_version=uk_open_data.__version__,
        run_on=date.today().isoformat(),
        input_mode=mode,
        figures=tuple(figures),
        tables=tables,
        map=_map_spec(len(rows)),
        working=tuple(trail.working),
        choices=(*trail.choices, *_choices(measure, compared, within, top)),
        checks=_checks(measure, compared),
        caveats=(*CAVEATS, *_placing_caveat(mode, use_table), measure.caveat),
        warnings=tuple(trail.warnings),
        sources=tuple(trail.sources),
        privacy=Privacy(
            suppress_below=None,
            cells_suppressed=0,
            row_level_output=False,
            sent_to_third_parties=tuple(trail.sent),
            notes=(
                "This analysis is about sites, not about people, so it hides no count.",
                "The result holds distances and public counts for local "
                "authorities. It names no site and repeats no postcode or "
                "position.",
                "Distances are given to the nearest kilometre. Even so, the "
                "distances from several local authorities can show roughly "
                "where a site is. Do not share the result if a site's address "
                "is confidential.",
                "The need figures are public counts and are shown in full.",
            ),
        ),
        charts=CHARTS,
        answer=_answer(figures, tables[0], within, measure),
        key_figures=KEY_FIGURES,
    )


# --- options ---------------------------------------------------------------


def _within_km(options: dict[str, Any]) -> float:
    """Read and check the distance that counts as within reach."""
    value = options.get("within_km")
    if isinstance(value, bool) or not isinstance(value, int | float):
        msg = f"{said('within_km')} must be a number."
        raise AnalysisInputError(msg, option="within_km")
    if not 0 < value <= MAX_WITHIN_KM:
        msg = f"{said('within_km')} must be above 0 and up to {MAX_WITHIN_KM}."
        raise AnalysisInputError(msg, option="within_km")
    return value


def _placing_caveat(mode: str, use_table: bool) -> tuple[str, ...]:
    """The caveat for sites placed at the centre of their neighbourhood."""
    if mode == "site_postcodes" and use_table:
        return (PLACED_IN_NEIGHBOURHOODS,)
    return ()


# --- reading the input -----------------------------------------------------


def _degrees(raw: Any) -> float | None:
    """Read one latitude or longitude, or None when it is not a number."""
    if isinstance(raw, bool) or is_blank(raw):
        return None
    try:
        value = float(str(raw).strip())
    except ValueError:
        return None
    return value if -180 <= value <= 180 else None


def _read_positions(
    latitudes: list[Any], longitudes: list[Any], trail: Trail
) -> tuple[list[Position], int]:
    """Read the position of each site.

    Returns:
        The positions in the United Kingdom, and the number of rows supplied.
    """
    supplied = len(latitudes)
    read = [
        (_degrees(latitude), _degrees(longitude))
        for latitude, longitude in zip(latitudes, longitudes, strict=True)
    ]
    positions = [
        (latitude, longitude)
        for latitude, longitude in read
        if latitude is not None and longitude is not None
    ]
    unreadable = supplied - len(positions)
    trail.working.append(
        Step(
            title="Read the site positions",
            detail=(
                f"{supplied} rows. {unreadable} had no latitude or longitude, "
                "or one that is not a number of degrees, and were left out."
            ),
            rows_in=supplied,
            rows_out=len(positions),
        )
    )
    if unreadable:
        trail.warnings.append(
            f"{unreadable} rows had no latitude or longitude, or one that is "
            "not a number of degrees."
        )
    return _in_the_uk(positions, trail), supplied


def _in_the_uk(positions: list[Position], trail: Trail) -> list[Position]:
    """Keep the positions in the United Kingdom, and stop when there is none."""
    inside = [
        (latitude, longitude)
        for latitude, longitude in positions
        if UK_LATITUDE[0] <= latitude <= UK_LATITUDE[1]
        and UK_LONGITUDE[0] <= longitude <= UK_LONGITUDE[1]
    ]
    outside = len(positions) - len(inside)
    if outside:
        trail.warnings.append(
            f"{outside} rows hold a position outside the United Kingdom and "
            "were left out. Check that latitude and longitude are not swapped."
        )
    if not inside:
        msg = (
            "None of the rows holds a position in the United Kingdom. Check "
            "the columns chosen, and that latitude and longitude are not "
            "swapped."
        )
        raise AnalysisInputError(msg)
    return inside


# --- the comparison --------------------------------------------------------


def _rows(
    sites: list[Position],
    authorities: dict[str, Authority],
    centres: dict[str, Position],
    compared: Compared,
    within: float,
    trail: Trail,
) -> list[_Row]:
    """Build one row per local authority compared that has a centre."""
    codes = [code for code in compared.codes if code in centres]
    missing = len(compared.codes) - len(codes)
    if missing:
        trail.warnings.append(
            f"{missing} local authorities in the area you serve have no "
            "centre in the boundary figures and are left out."
        )
    if not codes:
        msg = (
            f"No local authority in {compared.label} has both need figures "
            f"and a centre. Check {said('catchment')}."
        )
        raise AnalysisInputError(msg, option="catchment")
    need_bands = band_by_need([authorities[code].need for code in codes])
    distances = [
        round(min(distance_km(centres[code], site) for site in sites)) for code in codes
    ]
    trail.working.append(
        Step(
            title="Measured the distance to the nearest site",
            detail=(
                f"Area: {compared.label}. {compared.reason} For each of its "
                f"{len(codes)} local authorities, the straight-line distance "
                f"from its centre to the nearest of your {len(sites)} sites "
                "was measured, to the nearest kilometre. A site outside the "
                "area still counts as the nearest when it is. A local "
                f"authority is within reach when that distance is {within:g} "
                "km or less."
            ),
        )
    )
    return [
        _Row(
            authority=authorities[code],
            distance=distances[i],
            within_reach=distances[i] <= within,
            need_band=need_bands[i],
        )
        for i, code in enumerate(codes)
    ]


# --- tables ----------------------------------------------------------------


def _table_row(row: _Row) -> dict[str, Any]:
    """The columns both tables share."""
    return {
        "geography_code": row.authority.code,
        "geography_name": row.authority.name,
        "people_in_need": round(row.authority.need),
        "distance_km": row.distance,
    }


def _priority_table(
    rows: list[_Row],
    top: int,
    within: float,
    headings: dict[str, str],
    trail: Trail,
) -> Table:
    """The local authorities beyond reach, with the most people first."""
    beyond = [row for row in rows if not row.within_reach]
    ranked = sorted(
        beyond,
        key=lambda row: (-row.authority.need, -row.distance, row.authority.code),
    )[:top]
    trail.working.append(
        Step(
            title="Listed the places far from a site",
            detail=(
                f"The {len(beyond)} local authorities whose centre is more "
                f"than {within:g} km from a site were put in order of people, "
                f"most first. The first {len(ranked)} are listed."
            ),
        )
    )
    if not beyond:
        trail.warnings.append(
            "The centre of every local authority in the area you serve is "
            f"within {within:g} km of a site, so no place is listed. Lower "
            f"{said('within_km')} to list the farthest."
        )
    return Table(
        id="priority_areas",
        title="Far from a site: the places where a new site would reach most people",
        columns=(
            "rank",
            "geography_code",
            "geography_name",
            "people_in_need",
            "distance_km",
        ),
        rows=[{"rank": rank, **_table_row(row)} for rank, row in enumerate(ranked, 1)],
        headings=headings,
    )


def _authority_table(rows: list[_Row], headings: dict[str, str]) -> Table:
    """Every local authority compared, for the map and for a closer look."""
    return Table(
        id="by_local_authority",
        title=(
            "People and distance to a site in every local authority in the "
            "area you serve"
        ),
        columns=(
            "geography_code",
            "geography_name",
            "people_in_need",
            "need_band",
            "distance_km",
            "distance_band",
            "within_reach",
        ),
        rows=[
            {
                **_table_row(row),
                "need_band": row.need_band,
                "distance_band": row.distance_band,
                "within_reach": row.within_reach,
            }
            for row in rows
        ],
        detail=True,
        headings=headings,
    )


def _map_spec(places: int) -> MapSpec:
    """Describe the map of distance and people.

    The note on people says how few places were grouped, when there are
    fewer than the key has groups.
    """
    return MapSpec(
        title="Distance to your nearest site, by local authority",
        geography_type="LAD",
        geography_year=2023,
        table="by_local_authority",
        code_column="geography_code",
        layers=(
            MapLayer(
                id="distance",
                label="Distance to your nearest site",
                value_column="distance_band",
                kind="ordinal",
                note=(
                    "Straight-line distance from the centre of each local "
                    "authority to your nearest site."
                ),
                categories=DISTANCE_BANDS,
            ),
            MapLayer(
                id="need",
                label="People",
                value_column="need_band",
                kind="ordinal",
                note=(
                    "Local authorities in five equal groups by people."
                    f"{few_in_need_bands(places)}"
                ),
                categories=NEED_BANDS,
            ),
        ),
    )


# --- figures ---------------------------------------------------------------


def _figures(
    supplied: int, located: int, rows: list[_Row], measure: Measure, within: float
) -> list[Figure]:
    """Build the headline figures."""
    need = [row.authority.need for row in rows]
    beyond = [row for row in rows if not row.within_reach]
    people = sum(need)
    travelled = sum(row.authority.need * row.distance for row in rows)
    return [
        Figure("sites_supplied", "Sites in the data you gave", supplied, "count"),
        Figure(
            "sites_located",
            "Sites placed in the United Kingdom",
            located,
            "count",
            note="Distances are measured to these sites.",
        ),
        Figure(
            "areas_compared",
            "Local authorities in the area you serve",
            len(rows),
            "areas",
        ),
        Figure(
            "people_in_need",
            f"People in the area you serve ({measure.label})",
            round(people),
            "people",
        ),
        Figure(
            "average_distance_km",
            "Average distance from the centre of each person's local authority "
            "to your nearest site",
            round(travelled / people, 1) if people else None,
            "km",
            note=(
                "Each person is counted at the centre of their local "
                "authority, so a place with many people counts for more."
            ),
            # Worked out from distances already rounded to the kilometre, so
            # it says no more about where a site is than the table does.
            exact=before_rounding(travelled, people, 1),
        ),
        Figure(
            "share_of_people_within_reach",
            "Share of people in a local authority whose centre is within "
            f"{within:g} km of a site",
            percent(people - sum(row.authority.need for row in beyond), people),
            "percent",
            exact=before_rounding(
                people - sum(row.authority.need for row in beyond), people
            ),
        ),
        Figure(
            "people_beyond_reach",
            "People in a local authority whose centre is more than "
            f"{within:g} km from a site",
            round(sum(row.authority.need for row in beyond)),
            "people",
        ),
        Figure(
            "areas_beyond_reach",
            f"Local authorities whose centre is more than {within:g} km from a site",
            len(beyond),
            "areas",
        ),
        Figure(
            "farthest_distance_km",
            "Distance from the centre of the farthest local authority to a site",
            max(row.distance for row in rows),
            "km",
        ),
    ]


# --- what the person needs to know -----------------------------------------


def _answer(
    figures: list[Figure], priority: Table, within: float, measure: Measure
) -> str:
    """Say how far people are from a site and where a new one would help most."""
    shown = values(figures)
    who = "residents" if measure.id == RESIDENTS.id else "people in need"
    first = (
        f"Counting each person at the centre of their local authority, {who} "
        f"are {number(shown['average_distance_km'])} km from your nearest site "
        f"on average, and {_share_within(shown)} are within {within:g} km of one."
    )
    places = column(priority, "geography_name")
    if not places:
        return f"{first} No local authority in {AREA} is farther away than that."
    return (
        f"{first} Of the places farther away, a new site would reach most "
        f"{who} in {places[0]}."
    )


def _share_within(shown: dict[str, Any]) -> str:
    """The share of people within reach, in words when it is all or none.

    A share can round to 0.0% or 100.0% while a few places fall the other
    side, so the words are used only when every place does.
    """
    if shown["areas_beyond_reach"] == shown["areas_compared"]:
        return "none"
    if shown["areas_beyond_reach"] == 0:
        return "all"
    return f"{number(shown['share_of_people_within_reach'])}%"


def _choices(
    measure: Measure, compared: Compared, within: float, top: int
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
            id="distance",
            label="How distance is measured",
            value=(
                "In a straight line, from the centre of each local authority "
                "to the nearest site"
            ),
            reason="The package has no road or public transport times.",
        ),
        Choice(
            id="within_km",
            label="Distance that counts as within reach",
            value=f"{within:g} km",
            reason=(
                f"{DEFAULT_WITHIN_KM} km is what the analysis uses when no distance "
                "is set. Set the distance people will travel for what you offer."
                if within == DEFAULT_WITHIN_KM
                else "You set the distance."
            ),
            option="within_km",
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


def _checks(measure: Measure, compared: Compared) -> tuple[Check, ...]:
    """List what a person must confirm before using the figures."""
    return (
        Check(
            id="sites_public",
            question="Is the address of every site public?",
            why=(
                "The distances from several local authorities can show "
                "roughly where a site is. Do not share the result if a "
                "site's address is confidential, such as a refuge."
            ),
        ),
        Check(
            id="everything_listed",
            question="Does the data list every site people can use today?",
            why=(
                "A site left out makes the places near it look far from "
                "help. A site that has closed does the opposite."
            ),
        ),
        Check(
            id="straight_line",
            question="Is straight-line distance a fair guide where you work?",
            why=(
                "A river, a hill or a poor bus service can make a near site "
                "hard to reach. The analysis cannot see them."
            ),
        ),
        Check(
            id="need_fits",
            question=f"Are these the people your sites are for: {measure.label}?",
            why=(
                "Distance matters for the people who would use a site. "
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
