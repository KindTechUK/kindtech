# API Reference

KindTech provides four modules for accessing UK public data:

## Modules

### [Geographic Data](geo.md) — `kindtech.geo`

Load UK geographic boundary data from the ONS ArcGIS Geoportal. Returns GeoJSON.

```python
from kindtech.geo import load_geodata

# Load Local Authority Districts
boundaries = load_geodata(geography_type="LAD", coverage="UK")
```

### [ONS Statistics](ons.md) — `kindtech.ons`

Load statistical data from the ONS NOMIS API. Returns pandas or polars DataFrames.

```python
from kindtech.ons import load_ons

# Load Jobseeker's Allowance data
df = load_ons("NM_1_1", geography="TYPE480", time="latest")
```

### [Postcodes](postcodes.md) — `kindtech.postcodes`

Resolve UK postcodes (and outcodes) to ONS geography codes via postcodes.io, so
address data joins to boundaries and statistics. Returns pandas or polars
DataFrames.

```python
from kindtech.postcodes import postcodes_to_geography

# Postcodes -> LSOA, ready to join on `geography_code`
located = postcodes_to_geography(["SE13 7HX", "SE6 4RU"], geography_type="LSOA")
```

### [Deprivation (IMD)](imd.md) — `kindtech.imd`

Load the composite UK Index of Multiple Deprivation — the four nations' indices
harmonised onto one UK-wide ranking — keyed on geography codes. Returns pandas or
polars DataFrames.

```python
from kindtech.imd import load_imd

imd = load_imd(nation="England")  # join on `geography_code`
```

## Design principles

- **Flat functions** — no classes to instantiate, just call `load_geodata()` or `load_ons()`
- **String or enum** — pass `"LAD"` or `GeographyType.LAD`, both work
- **Bring your own DataFrame** — narwhals returns whatever backend you have installed
- **Bundled catalogs** — small CSV reference tables ship with the package (136KB total) so you can browse available datasets offline
- **Live data** — actual geographic/statistical data is always fetched fresh from the source APIs
