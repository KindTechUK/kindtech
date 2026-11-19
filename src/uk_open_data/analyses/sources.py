"""Published sources that analyses rest on, described once so they can be reused."""

from __future__ import annotations

from uk_open_data.analyses._model import Source
from uk_open_data.imd.api import ENGLAND_IMD_2025_URL
from uk_open_data.ons._catalog import find_tables
from uk_open_data.ons.api import NOMIS_BASE_URL
from uk_open_data.postcodes.api import POSTCODES_BASE_URL
from uk_open_data.postcodes.offline import SOURCE_NAME, SOURCE_URL

IOD_2025 = Source(
    id="iod-2025",
    name="English Indices of Deprivation 2025 (File 7)",
    publisher="Ministry of Housing, Communities and Local Government",
    url=ENGLAND_IMD_2025_URL,
    licence="Open Government Licence v3.0",
    edition="2025, on 2021 neighbourhoods, with mid-2022 population",
    used_for="Deprivation decile, local authority and residents of each area.",
)

POSTCODES_IO = Source(
    id="postcodes-io",
    name="postcodes.io",
    publisher="postcodes.io, built on the ONS Postcode Directory",
    url=POSTCODES_BASE_URL.replace("api.", ""),
    licence="Open Government Licence v3.0",
    edition="Live service on the day of the run",
    used_for="Finding the neighbourhood each postcode is in.",
)


def ons_postcode_lookup(edition: str, attribution: tuple[str, ...]) -> Source:
    """Describe the ONS postcode lookup behind the table on this machine."""
    return Source(
        id="ons-postcode-lookup",
        name=SOURCE_NAME,
        publisher="Office for National Statistics",
        url=SOURCE_URL,
        licence="Open Government Licence v3.0",
        edition=edition,
        used_for="Finding the neighbourhood each postcode is in.",
        attribution=attribution,
    )


def nomis_table(dataset_id: str, used_for: str) -> Source:
    """Describe a table read from Nomis, named as Nomis lists it."""
    listed = [table for table in find_tables() if table["id"] == dataset_id]
    name = listed[0]["name"] if listed else dataset_id
    collection = (listed[0].get("sourceName") or "") if listed else ""
    return Source(
        id=f"nomis-{dataset_id.lower()}",
        name=f"{name} ({dataset_id})",
        publisher="Office for National Statistics, through Nomis",
        url=f"{NOMIS_BASE_URL}/dataset/{dataset_id}.def.sdmx.json",
        licence="Open Government Licence v3.0",
        edition=(
            "Census 2021, taken on 21 March 2021"
            if collection.startswith("census_2021")
            else "The latest period Nomis held on the day of the run"
        ),
        used_for=used_for,
    )
