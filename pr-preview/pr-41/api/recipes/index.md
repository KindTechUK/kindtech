# Recipes for agents

Copy-paste snippets for the common tasks. Every connector returns a DataFrame
(pandas or polars, depending on what you have installed) keyed on
`geography_code` — that column is the universal join key across geography,
statistics, deprivation and postcodes.

## Install

```bash
uv add kindtech
```

## ONS statistics

```python
from kindtech.ons import load_ons

# Friendly alias + geography_type — no NOMIS TYPE codes needed
df = load_ons("population", geography_type="LAD", time="latest")

# Raw NOMIS dataset id, with filters and column selection
df = load_ons(
    "NM_1_1",
    geography_type="LAD",
    time="latest",
    measures=20100,
    select=["geography_code", "geography_name", "obs_value"],
)
```

## Geographic boundaries

```python
from kindtech.geo import load_geodata, geodata_to_properties

# GeoJSON FeatureCollection for Local Authority Districts
geo = load_geodata("LAD", year="2024", coverage="UK")

# Flatten to rows with geography_code / geography_name ready to join
rows = geodata_to_properties(geo, "LAD", 2024)
```

## Deprivation (IMD)

```python
from kindtech.imd import load_imd

# Official England IoD 2025 (defaults: nation-level latest)
imd = load_imd(nation="England")

# Cross-nation comparison uses the mySociety composite
uk = load_imd(nation="UK")  # year 2019
```

## Postcodes → geography

```python
from kindtech.postcodes import postcodes_to_geography, outcode_to_geography

# Postcodes resolved to LSOA, ready to join on geography_code
located = postcodes_to_geography(["SE13 7HX", "SE6 4RU"], geography_type="LSOA")

# Outcodes (the prefix before the space) resolved to the LADs they span
spans = outcode_to_geography(["SE13", "SE6"], geography_type="LAD")
```

## The join — combine sources on `geography_code`

This is the pattern the [case studies](../case-studies/index.md) use: load each
source, then merge on `geography_code`.

```python
import pandas as pd

from kindtech.geo import geodata_to_properties, load_geodata
from kindtech.imd import load_imd
from kindtech.ons import load_ons

# 1. Statistics and deprivation, both keyed on geography_code
pop = load_ons("population", geography_type="LAD", time="latest")
imd = load_imd(nation="England")

# 2. Boundaries, flattened to the same key
geo = load_geodata("LAD", year="2024", coverage="UK")
shapes = pd.DataFrame(geodata_to_properties(geo, "LAD", 2024))

# 3. Join everything on geography_code
merged = (
    shapes
    .merge(pop, on="geography_code", how="left")
    .merge(imd, on="geography_code", how="left")
)
```

## Discovery helpers

```python
from kindtech.ons import list_tables
from kindtech import list_dataset_aliases, list_geography_mappings

list_tables(name="population")    # search the bundled NOMIS catalog
list_dataset_aliases()            # friendly names → NOMIS dataset ids
list_geography_mappings()         # geography_type → NOMIS TYPE codes
```
