# kindtech API

Ergonomic access to UK public data — geographic boundaries (ONS Geoportal) and statistics (NOMIS API). Bring your own DataFrame backend (pandas or polars).

## Installation

```bash
uv add kindtech
```

## Examples

Interactive notebooks you can run in the browser:

| Notebook | Description |
|----------|-------------|
| [![Open in molab](https://marimo.io/molab-shield.svg)](https://molab.marimo.io/github/KindTechUK/kindtech/blob/main/examples/ons_statistics.py) | Browse and load ONS datasets from the NOMIS API |
| [![Open in molab](https://marimo.io/molab-shield.svg)](https://molab.marimo.io/github/KindTechUK/kindtech/blob/main/examples/geo_boundaries.py) | Explore UK geographic boundaries |
| [![Open in molab](https://marimo.io/molab-shield.svg)](https://molab.marimo.io/github/KindTechUK/kindtech/blob/main/examples/geo_plus_ons.py) | Join boundaries with statistics |

### Case studies

End-to-end reproductions of [DataKind UK](https://www.datakind.org.uk/) charity
projects, each chaining several connectors on `geography_code`:

| Notebook | Case study |
|----------|------------|
| [![Open in molab](https://marimo.io/molab-shield.svg)](https://molab.marimo.io/github/KindTechUK/kindtech/blob/main/examples/smart_works_unemployment.py) | **Smart Works** — women's unemployment vs service reach (Census 2021 + LAD boundaries) |
| [![Open in molab](https://marimo.io/molab-shield.svg)](https://molab.marimo.io/github/KindTechUK/kindtech/blob/main/examples/cal_vulnerable_client.py) | **Citizens Advice Lewisham** — deprivation vs service usage (postcodes + IMD + LSOA boundaries) |
| [![Open in molab](https://marimo.io/molab-shield.svg)](https://molab.marimo.io/github/KindTechUK/kindtech/blob/main/examples/sobus_bame_referrals.py) | **Sobus** — BAME mental-health referrals in Hammersmith & Fulham (outcodes + Census ethnicity) |
| [![Open in molab](https://marimo.io/molab-shield.svg)](https://molab.marimo.io/github/KindTechUK/kindtech/blob/main/examples/starlight_play_provision.py) | **Starlight** — hospital play provision vs need across ICBs |
| [![Open in molab](https://marimo.io/molab-shield.svg)](https://molab.marimo.io/github/KindTechUK/kindtech/blob/main/examples/material_focus_recycling.py) | **Material Focus** — travel time to the nearest recycling point (LAD boundaries + population) |

See the [case studies](https://kindtechuk.github.io/kindtech/case-studies/) in
the docs for the full write-ups and figures.

## Development

See [DEVELOPERS.md](DEVELOPERS.md) for development setup and workflow instructions.
