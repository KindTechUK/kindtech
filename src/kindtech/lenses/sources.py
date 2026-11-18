"""Published sources that lenses rest on, described once so they can be reused."""

from __future__ import annotations

from kindtech.imd.api import ENGLAND_IMD_2025_URL
from kindtech.lenses._model import Source
from kindtech.postcodes.api import POSTCODES_BASE_URL

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
