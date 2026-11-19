# Postcodes

The `uk_open_data.postcodes` module turns UK postcodes (and postcode outcodes) into
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
from uk_open_data import postcodes_to_geography

located = postcodes_to_geography(["SE13 7HX", "SE6 4RU"], geography_type="LSOA")
#    postcode geography_code geography_name
# 0  SE13 7HX      E01034394  Lewisham 040C
# 1   SE6 4RU      E01003318  Lewisham 020B
```

Returns columns `postcode`, `geography_code`, `geography_name`. The
`geography_code` aligns with `geodata_to_properties()` and `load_ons()`, so the
result merges directly:

```python
import pandas as pd
from uk_open_data import postcodes_to_geography, load_geodata, load_ons, geodata_to_properties

# 1. Postcodes -> counts per LSOA
located = postcodes_to_geography(postcodes, "LSOA")
per_lsoa = located.groupby("geography_code").size().reset_index(name="count")

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
from uk_open_data import lookup_postcodes

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
from uk_open_data import lookup_outcodes

lookup_outcodes(["SE13", "M1"])
#   outcode  valid      admin_districts   latitude  longitude
# 0    SE13   True  Greenwich, Lewisham  51.459641  -0.009665
```

Columns: `outcode`, `valid`, `admin_districts` (comma-separated LAD names),
`latitude`, `longitude`.

### `outcode_to_geography()`

Approximate an outcode to a single geography via its centroid.

```python
from uk_open_data import outcode_to_geography

outcode_to_geography(["SE13"], geography_type="LSOA")
#   outcode geography_code geography_name
# 0    SE13      E01033327  Lewisham 041B
```

!!! warning "Outcode mapping is approximate"
    An outcode covers many LSOAs/wards. This returns the geography *containing
    the outcode's geometric centroid* — a rough stand-in, useful when your data
    is only tagged by postcode prefix. For per-area analysis (e.g. counts
    per capita by LSOA), prefer full postcodes via `postcodes_to_geography()`,
    or split an outcode's records across its constituent areas weighted by
    population.

## Looking up postcodes on this machine

The functions above send postcodes to postcodes.io. When the postcodes belong
to the people a charity helps, you may not want them to leave your machine.
The postcode table lets you look them up locally instead.

The table is one file of a few megabytes that maps every postcode in
England and Wales to its 2021 LSOA and local authority. It is built from the
ONS best-fit postcode lookup. Fetch it once:

```bash
uk-open-data postcodes download
```

!!! note "Before the first table is published"
    The first table is published with version 0.2. Until then
    `postcodes download` has nothing to fetch on its own: build a table from
    the ONS lookup with `uk-open-data postcodes build`, host it, and pass
    `--url` and `--sha256`.

or from Python with `download_postcode_table()`. The file is public and the
same for everyone, so fetching it says nothing about your data, and it is
checked against a SHA-256 before it is installed. After that, nothing below
uses the network:

```python
from uk_open_data.postcodes import (
    district_to_local_authorities,
    postcode_to_lsoa,
    postcodes_to_local_authority,
    postcodes_to_lsoa,
)

postcode_to_lsoa("se13 7vc")                # an LSOA code, or None
postcodes_to_lsoa(["SE13 7VC", "M1 1VC"])   # one answer per postcode, in order
postcodes_to_local_authority(["SE13 7VC"])  # local authority codes, in order
district_to_local_authorities("SE13")       # local authority codes, sorted
```

| Function | What it does |
| --- | --- |
| `download_postcode_table()` | Fetches and installs the table. Pass `url=` and `sha256=` to use a copy you host |
| `postcode_table_path()` | The installed table's path, or `None` |
| `postcode_table_info()` | Edition, source, coverage, size and the credits to show |
| `postcode_to_lsoa()`, `postcodes_to_lsoa()` | Postcode to 2021 LSOA code, or `None` when it is not in the table |
| `postcodes_to_local_authority()` | Postcode to local authority code, or `None` when it is not in the table |
| `district_to_local_authorities()` | The local authorities a postcode district reaches into |
| `build_postcode_table()` | Builds a table from the ONS lookup file. Used to publish a new edition |

The table lives in `~/.cache/uk-open-data`, or in the folder named by the
`UK_OPEN_DATA_DIR` environment variable. The old names, `~/.cache/kindtech`
and `KINDTECH_DATA_DIR`, still work. A server should fetch it when it is
built, not when a request arrives.

!!! note "Coverage and credits"
    The table covers England and Wales. Scotland and Northern Ireland are left
    out: neither has 2021 LSOAs, and Northern Ireland postcodes need a separate
    licence for commercial use. When you publish something made with the table,
    show the credits from `postcode_table_info()["attribution"]`: the ONS
    source line, and the OS and Royal Mail copyright lines.

[Analyses](analyses.md) use the table on their own when one is installed.

## Design

`uk_open_data.postcodes` is a thin runtime wrapper — unlike the `geo` and `ons`
modules it ships no catalog and has no ingestion step, because postcodes.io
serves the lookup directly. Requests are batched (100 postcodes per call, the
postcodes.io limit) and results preserve input order. DataFrames come back in
whatever backend you have installed (pandas or polars), like the rest of
KindTech.

See [Data Sources](data-sources.md#postcodesio) for the underlying datasets,
licensing, and limits.
