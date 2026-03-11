# ONS Statistics

The `kindtech.ons` module provides access to UK statistics from the [ONS NOMIS API](https://www.nomisweb.co.uk/api/v01/help). Returns DataFrames in your preferred backend (pandas or polars) via [narwhals](https://narwhals-dev.github.io/narwhals/).

## Functions

### `load_ons()`

Load statistical data from the NOMIS API.

```python
from kindtech.ons import load_ons

# Basic usage
df = load_ons("NM_1_1")

# With filters
df = load_ons(
    "NM_1_1",
    geography="TYPE480",
    time="latest",
    measures=20100,
)

# Multiple values for a parameter
df = load_ons("NM_1_1", measures=[20100, 20201])
```

#### Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `dataset_id` | `str` | *required* | NOMIS dataset code (e.g., `"NM_1_1"`) |
| `base_url` | `str` | NOMIS API URL | Override the API base URL |
| `**kwargs` | keyword args | | Query parameters passed to the NOMIS API |

Common query parameters:

- `geography` — Geography type (e.g., `"TYPE480"` for local authorities)
- `time` — Time period (e.g., `"latest"`, `"2023"`)
- `measures` — Measure codes (e.g., `20100` for value)
- `select` — Columns to return (list of strings)
- `sex` — Sex filter (e.g., `5` for male, `6` for female, `7` for total)

See the [NOMIS API docs](https://www.nomisweb.co.uk/api/v01/help) for the full parameter reference.

#### Returns

DataFrame (pandas or polars, depending on what's installed). If both are available, polars is preferred.

#### Raises

- `ValueError` — If the dataset doesn't exist or the response can't be parsed
- `ImportError` — If neither pandas nor polars is installed

!!! warning "Row limit"
    NOMIS returns a maximum of 25,000 rows per request. If your result has exactly 25,000 rows, it's likely truncated. Provide a NOMIS UID (`uid='0x...'`) to retrieve the full table.

---

### `list_tables()`

Browse available NOMIS datasets.

```python
from kindtech.ons import list_tables

# List all 1,615 datasets
all_tables = list_tables()

# Filter by name
pop_tables = list_tables(name="population")

# Filter by source
jsa_tables = list_tables(source="jsa")
```

#### Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `name` | `str` or `None` | `None` | Substring to filter dataset names (case-insensitive) |
| `source` | `str` or `None` | `None` | Source name to filter by |

#### Returns

DataFrame with columns: `id`, `name`, `sourceName`.

## Bring Your Own DataFrame

The ONS module uses [narwhals](https://narwhals-dev.github.io/narwhals/) for DataFrame interoperability. Install your preferred backend alongside kindtech:

```bash
uv add pandas   # or polars
```

The return type automatically matches your installed backend:

```python
import polars as pl
from kindtech.ons import load_ons

df = load_ons("NM_1_1", time="latest")
assert isinstance(df, pl.DataFrame)  # polars preferred when both installed
```

## How it works

1. The bundled CSV catalog (`ons/data/nomis_tables.csv`, 1,615 datasets) maps dataset IDs to names and sources
2. `load_ons()` builds a NOMIS API URL with your query parameters
3. Fetches CSV data from the NOMIS API
4. Parses into a DataFrame using your installed backend
5. Returns the native DataFrame (no narwhals wrapper exposed)
