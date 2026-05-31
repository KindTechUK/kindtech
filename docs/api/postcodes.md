# Postcodes

The `kindtech.postcodes` module turns UK postcodes (and postcode outcodes) into
the ONS geography codes the rest of KindTech joins on. It wraps
[postcodes.io](https://postcodes.io/) — no API key required.

It's the layer that connects point-level address data to the common geography
types: any list of postcodes becomes a `geography_code` column — at LSOA, MSOA,
OA, LAD, ward, ICB or TTWA — that joins straight to boundaries
([`load_geodata`](geo.md)) and statistics ([`load_ons`](ons.md)).

## Functions

### `postcodes_to_geography()`

Map postcodes to a single geography level, ready to join.

```python
from kindtech import postcodes_to_geography

clients = postcodes_to_geography(["SE13 7HX", "SE6 4RU"], geography_type="LSOA")
#    postcode geography_code geography_name
# 0  SE13 7HX      E01034394  Lewisham 040C
# 1   SE6 4RU      E01003318  Lewisham 020B
```

Returns columns `postcode`, `geography_code`, `geography_name`. The
`geography_code` aligns with `geodata_to_properties()` and `load_ons()`, so the
result merges directly:

```python
import pandas as pd
from kindtech import postcodes_to_geography, load_geodata, load_ons, geodata_to_properties

# 1. Clients -> LSOA counts
clients = postcodes_to_geography(client_postcodes, "LSOA")
per_lsoa = clients.groupby("geography_code").size().reset_index(name="clients")

# 2. Population for per-capita, and boundaries for the map — same join key
pop = load_ons("population_lsoa", geography_type="LSOA", time="latest")
geo = pd.DataFrame(geodata_to_properties(load_geodata("LSOA"), "LSOA", 2021))

merged = geo.merge(per_lsoa, on="geography_code", how="left").merge(
    pop, on="geography_code", how="left"
)
```

Supported `geography_type` values: `LSOA`, `MSOA`, `OA`, `LAD`, `WD`, `ICB`,
`TTWA` (string or [`GeographyType`](geo.md) enum). An unsupported level raises
`ValueError`.

### `lookup_postcodes()`

The full lookup — one row per postcode with every geography level at once.

```python
from kindtech import lookup_postcodes

df = lookup_postcodes(["SE13 7HX", "M1 1AE", "NOTAPC"])
```

Columns: `postcode`, `valid`, `lsoa_code`/`lsoa_name`, `msoa_code`/`msoa_name`,
`oa_code`, `lad_code`/`lad_name`, `ward_code`, `icb_code`, `ttwa_code`,
`latitude`, `longitude`.

!!! note "Invalid postcodes are flagged, not dropped"
    Unrecognised postcodes return a row with `valid=False` and `None` codes, so
    the output always lines up with the input. Filter with
    `df[df["valid"]]` when you only want matches.

### `lookup_outcodes()`

Look up postcode **outcodes** — the prefix before the space (e.g. `SE13`). An
outcode spans many areas, so this returns the *list* of Local Authorities it
touches plus the outcode's geometric centroid.

```python
from kindtech import lookup_outcodes

lookup_outcodes(["SE13", "M1"])
#   outcode  valid      admin_districts   latitude  longitude
# 0    SE13   True  Greenwich, Lewisham  51.459641  -0.009665
```

Columns: `outcode`, `valid`, `admin_districts` (comma-separated LAD names),
`latitude`, `longitude`.

### `outcode_to_geography()`

Approximate an outcode to a single geography via its centroid.

```python
from kindtech import outcode_to_geography

outcode_to_geography(["SE13"], geography_type="LSOA")
#   outcode geography_code geography_name
# 0    SE13      E01033327  Lewisham 041B
```

!!! warning "Outcode mapping is approximate"
    An outcode covers many LSOAs/wards. This returns the geography *containing
    the outcode's geometric centroid* — a rough stand-in, useful when your data
    is only tagged by postcode prefix. For per-area analysis (e.g. referrals
    per capita by LSOA), prefer full postcodes via `postcodes_to_geography()`,
    or split an outcode's records across its constituent areas weighted by
    population.

## Design

`kindtech.postcodes` is a thin runtime wrapper — unlike the `geo` and `ons`
modules it ships no catalog and has no ingestion step, because postcodes.io
serves the lookup directly. Requests are batched (100 postcodes per call, the
postcodes.io limit) and results preserve input order. DataFrames come back in
whatever backend you have installed (pandas or polars), like the rest of
KindTech.

See [Data Sources](data-sources.md#postcodesio) for the underlying datasets,
licensing, and limits.
