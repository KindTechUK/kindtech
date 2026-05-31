# Examples

Runnable [marimo](https://marimo.io/) notebooks. Open any of them in the molab
cloud runtime to run it **in your browser** — each fetches live ONS data — or
run locally with `uv run marimo edit examples/<notebook>.py`.

## Connector basics

<div class="grid cards" markdown>

-   __ONS statistics__

    ---

    Browse and load datasets straight from the NOMIS API.

    [![Open in molab](https://marimo.io/molab-shield.svg)](https://molab.marimo.io/github/KindTechUK/kindtech/blob/main/examples/ons_statistics.py)

-   __Geographic boundaries__

    ---

    Explore LAD, LSOA and other UK boundary data interactively.

    [![Open in molab](https://marimo.io/molab-shield.svg)](https://molab.marimo.io/github/KindTechUK/kindtech/blob/main/examples/geo_boundaries.py)

-   __Boundaries + statistics__

    ---

    Join geographic shapes with ONS data and map the result.

    [![Open in molab](https://marimo.io/molab-shield.svg)](https://molab.marimo.io/github/KindTechUK/kindtech/blob/main/examples/geo_plus_ons.py)

</div>

## Case studies

End-to-end reproductions of [DataKind UK](https://www.datakind.org.uk/) charity
projects, each chaining several connectors on `geography_code`. See the
[Case Studies](case-studies/index.md) section for the full write-ups and figures.

| Notebook | Case study |
|----------|------------|
| [![Open in molab](https://marimo.io/molab-shield.svg)](https://molab.marimo.io/github/KindTechUK/kindtech/blob/main/examples/smart_works_unemployment.py) | **Smart Works** — women's unemployment vs service reach (Census 2021 + LAD boundaries) |
| [![Open in molab](https://marimo.io/molab-shield.svg)](https://molab.marimo.io/github/KindTechUK/kindtech/blob/main/examples/cal_vulnerable_client.py) | **Citizens Advice Lewisham** — deprivation vs service usage (postcodes + IMD + LSOA boundaries) |
| [![Open in molab](https://marimo.io/molab-shield.svg)](https://molab.marimo.io/github/KindTechUK/kindtech/blob/main/examples/sobus_bame_referrals.py) | **Sobus** — BAME mental-health referrals in Hammersmith & Fulham (outcodes + Census ethnicity) |
| [![Open in molab](https://marimo.io/molab-shield.svg)](https://molab.marimo.io/github/KindTechUK/kindtech/blob/main/examples/starlight_play_provision.py) | **Starlight** — hospital play provision vs need across ICBs |
| [![Open in molab](https://marimo.io/molab-shield.svg)](https://molab.marimo.io/github/KindTechUK/kindtech/blob/main/examples/material_focus_recycling.py) | **Material Focus** — travel time to the nearest recycling point (LAD boundaries + population) |
