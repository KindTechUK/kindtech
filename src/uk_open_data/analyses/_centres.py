"""The centres of local authorities and neighbourhoods, to measure distance.

The centres are the latitude and longitude that the ONS publishes with each
boundary. Those of local authorities are fetched once, held in memory, and can
be kept as a file on this machine. Those of neighbourhoods are a larger table,
so they are only ever read from a file kept on this machine.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

import requests

from uk_open_data._kept import kept_file, read_kept, write_kept
from uk_open_data._mapping import geo_code_field
from uk_open_data.analyses._model import AnalysisInputError, Choice, Source, Step
from uk_open_data.analyses._steps import (
    COUNTRIES,
    Position,
    Trail,
    read_postcode_column,
    warn_left_out,
)
from uk_open_data.analyses.sources import ons_postcode_lookup
from uk_open_data.geo import load_geodata
from uk_open_data.geo._catalog import find_services, get_service_url
from uk_open_data.postcodes import (
    PostcodeTableError,
    postcode_table_info,
    postcodes_to_lsoa,
)

CENTRES_FOLDER = "centres"
CENTRES_FILE_FORMAT = "kindtech-centres-1"
# The 2021 Census is published for the local authorities of 2023.
CENTRES_YEAR = 2023
NEIGHBOURHOOD_YEAR = 2021
EARTH_RADIUS_KM = 6371.0
# The boundary service gives this many neighbourhoods at a time.
PAGE_SIZE = 2000
# England and Wales have about 35,700. More than this means the service is
# not paging, and the fetch stops.
MAX_NEIGHBOURHOODS = 100_000
_ATTRIBUTION = (
    "Source: Office for National Statistics licensed under the Open Government "
    "Licence v.3.0",
    "Contains OS data © Crown copyright and database right {year}",
)


@dataclass(frozen=True)
class _Level:
    """A size of area whose centres can be kept on this machine."""

    name: str
    plural: str
    file_name: str
    source: Source


LOCAL_AUTHORITY_CENTRES = Source(
    id="ons-local-authority-centres-2023",
    name="Local Authority Districts (December 2023) Boundaries UK",
    publisher="Office for National Statistics, Open Geography Portal",
    url="https://geoportal.statistics.gov.uk/",
    licence="Open Government Licence v3.0",
    edition="December 2023",
    used_for="The centre of each local authority, to measure distance from.",
    attribution=tuple(line.format(year=CENTRES_YEAR) for line in _ATTRIBUTION),
)
NEIGHBOURHOOD_CENTRES = Source(
    id="ons-neighbourhood-centres-2021",
    name="Lower layer Super Output Areas (December 2021) Boundaries EW",
    publisher="Office for National Statistics, Open Geography Portal",
    url="https://geoportal.statistics.gov.uk/",
    licence="Open Government Licence v3.0",
    edition="December 2021",
    used_for="The centre of the neighbourhood each site is in.",
    attribution=tuple(line.format(year=NEIGHBOURHOOD_YEAR) for line in _ATTRIBUTION),
)
_LEVELS = {
    level.name: level
    for level in (
        _Level(
            name="local_authority",
            plural="local authorities",
            file_name="local-authorities-2023",
            source=LOCAL_AUTHORITY_CENTRES,
        ),
        _Level(
            name="neighbourhood",
            plural="neighbourhoods",
            file_name="neighbourhoods-2021",
            source=NEIGHBOURHOOD_CENTRES,
        ),
    )
}
LOCAL_AUTHORITY = "local_authority"
NEIGHBOURHOOD = "neighbourhood"


def distance_km(first: Position, second: Position) -> float:
    """Return the straight-line distance between two points, in kilometres.

    Args:
        first: Latitude and longitude, in degrees.
        second: Latitude and longitude, in degrees.
    """
    lat1, lon1, lat2, lon2 = map(math.radians, (*first, *second))
    half = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(half))


def load_centres(trail: Trail) -> dict[str, Position]:
    """Load the centre of each local authority in England and Wales.

    A copy kept on this machine is used when there is one. Otherwise the
    centres are fetched from the ONS Open Geography Portal.

    Returns:
        Local authority code to latitude and longitude.
    """
    level = _LEVELS[LOCAL_AUTHORITY]
    source = level.source
    kept = _read_kept(level)
    if kept is not None:
        rows, note = kept
        source = replace(
            source, edition=f"{source.edition}. A copy kept on this machine, {note}"
        )
        where = "A copy kept on this machine was used, so nothing was fetched."
    else:
        try:
            rows = _fetch_centres()
        except ValueError as error:
            msg = (
                f"The centres of local authorities could not be loaded. {error} "
                "Keep a copy on this machine with "
                "uk_open_data.analyses.access_distance.download_centres()."
            )
            raise AnalysisInputError(msg) from error
        where = "Fetched from the ONS Open Geography Portal."
    trail.sources.append(source)
    trail.working.append(
        Step(
            title="Loaded the centre of each local authority",
            detail=(
                f"{len(rows)} local authorities in England and Wales, each with "
                f"the latitude and longitude the ONS publishes for it. {where}"
            ),
        )
    )
    return {code: (latitude, longitude) for code, latitude, longitude in rows}


def locate_in_neighbourhoods(values: list[Any], trail: Trail) -> list[Position | None]:
    """Find where each row's postcode is, without sending it anywhere.

    Each postcode is placed at the centre of its neighbourhood. The postcode
    table on this machine gives the neighbourhood, and the neighbourhood
    centres kept on this machine give the position. Nothing is fetched and
    nothing is sent: when either file is missing, the analysis stops.

    Args:
        values: The postcode column.
        trail: Where the steps, warnings, sources and choices are recorded.

    Returns:
        Latitude and longitude per row, in row order. None where the row has
        no postcode, or one that is malformed or not found.
    """
    tidy, blank, malformed = read_postcode_column(values, trail)
    usable = [postcode for postcode in tidy if postcode is not None]
    distinct = sorted(set(usable))
    try:
        neighbourhoods = postcodes_to_lsoa(distinct)
        info = postcode_table_info()
    except PostcodeTableError as error:
        raise AnalysisInputError(str(error)) from error
    centres, note = _kept_neighbourhood_centres()
    found_for = {
        postcode: centres.get(code) if code else None
        for postcode, code in zip(distinct, neighbourhoods, strict=True)
    }
    edition = str(info["edition"])
    table = ons_postcode_lookup(edition, tuple(info["attribution"]))
    trail.sources.append(
        replace(table, used_for="Finding the neighbourhood each site is in.")
    )
    trail.sources.append(
        replace(
            NEIGHBOURHOOD_CENTRES,
            edition=(
                f"{NEIGHBOURHOOD_CENTRES.edition}. A copy kept on this machine, {note}"
            ),
        )
    )
    trail.choices.append(
        Choice(
            id="postcode_lookup",
            label="How postcodes were placed",
            value=(
                "On this machine, at the centre of each postcode's "
                f"neighbourhood (ONS postcode lookup, {edition})"
            ),
            reason="A postcode table is installed, so no postcode was sent out.",
            option="postcode_lookup",
        )
    )
    placed = [None if postcode is None else found_for[postcode] for postcode in tidy]
    found = sum(1 for position in placed if position is not None)
    not_found = len(usable) - found
    trail.working.append(
        Step(
            title="Found where each postcode is",
            detail=(
                f"{len(distinct)} distinct postcodes were looked up on this "
                f"machine, in the ONS postcode lookup ({edition}), and each "
                "was placed at the centre of its neighbourhood. "
                f"{not_found} rows had a postcode that was not found."
            ),
            rows_in=len(usable),
            rows_out=found,
        )
    )
    warn_left_out(blank, malformed, not_found, True, trail)
    return placed


def _kept_neighbourhood_centres() -> tuple[dict[str, Position], str]:
    """Read the neighbourhood centres kept on this machine, and their note.

    Raises:
        AnalysisInputError: If no copy is kept. They are never fetched while an
            analysis runs.
    """
    kept = _read_kept(_LEVELS[NEIGHBOURHOOD])
    if kept is None:
        msg = (
            "The centres of neighbourhoods are not kept on this machine, so "
            "postcodes cannot be placed here. Keep them with "
            "uk_open_data.analyses.access_distance.download_centres('neighbourhood'), "
            "or give a latitude and longitude for each row. No postcode was "
            "sent anywhere."
        )
        raise AnalysisInputError(msg)
    rows, note = kept
    return _as_mapping(rows), note


@lru_cache(maxsize=2)
def _as_mapping(rows: tuple[tuple[str, float, float], ...]) -> dict[str, Position]:
    """Turn rows of centres into a lookup by area code."""
    return {code: (latitude, longitude) for code, latitude, longitude in rows}


def _read_kept(
    level: _Level,
) -> tuple[tuple[tuple[str, float, float], ...], str] | None:
    """Read the centres kept on this machine, with the note that goes with them."""
    path = kept_file(CENTRES_FOLDER, level.file_name)
    if not path.is_file():
        return None
    try:
        return _read_kept_file(str(path), path.stat().st_mtime_ns)
    except (KeyError, TypeError, ValueError) as error:
        msg = (
            f"The centres of {level.plural} kept on this machine could not be "
            "read. Fetch them again with "
            f"uk_open_data.analyses.access_distance.download_centres('{level.name}')."
        )
        raise AnalysisInputError(msg) from error


@lru_cache(maxsize=4)
def _read_kept_file(
    path: str, modified: int
) -> tuple[tuple[tuple[str, float, float], ...], str]:
    """Read one kept file, once for each time it is written."""
    del modified  # Part of the cache key: a file written again is read again.
    folder, name = Path(path).parent.name, Path(path).stem
    kept = read_kept(folder, name, CENTRES_FILE_FORMAT)
    if kept is None:
        raise ValueError(path)
    rows = tuple(
        (str(code), float(latitude), float(longitude))
        for code, latitude, longitude in kept["centres"]
    )
    return rows, kept["note"]


@lru_cache(maxsize=1)
def _fetch_centres() -> tuple[tuple[str, float, float], ...]:
    """Fetch the centres from the ONS Open Geography Portal, once per process.

    Raises:
        ValueError: If the boundaries could not be fetched, or hold no centre.
    """
    geojson = load_geodata(
        "LAD",
        year=str(CENTRES_YEAR),
        month="DEC",
        coverage="UK",
        boundary_type="BUC",
    )
    field = geo_code_field("LAD", CENTRES_YEAR)
    rows = []
    for feature in geojson.get("features", []):
        centre = _centre_of(feature.get("properties") or {}, field)
        if centre is not None:
            rows.append(centre)
    if not rows:
        msg = "The boundary service returned no local authority with a centre."
        raise ValueError(msg)
    return tuple(sorted(rows))


def _fetch_neighbourhood_centres() -> tuple[tuple[str, float, float], ...]:
    """Fetch the centre of every neighbourhood from the ONS Open Geography Portal.

    The service gives a few thousand areas at a time, so it is asked page by
    page, for the attributes alone and no shapes.

    Raises:
        ValueError: If the service could not be reached, or holds no centre.
    """
    services = find_services(
        geography_type="LSOA",
        year=str(NEIGHBOURHOOD_YEAR),
        coverage="EW",
        boundary_type="BSC",
    )
    if not services:
        msg = "The package lists no boundary service for neighbourhoods."
        raise ValueError(msg)
    url = f"{get_service_url(services[0]['arcgis_id'])}/0/query"
    field = geo_code_field("LSOA", NEIGHBOURHOOD_YEAR)
    rows: list[tuple[str, float, float]] = []
    offset = 0
    while True:
        page = _attributes_page(url, field, offset)
        if not page:
            break
        offset += len(page)
        if offset > MAX_NEIGHBOURHOODS:
            msg = "The boundary service kept returning neighbourhoods."
            raise ValueError(msg)
        for attributes in page:
            centre = _centre_of(attributes, field)
            if centre is not None:
                rows.append(centre)
    if not rows:
        msg = "The boundary service returned no neighbourhood with a centre."
        raise ValueError(msg)
    return tuple(sorted(set(rows)))


def _attributes_page(url: str, field: str, offset: int) -> list[dict[str, Any]]:
    """Ask the boundary service for one page of attributes, in code order."""
    params: dict[str, Any] = {
        "f": "json",
        "where": "1=1",
        "outFields": "*",
        "returnGeometry": "false",
        "orderByFields": field,
        "resultOffset": offset,
        "resultRecordCount": PAGE_SIZE,
    }
    try:
        response = requests.get(url, params=params, timeout=60)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as error:
        msg = "The boundary service could not be reached."
        raise ValueError(msg) from error
    if not isinstance(payload, dict) or "error" in payload:
        msg = "The boundary service refused the request."
        raise ValueError(msg)
    features = payload.get("features") or []
    return [feature.get("attributes") or {} for feature in features]


def _centre_of(
    properties: dict[str, Any], field: str
) -> tuple[str, float, float] | None:
    """Read one area's code and centre, or None when it has none."""
    code = str(properties.get(field) or "")
    if code[:1] not in COUNTRIES.values():
        return None
    try:
        latitude = float(properties["LAT"])
        longitude = float(properties["LONG"])
    except (KeyError, TypeError, ValueError):
        return None
    return code, latitude, longitude


def _level(name: str) -> _Level:
    """Find a size of area by its name."""
    if name not in _LEVELS:
        msg = f"No centres for '{name}'. Known: {', '.join(_LEVELS)}."
        raise ValueError(msg)
    return _LEVELS[name]


def centres_path(level: str = LOCAL_AUTHORITY) -> Path | None:
    """Return where centres are kept on this machine, or None.

    Args:
        level: ``"local_authority"`` or ``"neighbourhood"``.
    """
    path = kept_file(CENTRES_FOLDER, _level(level).file_name)
    return path if path.is_file() else None


def keep_centres(
    centres: Iterable[tuple[str, float, float]],
    note: str,
    level: str = LOCAL_AUTHORITY,
) -> Path:
    """Keep the centres of local authorities or neighbourhoods on this machine.

    An analysis that measures distance reads the copy instead of asking the ONS
    Open Geography Portal, so a server or a demonstration works without the
    network. The centres of neighbourhoods are what lets the postcode of a
    site be placed without sending it anywhere. The copy lives in the data
    folder (see :func:`uk_open_data.postcodes.offline.data_dir`).

    Args:
        centres: Area code, latitude and longitude, one per area.
        note: Where the centres came from, in a few words. It is shown with
            the source in every result that uses the copy.
        level: ``"local_authority"`` or ``"neighbourhood"``.

    Returns:
        The path of the file written.

    Raises:
        ValueError: If the level is not one of the two.
    """
    chosen = _level(level)
    content = {
        "level": chosen.name,
        "centres": [
            [str(code), float(latitude), float(longitude)]
            for code, latitude, longitude in centres
        ],
    }
    return write_kept(
        CENTRES_FOLDER,
        chosen.file_name,
        CENTRES_FILE_FORMAT,
        note,
        content,
        compact=chosen.name == NEIGHBOURHOOD,
    )


def download_centres(level: str = LOCAL_AUTHORITY) -> Path:
    """Fetch centres from the ONS and keep them on this machine.

    Run this once when a server is built, for each level it needs. Only
    public figures are fetched.

    Args:
        level: ``"local_authority"`` or ``"neighbourhood"``.

    Returns:
        The path of the file written.

    Raises:
        ValueError: If the level is not one of the two, or the boundaries
            could not be fetched or hold no centre.
    """
    chosen = _level(level)
    clear_centres_cache()
    if chosen.name == NEIGHBOURHOOD:
        rows = _fetch_neighbourhood_centres()
    else:
        rows = _fetch_centres()
    note = f"fetched from the ONS Open Geography Portal on {date.today().isoformat()}."
    return keep_centres(rows, note, chosen.name)


def clear_centres_cache() -> None:
    """Forget the centres fetched or read earlier in this process."""
    _fetch_centres.cache_clear()
    _read_kept_file.cache_clear()
    _as_mapping.cache_clear()
