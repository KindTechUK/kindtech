# Deprivation (IMD)

The `kindtech.imd` module loads UK deprivation data, keyed on ONS geography
codes so it joins to [boundaries](geo.md) and [statistics](ons.md).

**A single nation returns that nation's _official_ index. `"UK"` returns a
composite — the only way to compare deprivation _across_ nations.**

## Official per nation, composite for comparison

Each UK nation publishes its own index, on its own geography, ranked **only
within its own borders** — an English "decile 1" and a Scottish "decile 1" are
not the same thing:

| Nation | Official index | Geography | Areas |
|---|---|---|---|
| England | IoD 2025 (or 2019) | LSOA 2021 (2019: LSOA 2011) | 33,755 / 32,844 |
| Wales | WIMD 2019 | LSOA 2011 | 1,909 |
| Scotland | SIMD 2020 | Data Zone 2011 | 6,976 |
| Northern Ireland | NIMDM 2017 | SOA | 890 |

To compare *across* nations you need one shared ranking. There is no official
UK-wide index, so KindTech uses the
[mySociety composite UK IMD](https://github.com/mysociety/composite_uk_imd)
(`nation="UK"`), which re-ranks every area onto one scale. The composite is a
third-party harmonisation, **not** a National Statistic — use it for
comparison, and a nation's official index for within-nation work.

## `load_imd()`

```python
from kindtech import load_imd

england = load_imd(nation="England")          # official IoD 2025, 2021 LSOAs
england_19 = load_imd(nation="England", year=2019)  # official IoD 2019, 2011 LSOAs
wales = load_imd(nation="Wales")              # official WIMD (within-nation)
uk = load_imd()                               # composite, cross-nation comparison
```

`nation` accepts `"UK"` (default), `"England"`, `"Wales"`, `"Scotland"`,
`"Northern Ireland"`, or the codes `E`/`W`/`S`/`N`.

### `nation="England"` — official English Indices of Deprivation

The richest path: gov.uk **File 7** (all ranks, scores, deciles and population
denominators). `year=2025` (default, **2021** LSOAs) or `year=2019` (**2011**
LSOAs) — same schema, so 2019 → 2025 is a clean change comparison.

Returns `geography_code`, `geography_name`, `nation`, `lad_code`, `lad_name`,
the overall `imd_score`/`imd_rank`/`imd_decile`, a `score` + `rank` + `decile`
for each of the **seven domains** (`income`, `employment`, `education`,
`health`, `crime`, `housing` = barriers to housing & services,
`living_environment`; e.g. `income_rank`, `income_decile`), and a `population`
denominator. Ranks/deciles are within-England (rank 1 / decile 1 = most
deprived).

### `nation="Wales"` / `"Scotland"` / `"Northern Ireland"` — official, within-nation

Each nation's own official index, fetched from its government source (WIMD 2019,
SIMD 2020, NIMDM 2017). These publish **ranks** (1 = most deprived), so the
output is `geography_code` (LSOA / Data Zone / SOA), `geography_name`, `nation`,
the overall `imd_rank`, a within-nation `imd_decile` derived from that rank, and
a `<domain>_rank` for each of that nation's domains. The **domain sets differ
by nation** (only income/employment/health/education/access are shared):

| Nation | Source | Domains (`<domain>_rank`) | Extra |
|---|---|---|---|
| Wales (WIMD 2019) | gov.wales (ODS) | income, employment, health, education, access, housing, **community_safety**, **physical_environment** | — |
| Scotland (SIMD 2020) | gov.scot (XLSX) | income, employment, health, education, access, **crime**, housing | `population` |
| N. Ireland (NIMDM 2017) | Open Data NI (CSV) | income, employment, health, education, access, **living_environment**, **crime_disorder** | — |

!!! note "2025 availability"
    Only **England** has a 2025 index. `load_imd(nation="Wales", year=2025)`
    raises — WIMD 2025 has no stable machine-readable download on StatsWales
    yet. Scotland and NI have no 2025 release at all.

!!! note "Reading XLSX/ODS sources"
    Wales (ODS) and Scotland (XLSX) are spreadsheets, read via
    [`python-calamine`](https://pypi.org/project/python-calamine/) (a KindTech
    dependency). No extra setup needed.

### `nation="UK"` — composite (cross-nation comparison)

Returns `geography_code` (LSOA 2011 / Data Zone / SOA), `nation`, and:

| Column | Description |
|---|---|
| `imd_rank` | **UK-wide** rank (1 = most deprived) |
| `imd_decile` | **UK-wide**, population-weighted decile |
| `imd_quintile` | **UK-wide**, population-weighted quintile |
| `nation_decile` | The official within-nation decile (**not** UK-comparable) |
| `imd_score`, `income_score`, `employment_score`, `local_score` | Underlying scores |

Use this only when comparing areas in different nations; its `imd_rank` /
`imd_decile` are the UK re-ranking, not a nation's official figures (those are
in `nation_decile`, or use the single-nation calls above).

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
    **England IoD 2025** is on **2021** LSOAs, so it joins natively to Census
    2021 and the default boundaries — no crosswalk needed. This is the easiest
    path for English analysis.

    Everything else — **England IoD 2019**, the **composite (`nation="UK"`)**,
    and Wales/Scotland/NI — is on **2011** geographies. To join those, either
    use 2011 boundaries (`load_geodata("LSOA", year="2011")`) or map postcodes
    via `lsoa11` (see [Postcodes](postcodes.md)).

## Licensing

The composite dataset is licensed
[CC-BY 4.0](https://creativecommons.org/licenses/by/4.0/) by mySociety; the
underlying national indices are Open Government Licence v3.0. See
[Data Sources](data-sources.md#composite-uk-imd) for details and attribution.
