# Geographic Data

The `kindtech.geo` module provides access to UK geographic boundary data from the [ONS ArcGIS Geoportal](https://geoportal.statistics.gov.uk/).

## Functions

### `load_geodata()`

Load geographic boundary data as GeoJSON.

```python
from kindtech.geo import load_geodata, GeographyType, CoverageArea, BoundaryType

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
| `**filters` | keyword args | | Field filters (e.g., `LAD21NM="Manchester"`) |

#### Returns

`dict` — A GeoJSON FeatureCollection. Returns `{"type": "FeatureCollection", "features": []}` if no matching service is found or the request fails.

---

### `get_field_info()`

Get available fields for filtering a dataset.

```python
from kindtech.geo import get_field_info

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
from kindtech.geo import get_available_geography_types

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

## How it works

1. The bundled CSV catalog (`geo/data/arcgis_services.csv`, 70 services) maps geography type + year + coverage + boundary to an ArcGIS service ID
2. `load_geodata()` finds the best matching service (most recent year if not specified)
3. Queries the ArcGIS FeatureServer REST API for GeoJSON
4. Returns the raw GeoJSON FeatureCollection
