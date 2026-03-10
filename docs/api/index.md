# API Reference

KindTech provides two modules for accessing UK public data:

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

## Design principles

- **Flat functions** — no classes to instantiate, just call `load_geodata()` or `load_ons()`
- **String or enum** — pass `"LAD"` or `GeographyType.LAD`, both work
- **Bring your own DataFrame** — narwhals returns whatever backend you have installed
- **Bundled catalogs** — small CSV reference tables ship with the package (136KB total) so you can browse available datasets offline
- **Live data** — actual geographic/statistical data is always fetched fresh from the source APIs
