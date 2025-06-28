# Geographic Data

The `kindtech.geo` module provides functions for loading and processing geographic data.

## Functions

### `load_geodata()`

```python
from kindtech import load_geodata

# Load geographic data from a specific source
data = load_geodata(source="uk_boundaries")

# Load geographic data from a file
data = load_geodata(filepath="/path/to/geodata.geojson")
```

#### Parameters

- **filepath** (*str, optional*): Path to the geographic data file.
- **source** (*str, optional*): Source identifier for pre-configured data sources.

#### Returns

- **dict**: Loaded geographic data.

#### Raises

- **ValueError**: If neither filepath nor source is provided.

## Examples

```python
# Load UK administrative boundaries
uk_boundaries = load_geodata(source="uk_boundaries")

# Load custom GeoJSON file
custom_geo = load_geodata(filepath="custom_boundaries.geojson")
```
