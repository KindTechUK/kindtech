# KindTech

Ergonomic Python access to UK public data. Geographic boundaries from the ONS ArcGIS Geoportal, statistics from the NOMIS API — with universal DataFrame support.

## Install

```bash
# Core package (lightweight — only requests + narwhals)
uv add kindtech

# Pick your DataFrame backend
uv add kindtech[pandas]   # or
uv add kindtech[polars]
```

## Quick start

```python
from kindtech.geo import load_geodata, GeographyType
from kindtech.ons import load_ons, list_tables

# Load Local Authority District boundaries (GeoJSON)
boundaries = load_geodata(geography_type="LAD", coverage="UK")

# Load ONS statistics (returns your preferred DataFrame type)
df = load_ons("NM_1_1", geography="TYPE480", time="latest")

# Browse available datasets
tables = list_tables(name="population")
```

## Bring Your Own DataFrame

KindTech uses [narwhals](https://narwhals-dev.github.io/narwhals/) for universal DataFrame support. The library itself has **no pandas or polars dependency** — it returns whatever backend you have installed.

```python
# With pandas installed → returns pd.DataFrame
uv add kindtech[pandas]

from kindtech.ons import load_ons
df = load_ons("NM_1_1")
type(df)  # <class 'pandas.core.frame.DataFrame'>
```

```python
# With polars installed → returns pl.DataFrame
uv add kindtech[polars]

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

## Modules

- [**Geographic Data**](api/geo.md) — UK boundary data from ArcGIS (LAD, LSOA, etc.)
- [**ONS Statistics**](api/ons.md) — 1,615 datasets from the NOMIS API
- [**Case Studies**](case-studies/index.md) — Real-world examples from the charity sector
