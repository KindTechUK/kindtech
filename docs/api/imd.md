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

Two vintages are available via `year`:

| `year` | Source | Geography | Comparable across UK? |
|---|---|---|---|
| `2019` | Composite UK IMD (2017–2020 indices) | LSOA 2011 / DZ / SOA | **Yes** — one UK ranking |
| `2025` | Latest national index | **LSOA 2021** | No — within-nation |

`year` defaults to the **latest available** for the chosen nation: `2025` for
England, `2019` (composite) for the UK as a whole and for Wales/Scotland/NI.

```python
from kindtech import load_imd

uk = load_imd()                              # composite (no UK-wide 2025 exists)
england = load_imd(nation="England")         # IoD 2025 — latest, 2021 LSOAs + domains
england_19 = load_imd(nation="England", year=2019)  # composite English areas
```

### `year=2019` — composite UK (default)

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

### `year=2025` — latest national index

The four nations refresh on independent cycles, so 2025 is **per-nation**, not
UK-wide:

| Nation | Latest | `year=2025` |
|---|---|---|
| England | IMD 2025 (2021 LSOAs) | ✅ supported |
| Wales | WIMD 2025 (2021 LSOAs) | ⏳ pending — StatsWales has no stable machine-readable download yet |
| Scotland | SIMD 2020 | ❌ no 2025 release — use `year=2019` |
| N. Ireland | NIMDM 2017 | ❌ no 2025 release — use `year=2019` |

```python
imd25 = load_imd(nation="England", year=2025)
```

Returns `geography_code` (**2021** LSOA), `geography_name`, `nation`,
`lad_code`, `lad_name`, the overall `imd_score`/`imd_rank`/`imd_decile`, and a
score + decile for each of the **seven domains**: `income`, `employment`,
`education`, `health`, `crime`, `housing` (barriers to housing & services),
`living_environment`. Deciles are within-nation (1 = most deprived 10% of
English LSOAs). Calling `year=2025` for the UK, Wales, Scotland or NI raises a
`ValueError` explaining what to use instead.

## Joining to boundaries and statistics

`geography_code` matches the rest of KindTech, so deprivation overlays onto a map
or merges with population for per-capita work:

```python
import pandas as pd
from kindtech import load_imd, load_geodata, geodata_to_properties

imd = load_imd(nation="England")  # IoD 2025, on 2021 LSOAs
# Default boundaries are 2021 LSOAs — a native join, no crosswalk
geo = pd.DataFrame(geodata_to_properties(load_geodata("LSOA"), "LSOA", 2021))

mapped = geo.merge(imd, on="geography_code", how="left")
```

!!! warning "LSOA vintage"
    The **composite (`year=2019`)** is on **2011** LSOAs, while Census 2021 and
    the default LSOA boundaries are **2021** LSOAs. To join the composite,
    either use 2011 boundaries (`load_geodata("LSOA", year="2011")`) or map
    client postcodes via `lsoa11` (see [Postcodes](postcodes.md)).

    The **latest data (`year=2025`)** is already on **2021** LSOAs, so it joins
    natively to Census 2021 and the default boundaries — no crosswalk needed.
    This is the easiest path for English analysis.

## Licensing

The composite dataset is licensed
[CC-BY 4.0](https://creativecommons.org/licenses/by/4.0/) by mySociety; the
underlying national indices are Open Government Licence v3.0. See
[Data Sources](data-sources.md#composite-uk-imd) for details and attribution.
