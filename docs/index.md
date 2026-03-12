# KindTech

Ergonomic Python access to UK public data. Geographic boundaries from the ONS ArcGIS Geoportal, statistics from the NOMIS API — with universal DataFrame support.

## Install

```bash
uv add kindtech
```

KindTech is lightweight (~500KB) — just requests + narwhals. You bring your own DataFrame library (pandas or polars).

## Quick start

```python
from kindtech import load_geodata, load_ons, geodata_to_properties
import pandas as pd  # or polars

# Load LAD boundaries (GeoJSON) and extract properties
geojson = load_geodata(geography_type="LAD")
geo_df = pd.DataFrame(geodata_to_properties(geojson, "LAD", 2024))

# Load ONS statistics — columns are normalised automatically
ons_df = load_ons("population", geography_type="LAD", time="latest")

# Join on the shared geography_code column
merged = geo_df.merge(ons_df, on="geography_code")
```

## Bring Your Own DataFrame

KindTech uses [narwhals](https://narwhals-dev.github.io/narwhals/) for universal DataFrame support. The library itself has **no pandas or polars dependency** — it returns whatever backend you have installed.

```python
# With pandas installed → returns pd.DataFrame
from kindtech.ons import load_ons
df = load_ons("NM_1_1")
type(df)  # <class 'pandas.core.frame.DataFrame'>
```

```python
# With polars installed → returns pl.DataFrame
from kindtech.ons import load_ons
df = load_ons("NM_1_1")
type(df)  # <class 'polars.dataframe.frame.DataFrame'>
```

If both are installed, polars is preferred (it's faster and more memory-efficient). The geo module returns plain GeoJSON dicts — no DataFrame backend needed.

### Why narwhals?

| | kindtech | typical data library |
|---|---|---|
| Install size | ~500KB (requests + narwhals) | ~30MB+ (pandas) |
| Backend lock-in | None — use what you prefer | Forced into pandas |
| Extra deps | 0 | numpy, pytz, ... |

You bring the DataFrame library. KindTech brings the data.

## Why does this exist?

UK public data is powerful but painful to access programmatically. The ONS ArcGIS Geoportal has no developer documentation — just a point-and-click GUI. The REST API endpoint was discovered buried in the source code of an obscure UK government R package. NOMIS is slightly better documented but requires deep knowledge of SDMX query syntax and dataset codes that aren't surfaced anywhere obvious.

Every charity, social enterprise, and researcher working with UK geographic or statistical data ends up reverse-engineering the same APIs independently. KindTech wraps them so you don't have to — two function calls instead of hours of documentation archaeology.

## Interactive examples

Try these notebooks in your browser — no install needed:

| Notebook | Description |
|----------|-------------|
| [![Open in molab](https://marimo.io/molab-shield.svg)](https://molab.marimo.io/github/KindTechUK/kindtech/blob/main/examples/ons_statistics.py) | Browse and load ONS datasets from the NOMIS API |
| [![Open in molab](https://marimo.io/molab-shield.svg)](https://molab.marimo.io/github/KindTechUK/kindtech/blob/main/examples/geo_boundaries.py) | Explore UK geographic boundaries |
| [![Open in molab](https://marimo.io/molab-shield.svg)](https://molab.marimo.io/github/KindTechUK/kindtech/blob/main/examples/geo_plus_ons.py) | Join boundaries with statistics |

## Modules

- [**Geographic Data**](api/geo.md) — UK boundary data from ArcGIS (LAD, LSOA, etc.)
- [**ONS Statistics**](api/ons.md) — 1,615 datasets from the NOMIS API
- [**Case Studies**](case-studies/index.md) — Real-world examples from the charity sector
