# uk-open-data

UK open data for charities, in Python: geographic boundaries, official
statistics, postcodes and deprivation indices, with analyses that join them to
your own data and return figures you can check.

Made by [KindTech UK](https://github.com/KindTechUK). Up to version 0.1 the
package was called `kindtech`.

## What is in it

- **Data modules.** `uk_open_data.geo` loads boundaries from the ONS
  Geoportal, `uk_open_data.ons` loads statistics from the Nomis API,
  `uk_open_data.postcodes` turns postcodes into geography codes, and
  `uk_open_data.imd` loads the deprivation indices. Bring your own DataFrame
  backend, pandas or polars.
- **[Analyses](https://kindtechuk.github.io/uk-open-data/api/analyses/).** Each
  analysis answers one question a charity asks of its own data, such as "Are we
  reaching people in the most deprived neighbourhoods?". It returns totals,
  the working, the sources and what a person must check. Nothing in a result
  describes one person.
- **[A command line](https://kindtechuk.github.io/uk-open-data/api/cli/).**
  `uk-open-data analysis run` runs an analysis on a file without writing any
  Python.
- **[A connector for chat assistants](https://kindtechuk.github.io/uk-open-data/api/connector/).**
  The same analyses and data as tools for an assistant such as Claude or
  ChatGPT. The assistant sees totals, never rows.

These analyses follow work first done by
[DataKind UK](https://www.datakind.org.uk/) volunteers with charities.

## Installation

Install [uk-open-data from PyPI](https://pypi.org/project/uk-open-data/):

```bash
uv add uk-open-data
```

The `uk-open-data` package includes `uk_open_data.geo`, `uk_open_data.ons`,
`uk_open_data.postcodes`, and `uk_open_data.imd`. See the
[package FAQ](https://kindtechuk.github.io/uk-open-data/faq/) for how these
subpackages are installed and released together.

## Examples

Interactive notebooks you can run in the browser:

| Notebook | Description |
|----------|-------------|
| [![Open in molab](https://marimo.io/molab-shield.svg)](https://molab.marimo.io/github/KindTechUK/uk-open-data/blob/main/examples/ons_statistics.py) | Browse and load ONS datasets from the NOMIS API |
| [![Open in molab](https://marimo.io/molab-shield.svg)](https://molab.marimo.io/github/KindTechUK/uk-open-data/blob/main/examples/geo_boundaries.py) | Explore UK geographic boundaries |
| [![Open in molab](https://marimo.io/molab-shield.svg)](https://molab.marimo.io/github/KindTechUK/uk-open-data/blob/main/examples/geo_plus_ons.py) | Join boundaries with statistics |

### Case studies

End-to-end reproductions of [DataKind UK](https://www.datakind.org.uk/) charity
projects, each chaining several connectors on `geography_code`:

| Notebook | Case study |
|----------|------------|
| [![Open in molab](https://marimo.io/molab-shield.svg)](https://molab.marimo.io/github/KindTechUK/uk-open-data/blob/main/examples/smart_works_unemployment.py) | **Smart Works** — women's unemployment vs service reach (Census 2021 + LAD boundaries) |
| [![Open in molab](https://marimo.io/molab-shield.svg)](https://molab.marimo.io/github/KindTechUK/uk-open-data/blob/main/examples/cal_vulnerable_client.py) | **Citizens Advice Lewisham** — deprivation vs service usage (postcodes + IMD + LSOA boundaries) |
| [![Open in molab](https://marimo.io/molab-shield.svg)](https://molab.marimo.io/github/KindTechUK/uk-open-data/blob/main/examples/sobus_bame_referrals.py) | **Sobus** — BAME mental-health referrals in Hammersmith & Fulham (outcodes + Census ethnicity) |
| [![Open in molab](https://marimo.io/molab-shield.svg)](https://molab.marimo.io/github/KindTechUK/uk-open-data/blob/main/examples/starlight_play_provision.py) | **Starlight** — hospital play provision vs need across ICBs |
| [![Open in molab](https://marimo.io/molab-shield.svg)](https://molab.marimo.io/github/KindTechUK/uk-open-data/blob/main/examples/material_focus_recycling.py) | **Material Focus** — travel time to the nearest recycling point (LAD boundaries + population) |

See the [case studies](https://kindtechuk.github.io/uk-open-data/case-studies/) in
the docs for the full write-ups and figures.

## Development

See [DEVELOPERS.md](DEVELOPERS.md) for development setup and workflow instructions.

## Licence

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE). Version 0.1.0 was
published under the MIT License; its notice is kept in NOTICE.
