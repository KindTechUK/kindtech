"""The centre of each local authority, for lenses that measure distance.

The centres are the latitude and longitude that the ONS publishes with each
boundary. They are fetched once, held in memory, and can be kept as a file on
this machine.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import replace
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

from kindtech._kept import kept_file, read_kept, write_kept
from kindtech._mapping import geo_code_field
from kindtech.geo import load_geodata
from kindtech.lenses._model import LensInputError, Source, Step
from kindtech.lenses._steps import COUNTRIES, Position, Trail

CENTRES_FOLDER = "centres"
CENTRES_NAME = "local-authorities-2023"
CENTRES_FILE_FORMAT = "kindtech-centres-1"
# The 2021 Census is published for the local authorities of 2023.
CENTRES_YEAR = 2023
EARTH_RADIUS_KM = 6371.0

LOCAL_AUTHORITY_CENTRES = Source(
    id="ons-local-authority-centres-2023",
    name="Local Authority Districts (December 2023) Boundaries UK",
    publisher="Office for National Statistics, Open Geography Portal",
    url="https://geoportal.statistics.gov.uk/",
    licence="Open Government Licence v3.0",
    edition="December 2023",
    used_for="The centre of each local authority, to measure distance from.",
    attribution=(
        "Source: Office for National Statistics licensed under the Open "
        "Government Licence v.3.0",
        "Contains OS data © Crown copyright and database right 2023",
    ),
)


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
    source = LOCAL_AUTHORITY_CENTRES
    kept = _read_kept()
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
                "kindtech.lenses.access_distance.download_centres()."
            )
            raise LensInputError(msg) from error
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


def _read_kept() -> tuple[tuple[tuple[str, float, float], ...], str] | None:
    """Read the centres kept on this machine, with the note that goes with them."""
    try:
        kept = read_kept(CENTRES_FOLDER, CENTRES_NAME, CENTRES_FILE_FORMAT)
        if kept is None:
            return None
        rows = tuple(
            (str(code), float(latitude), float(longitude))
            for code, latitude, longitude in kept["centres"]
        )
        return rows, kept["note"]
    except (KeyError, TypeError, ValueError) as error:
        msg = (
            "The centres kept on this machine could not be read. Fetch them "
            "again with kindtech.lenses.access_distance.download_centres()."
        )
        raise LensInputError(msg) from error


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


def _centre_of(
    properties: dict[str, Any], field: str
) -> tuple[str, float, float] | None:
    """Read one local authority's code and centre, or None when it has none."""
    code = str(properties.get(field) or "")
    if code[:1] not in COUNTRIES.values():
        return None
    try:
        latitude = float(properties["LAT"])
        longitude = float(properties["LONG"])
    except (KeyError, TypeError, ValueError):
        return None
    return code, latitude, longitude


def centres_path() -> Path | None:
    """Return where the centres are kept on this machine, or None."""
    path = kept_file(CENTRES_FOLDER, CENTRES_NAME)
    return path if path.is_file() else None


def keep_centres(centres: Iterable[tuple[str, float, float]], note: str) -> Path:
    """Keep the centres of local authorities on this machine.

    A lens that measures distance reads the copy instead of asking the ONS
    Open Geography Portal, so a server or a demonstration works without the
    network. The copy lives in the data folder (see
    :func:`kindtech.postcodes.offline.data_dir`).

    Args:
        centres: Local authority code, latitude and longitude, one per local
            authority.
        note: Where the centres came from, in a few words. It is shown with
            the source in every result that uses the copy.

    Returns:
        The path of the file written.
    """
    content = {
        "year": CENTRES_YEAR,
        "centres": [
            [str(code), float(latitude), float(longitude)]
            for code, latitude, longitude in centres
        ],
    }
    return write_kept(CENTRES_FOLDER, CENTRES_NAME, CENTRES_FILE_FORMAT, note, content)


def download_centres() -> Path:
    """Fetch the centres of local authorities and keep them on this machine.

    Run this once when a server is built. Only public figures are fetched.

    Returns:
        The path of the file written.

    Raises:
        ValueError: If the boundaries could not be fetched, or hold no centre.
    """
    clear_centres_cache()
    note = f"fetched from the ONS Open Geography Portal on {date.today().isoformat()}."
    return keep_centres(_fetch_centres(), note)


def clear_centres_cache() -> None:
    """Forget the centres fetched earlier in this process."""
    _fetch_centres.cache_clear()
