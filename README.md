# kindtech API

Ergonomic access to UK public data — geographic boundaries (ONS Geoportal) and statistics (NOMIS API). Bring your own DataFrame backend (pandas or polars).

## Installation

```bash
uv add kindtech[pandas]   # or kindtech[polars]
```

## Examples

Interactive notebooks you can run in the browser:

| Notebook | Description |
|----------|-------------|
| [![Open in molab](https://marimo.io/molab-shield.svg)](https://molab.marimo.io/github/KindTechUK/kindtech/blob/main/examples/ons_statistics.py) | Browse and load ONS datasets from the NOMIS API |
| [![Open in molab](https://marimo.io/molab-shield.svg)](https://molab.marimo.io/github/KindTechUK/kindtech/blob/main/examples/geo_boundaries.py) | Explore UK geographic boundaries |
| [![Open in molab](https://marimo.io/molab-shield.svg)](https://molab.marimo.io/github/KindTechUK/kindtech/blob/main/examples/geo_plus_ons.py) | Join boundaries with statistics |

## Development

See [DEVELOPERS.md](DEVELOPERS.md) for development setup and workflow instructions.
