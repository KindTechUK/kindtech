# API Reference

KindTech provides four modules for accessing UK public data, and analyses that
put them to work on your own data:

## Modules

### [Geographic Data](geo.md) — `uk_open_data.geo`

Load UK geographic boundary data from the ONS ArcGIS Geoportal. Returns GeoJSON.

```python
from uk_open_data.geo import load_geodata

# Load Local Authority Districts
boundaries = load_geodata(geography_type="LAD", coverage="UK")
```

### [ONS Statistics](ons.md) — `uk_open_data.ons`

Load statistical data from the ONS NOMIS API. Returns pandas or polars DataFrames.

```python
from uk_open_data.ons import load_ons

# Load Jobseeker's Allowance data
df = load_ons("NM_1_1", geography="TYPE480", time="latest")
```

### [Postcodes](postcodes.md) — `uk_open_data.postcodes`

Resolve UK postcodes (and outcodes) to ONS geography codes via postcodes.io, so
address data joins to boundaries and statistics. Returns pandas or polars
DataFrames.

```python
from uk_open_data.postcodes import postcodes_to_geography

# Postcodes -> LSOA, ready to join on `geography_code`
located = postcodes_to_geography(["SE13 7HX", "SE6 4RU"], geography_type="LSOA")
```

### [Deprivation (IMD)](imd.md) — `uk_open_data.imd`

Load UK Indices of Multiple Deprivation, keyed on geography codes. A single
nation returns its **official** index (England IoD 2025/2019 with all domains,
or WIMD/SIMD/NIMDM); `nation="UK"` returns the mySociety composite for
cross-nation comparison. Returns pandas or polars DataFrames.

```python
from uk_open_data.imd import load_imd

imd = load_imd(nation="England")  # official IoD 2025; join on `geography_code`
```

### [Analyses](analyses.md) — `uk_open_data.analyses`

Ask a question of your own data. An analysis joins your table to open data and
returns figures with their sources, the working, the choices made and the
checks a person should do. Results hold totals only, never rows.

```python
from uk_open_data.analyses import run_analysis

result = run_analysis(
    "reach-deprivation", clients, columns={"postcode": "Client postcode"}
)
```

## Design principles

- **Flat functions** — no classes to instantiate, just call `load_geodata()` or `load_ons()`
- **String or enum** — pass `"LAD"` or `GeographyType.LAD`, both work
- **Bring your own DataFrame** — narwhals returns whatever backend you have installed
- **Bundled catalogs** — small CSV reference tables ship with the package (136KB total) so you can browse available datasets offline
- **Live data** — actual geographic/statistical data is always fetched fresh from the source APIs
