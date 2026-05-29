# Deprivation (IMD)

The `kindtech.imd` module loads the **composite UK Index of Multiple
Deprivation** — the four nations' official deprivation indices harmonised onto a
single UK-wide ranking — keyed on ONS geography codes so it joins to
[boundaries](geo.md) and [statistics](ons.md).

## Why a composite (not four separate indices)

Each UK nation publishes its own index on its own geography:

| Nation | Index | Geography | Areas |
|---|---|---|---|
| England | IMD 2019 | LSOA (2011) | 32,844 |
| Wales | WIMD 2019 | LSOA (2011) | 1,909 |
| Scotland | SIMD 2020 | Data Zone (2011) | 6,976 |
| Northern Ireland | NIMDM 2017 | Super Output Area | 890 |

Crucially, each index ranks areas **only within its own nation** — an English
"decile 1" and a Scottish "decile 1" are not the same thing. To compare
deprivation across the UK you need a single ranking. KindTech uses the
[mySociety composite UK IMD](https://github.com/mysociety/composite_uk_imd),
which re-ranks every area on one UK-wide scale.

## `load_imd()`

```python
from kindtech import load_imd

uk = load_imd()                      # all four nations, one UK ranking
england = load_imd(nation="England") # English LSOAs (2011) only
scotland = load_imd(nation="Scotland")
```

Returns one row per area with:

| Column | Description |
|---|---|
| `geography_code` | LSOA (England/Wales, 2011), Data Zone (Scotland), or SOA (NI) |
| `nation` | `E` / `W` / `S` / `N` |
| `imd_rank` | UK-wide rank (1 = most deprived) |
| `imd_decile` | UK-wide, population-weighted decile (1 = most deprived 10%) |
| `imd_quintile` | UK-wide, population-weighted quintile |
| `nation_decile` | Original within-nation decile (**not** comparable across nations) |
| `imd_score`, `income_score`, `employment_score`, `local_score` | Underlying scores |

`nation` accepts `"UK"` (default), `"England"`, `"Wales"`, `"Scotland"`,
`"Northern Ireland"`, or the single-letter codes `E`/`W`/`S`/`N`.

## Joining to boundaries and statistics

`geography_code` matches the rest of KindTech, so deprivation overlays onto a map
or merges with population for per-capita work:

```python
import pandas as pd
from kindtech import load_imd, load_geodata, geodata_to_properties

imd = load_imd(nation="England")
# English IMD is on 2011 LSOAs — use matching boundaries
geo = pd.DataFrame(geodata_to_properties(load_geodata("LSOA", year="2011"), "LSOA", 2011))

mapped = geo.merge(imd, on="geography_code", how="left")
```

!!! warning "LSOA vintage"
    English and Welsh IMD are published on **2011** LSOAs, while Census 2021 and
    the default LSOA boundaries are **2021** LSOAs. Join IMD to 2011 boundaries,
    map client postcodes via `lsoa11` (see [Postcodes](postcodes.md)), or use the
    planned 2011→2021 crosswalk. Scottish Data Zones and NI SOAs are unaffected.

## Licensing

The composite dataset is licensed
[CC-BY 4.0](https://creativecommons.org/licenses/by/4.0/) by mySociety; the
underlying national indices are Open Government Licence v3.0. See
[Data Sources](data-sources.md#composite-uk-imd) for details and attribution.
