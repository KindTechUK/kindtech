# Geographic Data

The `uk_open_data.geo` module provides access to UK geographic boundary data from the [ONS ArcGIS Geoportal](https://geoportal.statistics.gov.uk/).

## Functions

### `load_geodata()`

Load geographic boundary data as GeoJSON.

```python
from uk_open_data.geo import load_geodata, GeographyType, CoverageArea, BoundaryType

# Using strings
data = load_geodata(geography_type="LAD", coverage="UK", boundary_type="BGC")

# Using enums
data = load_geodata(
    geography_type=GeographyType.LAD,
    coverage=CoverageArea.UK,
    boundary_type=BoundaryType.BGC,
)

# With filters
manchester = load_geodata(geography_type="LAD", LAD21NM="Manchester")
```

#### Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `geography_type` | `str` or `GeographyType` | *required* | Geography level (e.g., `"LAD"`, `"LSOA"`) |
| `year` | `str` or `None` | `None` | Year of the data (e.g., `"2021"`) |
| `month` | `str`, `Month`, or `None` | `None` | Month (e.g., `"DEC"`, `Month.DEC`) |
| `coverage` | `str`, `CoverageArea`, or `None` | `None` | Coverage area (`"UK"`, `"GB"`, `"EW"`) |
| `boundary_type` | `str`, `BoundaryType`, or `None` | `"BGC"` | Boundary resolution |
| `simplify_m` | `float` or `None` | `None` | Ask the service to leave out detail finer than about this many metres |
| `**filters` | keyword args | | Field filters (e.g., `LAD21NM="Manchester"`) |

#### Simpler outlines

The ONS publishes most layers at several resolutions, and `boundary_type` picks one. Some layers are public only at full resolution and at 200 m, which is too heavy or too rough for a map of one town. For those, ask for the full-resolution layer and let the service simplify it:

```python
codes = ["E01003189", "E01003190"]
outlines = load_geodata(
    "LSOA", year="2021", boundary_type="BFE", simplify_m=20, LSOA21CD=codes
)
```

A full-extent layer (`BFE`) runs to the low water mark and to the middle of a river, so it colours water as land on a map drawn large. Where a layer clipped to the shore is published (`BFC`), ask for that one. The service simplifies each outline by itself, so two neighbours may no longer share exactly the same edge; keep the distance small against the size of the map.

#### Returns

`dict` — A GeoJSON FeatureCollection. Returns `{"type": "FeatureCollection", "features": []}` if no matching service is found or the request fails.

The ONS boundary service gives a few thousand features in one answer. A larger layer, such as every neighbourhood, is fetched page by page, so the collection holds every feature. If any page fails, the collection is empty and an error is logged: you never get a part of a layer as if it were the whole. A large layer with outlines takes many requests; filter by code when you need only some areas.

---

### `get_field_info()`

Get available fields for filtering a dataset.

```python
from uk_open_data.geo import get_field_info

fields = get_field_info(geography_type="LAD")
# [{"name": "LAD21CD", "type": "esriFieldTypeString", "alias": "LAD Code"}, ...]
```

#### Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `geography_type` | `str` or `GeographyType` | *required* | Geography level |
| `year` | `str` or `None` | `None` | Year |
| `coverage` | `str`, `CoverageArea`, or `None` | `None` | Coverage area |
| `boundary_type` | `str`, `BoundaryType`, or `None` | `None` | Boundary resolution |

#### Returns

`list[dict]` — Field metadata from ArcGIS (name, type, alias, etc.).

---

### `get_available_geography_types()`

List all supported geography types.

```python
from uk_open_data.geo import get_available_geography_types

types = get_available_geography_types()
# [{"code": "LAD", "description": "Local Authority Districts"}, ...]
```

---

### `get_available_boundary_types()`

List all supported boundary resolutions.

---

### `get_available_coverage_areas()`

List all supported coverage areas.

## Enums

All enums accept both string codes and enum values. They have `.code` and `.description` attributes.

| Enum | Values | Example |
|---|---|---|
| `GeographyType` | LAD, LSOA, MSOA, ... | `GeographyType.LAD` |
| `BoundaryType` | BFC, BFE, BGC, BSC | `BoundaryType.BGC` |
| `CoverageArea` | UK, GB, EW | `CoverageArea.UK` |
| `Month` | JAN through DEC | `Month.DEC` |

---

### `geodata_to_properties()`

Extract feature properties from GeoJSON with normalised column names for easy joins with ONS data.

```python
from uk_open_data import load_geodata, geodata_to_properties
import pandas as pd

geojson = load_geodata(geography_type="LAD", year="2024")
rows = geodata_to_properties(geojson, "LAD", 2024)
geo_df = pd.DataFrame(rows)
# geo_df has 'geography_code' and 'geography_name' columns
# plus all original ArcGIS properties (LAD24CD, LAD24NM, etc.)
```

#### Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `geojson` | `dict` | *required* | GeoJSON FeatureCollection from `load_geodata()` |
| `geography_type` | `str` or `GeographyType` | *required* | Geography level (e.g., `"LAD"`, `"LSOA"`) |
| `year` | `int` or `str` | *required* | Year of the data (e.g., `2024`) |

#### Returns

`list[dict]` — One dict per feature, containing:

- `geography_code` — normalised geography code (e.g. `E06000001`), derived from the year-stamped ArcGIS field (e.g. `LAD24CD`)
- `geography_name` — normalised geography name (e.g. `Hartlepool`), derived from the year-stamped ArcGIS field (e.g. `LAD24NM`)
- All original ArcGIS properties preserved as-is

The normalised `geography_code` column matches the column produced by `load_ons(normalize=True)`, enabling trivial joins:

```python
from uk_open_data import load_geodata, load_ons, geodata_to_properties
import pandas as pd

geojson = load_geodata(geography_type="LAD", year="2024")
geo_df = pd.DataFrame(geodata_to_properties(geojson, "LAD", 2024))
ons_df = load_ons("population", geography_type="LAD", time="latest")
merged = geo_df.merge(ons_df, on="geography_code")
```

## How it works

1. The bundled CSV catalog (`geo/data/arcgis_services.csv`, 654 services across 24 geography types) maps geography type + year + coverage + boundary to an ArcGIS service ID
2. `load_geodata()` finds the best matching service (most recent year if not specified)
3. Queries the ArcGIS FeatureServer REST API for GeoJSON
4. Returns the raw GeoJSON FeatureCollection
5. `geodata_to_properties()` extracts feature properties and adds normalised `geography_code` / `geography_name` columns using `geo_code_field()` and `geo_name_field()` from the internal mapping module
