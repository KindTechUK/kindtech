"""Access and distance: how far are people from our nearest site?

Takes where a charity's sites or service points are, measures the straight-line
distance from the centre of each local authority of England and Wales to the
nearest one, and lists the places where the most people are far from a site.
It follows the method of the Material Focus case study.

The lens is about sites, not about people, so it hides no count. Distance is
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
from uk_open_data.lenses._centres import centres_path as centres_path
from uk_open_data.lenses._centres import clear_centres_cache as clear_centres_cache
from uk_open_data.lenses._centres import (
    distance_km,
    load_centres,
    locate_in_neighbourhoods,
)
from uk_open_data.lenses._centres import download_centres as download_centres
from uk_open_data.lenses._centres import keep_centres as keep_centres
from uk_open_data.lenses._inputs import is_blank
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
    MAX_TOP,
    MEASURES,
    NEED_BANDS,
    RESIDENTS,
    Authority,
    Compared,
    Measure,
    band_by_need,
    choose_compared,
    load_need,
    read_measure,
    read_top,
)
from uk_open_data.lenses._steps import (
    EVERYWHERE,
    POSTCODE_LOOKUP,
    Position,
    Trail,
    locate_postcodes,
    percent,
    use_postcode_table,
)

LENS_ID = "access-distance"
LENS_VERSION = "0.1"
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

INFO = LensInfo(
    id=LENS_ID,
    title="Access and distance",
    question="How far are people from our nearest site, and where would a new "
    "site help most?",
    summary=(
        "Measures the straight-line distance from the centre of each local "
        "authority to your nearest site, and says what share of people are "
        "within reach. It lists the local authorities where the most people "
        "are far from a site."
    ),
    version=LENS_VERSION,
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
            description=(
                "The people to measure distance for. One of: "
                f"{', '.join(MEASURES)}. Or a table Nomis publishes by local "
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
            description=(
                "The area you could serve: a list of local authority names or "
                "codes, or 'England', 'Wales' or 'England and Wales'. Left "
                "empty, every local authority in England and Wales is compared."
            ),
            default=None,
        ),
        Option(
            name="within_km",
            description=(
                "How many kilometres from a site counts as within reach, "
                f"above 0 and up to {MAX_WITHIN_KM}."
            ),
            default=DEFAULT_WITHIN_KM,
        ),
        Option(
            name="top",
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
    "nearer or much farther than the figure says.",
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
        title="Distance to your nearest site from the places listed",
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


def run(lens_input: LensInput) -> LensResult:
    """Run the lens. Use :func:`uk_open_data.lenses.run_lens` to call it."""
    options = lens_input.options
    top = read_top(options)
    within = _within_km(options)
    measure = read_measure(options.get("need"))
    use_table = use_postcode_table(options)
    mode = lens_input.mode.name
    trail = Trail()
    authorities = load_need(measure, trail)
    centres = load_centres(trail)
    if mode == "site_coordinates":
        sites, supplied = _read_positions(
            lens_input.values["latitude"], lens_input.values["longitude"], trail
        )
    else:
        postcodes = lens_input.values["postcode"]
        locate = locate_in_neighbourhoods if use_table else locate_postcodes
        placed = locate(postcodes, trail)
        sites = _in_the_uk([p for p in placed if p is not None], trail)
        supplied = len(postcodes)
    compared = choose_compared(options.get("catchment"), authorities)
    rows = _rows(sites, authorities, centres, compared, within, trail)
    return LensResult(
        lens_id=LENS_ID,
        lens_version=LENS_VERSION,
        package_version=uk_open_data.__version__,
        run_on=date.today().isoformat(),
        input_mode=mode,
        figures=tuple(_figures(supplied, len(sites), rows, measure, within)),
        tables=(_priority_table(rows, top, within, trail), _authority_table(rows)),
        map=_map_spec(),
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
                "This lens is about sites, not about people, so it hides no count.",
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
    )


# --- options ---------------------------------------------------------------


def _within_km(options: dict[str, Any]) -> float:
    """Read and check the distance that counts as within reach."""
    value = options.get("within_km")
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise LensInputError("The option 'within_km' must be a number.")
    if not 0 < value <= MAX_WITHIN_KM:
        msg = f"The option 'within_km' must be above 0 and up to {MAX_WITHIN_KM}."
        raise LensInputError(msg)
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
        raise LensInputError(msg)
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
            f"{missing} local authorities in the area compared have no centre "
            "in the boundary figures and are left out."
        )
    if not codes:
        msg = (
            f"No local authority in {compared.label} has both need figures "
            "and a centre. Check the 'catchment' option."
        )
        raise LensInputError(msg)
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


def _priority_table(rows: list[_Row], top: int, within: float, trail: Trail) -> Table:
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
                f"The {len(beyond)} local authorities more than {within:g} km "
                "from a site were put in order of people, most first. The "
                f"first {len(ranked)} are listed."
            ),
        )
    )
    if not beyond:
        trail.warnings.append(
            f"Every local authority compared is within {within:g} km of a "
            "site, so no place is listed. Lower the 'within_km' option to "
            "list the farthest."
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
    )


def _authority_table(rows: list[_Row]) -> Table:
    """Every local authority compared, for the map and for a closer look."""
    return Table(
        id="by_local_authority",
        title="People and distance to a site in every local authority compared",
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
    )


def _map_spec() -> MapSpec:
    """Describe the map of distance and people."""
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
                note="Local authorities in five equal groups by people.",
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
        Figure("areas_compared", "Local authorities compared", len(rows), "areas"),
        Figure(
            "people_in_need",
            f"People in the area compared: {measure.label}",
            round(people),
            "people",
        ),
        Figure(
            "average_distance_km",
            "Average distance to your nearest site, counting every person",
            round(travelled / people, 1) if people else None,
            "km",
            note=(
                "Each person is counted at the centre of their local "
                "authority, so a place with many people counts for more."
            ),
        ),
        Figure(
            "share_of_people_within_reach",
            f"Share of people in a local authority within {within:g} km of a site",
            percent(people - sum(row.authority.need for row in beyond), people),
            "percent",
        ),
        Figure(
            "people_beyond_reach",
            f"People in a local authority more than {within:g} km from a site",
            round(sum(row.authority.need for row in beyond)),
            "people",
        ),
        Figure(
            "areas_beyond_reach",
            f"Local authorities more than {within:g} km from a site",
            len(beyond),
            "areas",
        ),
        Figure(
            "farthest_distance_km",
            "Distance from the farthest local authority to a site",
            max(row.distance for row in rows),
            "km",
        ),
    ]


# --- what the person needs to know -----------------------------------------


def _choices(
    measure: Measure, compared: Compared, within: float, top: int
) -> tuple[Choice, ...]:
    """List the choices the lens made."""
    return (
        Choice(
            id="need",
            label="People distance is measured for",
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
                f"{DEFAULT_WITHIN_KM} km is what the lens uses when no distance "
                "is set. Set the distance people will travel for what you offer."
                if within == DEFAULT_WITHIN_KM
                else "You set the distance."
            ),
            option="within_km",
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
                "hard to reach. The lens cannot see them."
            ),
        ),
        Check(
            id="need_fits",
            question=f"Are these the people your sites are for: {measure.label}?",
            why=(
                "Distance matters for the people who would use a site. "
                "Change the 'need' option if another measure fits better."
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


LENS = Lens(info=INFO, run=run)
