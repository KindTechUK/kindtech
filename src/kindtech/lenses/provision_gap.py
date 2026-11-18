"""Provision gap: where is provision thin against need across a region?

Takes a charity's sites or services, each with a location and how much it
provides, totals the provision in each local authority, and sets it against
the people who live there or a count of people in need. It follows the method
of the Starlight case study, by local authority.

The lens is about sites and what they provide, not about people, so it hides
no count. Counts of people belong in the need against reach lens.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date
from statistics import median
from typing import Any

import kindtech
from kindtech.lenses._inputs import is_blank
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
    OptionChoice,
    Privacy,
    Role,
    Step,
    Table,
)
from kindtech.lenses._need import (
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
    load_need,
    read_measure,
    read_top,
)
from kindtech.lenses._privacy import DEFAULT_SUPPRESS_BELOW
from kindtech.lenses._steps import (
    EVERYWHERE,
    LOCAL_AUTHORITY,
    POSTCODE_LOOKUP,
    Trail,
    percent,
    place_postcodes,
    use_postcode_table,
)

LENS_ID = "provision-gap"
LENS_VERSION = "0.1"
NO_PROVISION = "None"
PROVISION_BANDS = (
    NO_PROVISION,
    "Lower provision",
    "Middle provision",
    "Higher provision",
)

INFO = LensInfo(
    id=LENS_ID,
    title="Provision gap",
    question="Where is provision thin against need across a region?",
    summary=(
        "Totals what your sites or services provide in each local authority "
        "and sets it against the people who live there, or a count of people "
        "in need. It lists the high-need local authorities with the least "
        "provision for each 1,000 people."
    ),
    version=LENS_VERSION,
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
            description="One row per site or service, with its postcode and volume.",
            roles=("postcode", "volume"),
        ),
        InputMode(
            name="area_volumes",
            description="One row per local authority, with the volume provided there.",
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
            description=(
                "The people to set your provision against. One of: "
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
            name="top",
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
    "Need is a count of people, so a large local authority is more likely to "
    "be listed as high need than a small one with the same rate.",
)

CHARTS = (
    Chart(
        id="need_in_priority_areas",
        title="People in need in the places listed",
        table="priority_areas",
        category_column="geography_name",
        series=(ChartSeries("people_in_need", "People in need", "people"),),
    ),
    Chart(
        id="provision_in_priority_areas",
        title="Provision for each 1,000 people in need in the places listed",
        table="priority_areas",
        category_column="geography_name",
        series=(
            ChartSeries(
                "volume_per_1000_in_need", "Volume per 1,000 in need", "per_1000"
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


def run(lens_input: LensInput) -> LensResult:
    """Run the lens. Use :func:`kindtech.lenses.run_lens` to call it."""
    options = lens_input.options
    top = read_top(options)
    measure = read_measure(options.get("need"))
    mode = lens_input.mode.name
    trail = Trail()
    authorities = load_need(measure, trail)
    if mode == "area_volumes":
        volumes, supplied = _volume_by_authority(
            lens_input.values["local_authority"],
            lens_input.values["volume"],
            authorities,
            trail,
        )
    else:
        postcodes = lens_input.values["postcode"]
        amounts = (
            _amounts(lens_input.values["volume"])
            if mode == "sites"
            else [1.0] * len(postcodes)
        )
        volumes, supplied = _volume_by_postcode(
            postcodes, amounts, use_postcode_table(options), trail
        )
    located = _keep_listed(volumes, authorities, trail)
    compared = choose_compared(options.get("catchment"), authorities)
    rows = _rows(located, authorities, compared, trail)
    return LensResult(
        lens_id=LENS_ID,
        lens_version=LENS_VERSION,
        package_version=kindtech.__version__,
        run_on=date.today().isoformat(),
        input_mode=mode,
        figures=tuple(_figures(supplied, sum(located.values()), rows, measure)),
        tables=(_priority_table(rows, top, trail), _authority_table(rows)),
        map=_map_spec(),
        working=tuple(trail.working),
        choices=(*trail.choices, *_choices(measure, compared, top)),
        checks=_checks(mode, measure, compared),
        caveats=(*CAVEATS, measure.caveat),
        warnings=tuple(trail.warnings),
        sources=tuple(trail.sources),
        privacy=Privacy(
            suppress_below=DEFAULT_SUPPRESS_BELOW,
            cells_suppressed=0,
            row_level_output=False,
            sent_to_third_parties=tuple(trail.sent),
            notes=(
                "This lens is about sites and what they provide, not about "
                "people, so it hides no count.",
                "The result holds totals for local authorities. It names no "
                "site and repeats no postcode.",
                "Where a local authority holds one site, the volume shown for "
                "it is that site's volume.",
                "The need figures are public counts and are shown in full.",
            ),
        ),
        charts=CHARTS,
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
    bad = sum(1 for amount in amounts if amount is None)
    if bad:
        msg = (
            f"{bad} rows have a volume that is not a number of zero or more. "
            "Correct those rows and run the lens again."
        )
        raise LensInputError(msg)
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
            f"A volume of {_tidy(not_placed):,} is at sites that could not be "
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
    blank = unknown = 0
    for place, amount in zip(places, amounts, strict=True):
        if is_blank(place):
            blank += 1
            continue
        code = by_key.get(str(place).strip().casefold())
        unknown += code is None
        totals[code or ""] += amount
    if blank:
        trail.warnings.append(f"{blank} rows had no local authority.")
    if unknown:
        trail.warnings.append(
            f"{unknown} rows named a local authority that the need figures do "
            "not list. Use the names or codes that Nomis uses."
        )
    trail.working.append(
        Step(
            title="Read the local authority volumes",
            detail=(
                f"{len(places)} rows holding a volume of "
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
                f"A volume of {_tidy(inside):,} is in a local authority the "
                f"need figures list. {_tidy(outside):,} is outside England "
                "and Wales, or in a local authority the figures do not list."
            ),
        )
    )
    if outside:
        trail.warnings.append(
            f"A volume of {_tidy(outside):,} was placed outside England and "
            "Wales, or in a local authority the need figures do not list "
            "(for example one whose boundary has changed). It is left out."
        )
    if not located:
        msg = (
            "None of the provision could be placed in a local authority in "
            "England or Wales. Check the location column."
        )
        raise LensInputError(msg)
    return located


# --- the comparison --------------------------------------------------------


def _rows(
    located: dict[str, float],
    authorities: dict[str, Authority],
    compared: Compared,
    trail: Trail,
) -> list[_Row]:
    """Build one row per local authority compared."""
    if not compared.codes:
        msg = (
            f"The need figures list no local authority in {compared.label}. "
            "Check the 'catchment' option."
        )
        raise LensInputError(msg)
    volume = [located.get(code, 0.0) for code in compared.codes]
    need = [authorities[code].need for code in compared.codes]
    inside = sum(volume)
    with_provision = sum(1 for amount in volume if amount > 0)
    trail.working.append(
        Step(
            title="Set the area to compare",
            detail=(
                f"Area: {compared.label}. {compared.reason} A volume of "
                f"{_tidy(inside):,} of the {_tidy(sum(located.values())):,} "
                f"placed is in it, in {with_provision} of its {len(volume)} "
                "local authorities."
            ),
        )
    )
    if not inside:
        msg = (
            f"None of the provision is in the catchment ({compared.label}). "
            "Check the 'catchment' option."
        )
        raise LensInputError(msg)
    _warn_about_area(sum(located.values()) - inside, with_provision, compared, trail)
    cut = median(need)
    high = [amount >= cut and amount > 0 for amount in need]
    need_bands = band_by_need(need)
    provision_bands = _provision_bands(volume, need)
    trail.working.append(
        Step(
            title="Set provision against need",
            detail=(
                "For each local authority, the volume you provide was divided "
                "by the people in need and multiplied by 1,000. A local "
                "authority is high need when its count of people in need is "
                f"at or above the middle value of the area ({round(cut):,})."
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
    """Warn when the area compared looks too wide, too narrow or too small."""
    if outside:
        trail.warnings.append(
            f"A volume of {_tidy(outside):,} is outside the catchment and is "
            "left out. Change the 'catchment' option to include it."
        )
    if not compared.named and with_provision * FEW_AREAS < len(compared.codes):
        trail.warnings.append(
            f"You provide in {with_provision} of the {len(compared.codes)} "
            "local authorities compared. If you serve a smaller area, name it "
            "with the 'catchment' option, so that places you could not reach "
            "are not listed as gaps."
        )
    if len(compared.codes) < len(NEED_BANDS):
        trail.warnings.append(
            f"Only {len(compared.codes)} local authorities are compared, so "
            "'high need' says little. It means at or above the middle value."
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


def _priority_table(rows: list[_Row], top: int, trail: Trail) -> Table:
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
            title="Listed the places with high need and thin provision",
            detail=(
                f"The {len(high)} high-need local authorities were put in "
                "order of provision for each 1,000 people in need, lowest "
                f"first, and then by need, highest first. The first "
                f"{len(ranked)} are listed."
            ),
        )
    )
    return Table(
        id="priority_areas",
        title="High need and thin provision: the places to look at first",
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


def _authority_table(rows: list[_Row]) -> Table:
    """Every local authority compared, for the map and for a closer look."""
    return Table(
        id="by_local_authority",
        title="Need and provision in every local authority compared",
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


def _map_spec() -> MapSpec:
    """Describe the map of need and provision."""
    return MapSpec(
        title="Need and provision, by local authority",
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
                id="provision",
                label="Provision for each 1,000 people in need",
                value_column="provision_band",
                kind="ordinal",
                note=(
                    "Local authorities where you provide are in three equal "
                    "groups. The lowest band holds places where you provide "
                    "nothing."
                ),
                categories=PROVISION_BANDS,
            ),
        ),
    )


# --- figures ---------------------------------------------------------------


def _figures(
    supplied: float, located: float, rows: list[_Row], measure: Measure
) -> list[Figure]:
    """Build the headline figures."""
    volume = [row.volume for row in rows]
    need = [row.authority.need for row in rows]
    high = [i for i, row in enumerate(rows) if row.high_need]
    in_catchment = sum(volume)
    return [
        Figure(
            "volume_supplied", "Volume in the data you gave", _tidy(supplied), "count"
        ),
        Figure(
            "volume_located",
            "Volume placed in a local authority in England or Wales",
            _tidy(located),
            "count",
        ),
        Figure(
            "volume_in_catchment",
            "Volume in the area compared",
            _tidy(in_catchment),
            "count",
            note="The figures below are about this provision.",
        ),
        Figure("areas_compared", "Local authorities compared", len(rows), "areas"),
        Figure(
            "areas_without_provision",
            "Local authorities where you provide nothing",
            sum(1 for amount in volume if not amount),
            "areas",
        ),
        Figure(
            "people_in_need",
            f"People in need in the area compared: {measure.label}",
            round(sum(need)),
            "people",
        ),
        Figure(
            "volume_per_1000_in_need",
            "Volume for each 1,000 people in need, across the area",
            _per_1000(in_catchment, sum(need)),
            "per_1000",
        ),
        Figure(
            "high_need_areas", "Local authorities with high need", len(high), "areas"
        ),
        Figure(
            "high_need_areas_without_provision",
            "High-need local authorities where you provide nothing",
            sum(1 for i in high if not volume[i]),
            "areas",
        ),
        Figure(
            "share_of_provision_in_high_need_areas",
            "Share of your provision that is in high-need local authorities",
            percent(sum(volume[i] for i in high), in_catchment),
            "percent",
        ),
        Figure(
            "share_of_need_in_high_need_areas",
            "Share of people in need who live in those local authorities",
            percent(sum(need[i] for i in high), sum(need)),
            "percent",
            note="Compare this with the share of your provision.",
        ),
    ]


# --- what the person needs to know -----------------------------------------


def _choices(measure: Measure, compared: Compared, top: int) -> tuple[Choice, ...]:
    """List the choices the lens made."""
    return (
        Choice(
            id="need",
            label="People your provision is set against",
            value=measure.label,
            reason=measure.reason,
            option="need",
        ),
        Choice(
            id="high_need",
            label="What counts as high need",
            value="At or above the middle value of the area compared",
            reason="Half of the local authorities compared are high need.",
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


def _checks(mode: str, measure: Measure, compared: Compared) -> tuple[Check, ...]:
    """List what a person must confirm before using the figures."""
    if mode == "site_list":
        first = Check(
            id="sites_alike",
            question="Do your sites each provide about the same amount?",
            why=(
                "With no volume column every site counts as one. Add a "
                "volume column if some sites provide much more than others."
            ),
        )
    else:
        first = Check(
            id="volume_is_provision",
            question="Is the volume a count of what you provide, and not of people?",
            why=(
                "This lens shows every volume as it is. Counts of people "
                "belong in the need against reach lens, which hides small "
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
            why="The lens cannot tell which dates the rows are from.",
        ),
        Check(
            id="need_fits",
            question=f"Are these the people you provide for: {measure.label}?",
            why=(
                "Provision is only meaningful against the people it is for. "
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
