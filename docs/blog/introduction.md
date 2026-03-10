# Introduction to KindTech

## Posted June 2025

Welcome to KindTech, a Python package designed to simplify working with UK geographic boundaries and Office for National Statistics data.

## What is KindTech?

KindTech is a lightweight Python library for accessing UK public data. It wraps the ONS ArcGIS Geoportal (geographic boundaries) and the NOMIS API (statistics) with a clean, functional API.

## Key Features

- **Simple API** — flat functions, no classes to instantiate
- **Bring your own DataFrame** — works with pandas or polars via narwhals, no backend lock-in
- **Lightweight** — core package is ~500KB (requests + narwhals), no pandas/numpy required
- **Bundled catalogs** — browse available datasets offline, data is fetched live from source

## Getting Started

```bash
uv add kindtech[pandas]   # or kindtech[polars]
```

```python
from kindtech.geo import load_geodata
from kindtech.ons import load_ons, list_tables

# Load Local Authority District boundaries (GeoJSON)
boundaries = load_geodata(geography_type="LAD", coverage="UK")

# Load ONS statistics
df = load_ons("NM_1_1", geography="TYPE480", time="latest")

# Browse available datasets
tables = list_tables(name="population")
```

## Next Steps

Check out the [API documentation](../api/index.md) to learn more about the available functions.
