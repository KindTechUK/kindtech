# Data Sources

KindTech wraps two UK public data APIs that aren't prominently documented for
developers. This page documents the APIs, their quirks, and how kindtech's
ingestion scripts work.

---

## ONS Open Geography Portal (ArcGIS)

The [Open Geography Portal](https://geoportal.statistics.gov.uk/) serves UK
boundary data as an [Esri ArcGIS Hub](https://hub.arcgis.com/) deployment
under the ONS organisation ID `ESMARspQHYMw9BZ9`. It was
[launched in July 2020](https://www.arcgis.com/sharing/rest/portals/ESMARspQHYMw9BZ9?f=json),
though the ONS Geography team has used
[ArcGIS Online since June 2015](https://www.arcgis.com/sharing/rest/community/users/ONSGeography_data?f=json).

### Endpoints

| Endpoint | Description |
|---|---|
| `https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services?f=json` | Service catalog (JSON) |
| `.../{service_name}/FeatureServer/0/query?where=1%3D1&outFields=*&f=geojson` | Query features as GeoJSON |
| `https://www.arcgis.com/sharing/rest/portals/ESMARspQHYMw9BZ9?f=json` | Organisation metadata |
| `https://www.arcgis.com/sharing/rest/community/users/ONSGeography_data?f=json` | User profile |

Standard [ArcGIS REST API](https://developers.arcgis.com/rest/services-reference/online/).
No authentication needed. Licensed under
[OGL v3.0](https://www.ons.gov.uk/methodology/geography/licences). ONS does
not publish their own API documentation — they rely on Esri's standard
reference.

### Catalog discovery

The portal's
[services listing page](https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services/)
renders with client-side JavaScript — HTML scraping returns an empty `<ul>`.
Appending `?f=json` returns a machine-readable JSON catalog of ~3,700 services
(~1,200 FeatureServers plus MapServers, lookup tables, and other types).

!!! warning "Rate limiting"
    The JSON endpoint is intermittently rate-limited. Some requests return an
    empty `services` array. If ingestion returns 0 services, wait and retry.

### Service naming conventions

The catalog uses two naming conventions, both following the
[GSS Coding and Naming Policy](https://www.ons.gov.uk/methodology/geography/geographicalproducts/namescodesandlookups)
(implemented 1 January 2011):

**Short form** (post-2021):
```
LAD_DEC_2024_UK_BGC
│   │   │    │  └── Resolution: Generalised Clipped Boundaries
│   │   │    └───── Coverage: United Kingdom
│   │   └────────── Year: 2024
│   └────────────── Month: December
└────────────────── Geography: Local Authority Districts
```

**Long form** (pre-2021):
```
Local_Authority_Districts_December_2024_Boundaries_UK_BGC
```

The transition happened around 2021 (see
[Boundary Dataset Guidance: 2021 Onwards](https://geoportal.statistics.gov.uk/datasets/ons::boundary-dataset-guidance-2021-onwards/about)).

### Resolution codes

The [ONS digital boundaries page](https://www.ons.gov.uk/methodology/geography/geographicalproducts/digitalboundaries)
defines five standard resolutions:

| Code | Full name | Detail |
|------|-----------|--------|
| BFE | Full resolution, Extent of the Realm | Mean Low Water mark |
| BFC | Full resolution, Clipped to coastline | Mean High Water mark |
| BGC | Generalised Clipped | 20m tolerance |
| BSC | Super Generalised Clipped | 200m tolerance |
| BUC | Ultra Generalised Clipped | 500m tolerance |

Older ArcGIS service names use rearranged abbreviations:

| Old suffix | Current suffix |
|------------|---------------|
| FCB | BFC |
| FEB | BFE |
| GCB | BGC |
| SGCB | BSC |
| UGCB | BUC |

These old codes don't appear in official ONS documentation — they are an
ArcGIS-internal convention. The ingestion normalises all of them to the
current standard.

### Catalog quirks

**Historical datasets (1921-present):**

| Service | Year | Geography |
|---------|------|-----------|
| `CTRY_DEC_1921_GB_BGC` | 1921 | Countries |
| `CTY_DEC_1921_EW_BGC` | 1921 | Counties |
| `ED_1971_EW_BGC` | 1971 | Enumeration Districts |
| `ED_1981_EW_BGC` | 1981 | Enumeration Districts |
| `WD_1998_UK_BGC` | 1998 | Wards |

The 1921 boundaries were digitised around the 2021 Census centenary. The
1971/1981 entries are
[Enumeration Districts](https://www.ons.gov.uk/census/2001censusandearlier/glossary/ag)
(EDs) — operational units used for censuses 1961-1991, each representing one
enumerator's workload. EDs were
[superseded by Output Areas](https://www.ons.gov.uk/census/2001censusandearlier/dataandproducts/outputgeography/outputareas)
for the 2001 Census.

**May vs December releases:**

Administrative boundaries
[change during the year](https://www.ons.gov.uk/methodology/geography/ukgeographies/administrativegeography/ourchanginggeography/boundarychanges).
**May** boundaries reflect changes taking effect on local election day (first
Thursday in May). **December** boundaries provide a year-end snapshot aligned
with the 1 December reference date used for electoral statistics since 2001.

**Composite-key duplicates (9 cases):**

1. **Short-form + long-form names** for the same dataset — harmless duplicates
2. **NHSER variants** — "NHS England Regions" (`nhser18cd`) vs "NHS England
   Region Local Offices" (`nhsrlo18cd`), different
   [administrative levels](https://www.ons.gov.uk/methodology/geography/ukgeographies/healthgeography).
   Local Offices were created in 2015 (from 27 Area Teams of 2013) and
   [abolished by April 2020](https://geoportal.statistics.gov.uk/datasets/ons::nhs-england-region-local-office-to-nhs-england-region-april-2017-lookup-in-en/about)
3. **OA RUC variants** — Output Areas with and without the
   [Rural-Urban Classification](https://www.ons.gov.uk/methodology/geography/geographicalproducts/ruralurbanclassifications)
   (12 vs 17 columns). The
   [RUC](https://www.ons.gov.uk/methodology/geography/geographicalproducts/ruralurbanclassifications/2021ruralurbanclassification),
   first introduced in 2004, classifies OAs as urban or rural
4. **Trailing underscore typos** — stripped during ingestion

All entries are kept in the catalog. No skip lists, no manual curation.

### Geo ingestion

Parses ~3,700 ArcGIS services down to **615 boundary datasets** across **24
geography types**, spanning 1921-2025. Stdlib-only (`csv`, `re`, `requests`).

```bash
uv run python -m kindtech.geo._ingestion
```

---

## NOMIS API

[NOMIS](https://www.nomisweb.co.uk/home/about.asp) is a web-based database of
labour market and population statistics, operated by the **University of
Durham** on behalf of ONS
[since 1981](https://www.nomisweb.co.uk/home/about.asp). Licensed under the
[Open Government Licence](https://www.nomisweb.co.uk/home/copyright.asp).

### Endpoints

| Endpoint | Description |
|---|---|
| `dataset/def.sdmx.json` | Bulk listing of all datasets (SDMX JSON) |
| `dataset/{id}.data.csv?{params}` | Data download as CSV |
| `contenttype/sources.json` | Source groupings |
| `dataset/{id}.overview.json` | Dataset overview |
| `dataset/{id}/{concept}/def.sdmx.xml` | Dimension metadata (SDMX-ML) |

Base URL: `https://www.nomisweb.co.uk/api/v01/`

[Full API documentation](https://www.nomisweb.co.uk/api/v01/help)

### SDMX format

NOMIS uses [SDMX](https://sdmx.org/) 2.0 structures (KeyFamilies, Dimensions,
Codelists). The `.sdmx.json` format is a NOMIS-specific convenience — not the
standard SDMX-JSON from SDMX 2.1
([ISO 17369](https://sdmx.org/?page_id=5008)). The standard format is XML
(`.sdmx.xml`).

### Rate limits and authentication

| Access level | Limit |
|---|---|
| Guest (unauthenticated) | 25,000 cells per request |
| Authenticated (with UID) | No cell limit |
| KML / RSS formats | 1,000 cells |

Authentication is free — create an account on nomisweb.co.uk and get a UID
from "my account" > "web services".

!!! warning "Cell limit"
    The limit is 25,000 **cells** (not rows). If your result has exactly
    25,000 rows, it's likely truncated. Pass a NOMIS UID to retrieve the
    full table.

### Source annotations in the bulk listing

The bulk listing (`dataset/def.sdmx.json`) includes source annotations
embedded in each dataset's `annotations` array:

```json
{
  "id": "NM_1_1",
  "name": {"value": "Jobseeker's Allowance with rates and proportions"},
  "annotations": {
    "annotation": [
      {"annotationtitle": "contenttype/sources", "annotationtext": "jsa"},
      {"annotationtitle": "LastUpdated", "annotationtext": "2025-01-14"}
    ]
  }
}
```

1,572 out of 1,615 datasets have the `contenttype/sources` annotation in the
bulk listing. The remaining 43 genuinely lack source information.

### Catalog quirks

- **31 datasets from the 1961 Census** (NM_1230-NM_1257) —
  [digitised around January 2021](https://www.nomisweb.co.uk/api/v01/dataset/NM_1230_1.overview.json),
  covering England and Wales at district, county, parish, ward, and
  enumeration district levels
- **1981/1991 Census data** — small area and workplace statistics
- **1968 SIC VAT registrations** — industrial classification data

NOMIS is a long-term statistical archive, not just current data.

### NOMIS ingestion

Makes **one HTTP request** to `dataset/def.sdmx.json`, extracts IDs, names,
and source annotations. Completes in ~6 seconds for 1,615 datasets.
Stdlib-only (`csv`, `requests`).

```bash
uv run python -m kindtech.ons._ingestion
```

### Community packages

No official client libraries from NOMIS, ONS, or Durham University. All
wrappers are community-built:

| Package | Language | Notes |
|---------|----------|-------|
| [nomisr](https://github.com/ropensci/nomisr) | R | Evan Odell, rOpenSci. [JOSS (2018)](https://doi.org/10.21105/joss.00859). Removed from CRAN July 2025 |
| [UKCensusAPI](https://github.com/virgesmith/UKCensusAPI) | Python | virgesmith |
| [nomisweb](https://github.com/ouseful-datasupply/nomisweb) | Python | Tony Hirst |
| [Consensus](https://github.com/Ilkka-LBL/Consensus) | Python | Ilkka-LBL |

---

## Geography Crosswalk

The geo module uses ONS geography type codes (`LAD`, `LSOA`, `MSOA`, etc.)
while NOMIS uses internal TYPE codes (`TYPE424`, `TYPE151`, etc.). KindTech
maps between them so you don't have to.

### Using `geography_type` in `load_ons()`

Instead of looking up NOMIS TYPE codes, pass the same geography type you
use with `load_geodata()`:

```python
from kindtech import load_geodata, load_ons

# Same geography concept, different APIs
boundaries = load_geodata(geography_type="LAD", year="2024")
statistics = load_ons("NM_1_1", geography_type="LAD", time="latest")
```

The raw `geography="TYPE424"` parameter still works if you need it.

### TYPE code mapping

NOMIS assigns different TYPE codes to the same geography at different time
points. KindTech resolves these automatically based on the `time` parameter:

| Geography | Year range | NOMIS TYPE |
|-----------|-----------|------------|
| LAD | 2023+ | TYPE424 |
| LAD | 2021-2022 | TYPE431 |
| LAD | 2019-2020 | TYPE434 |
| LAD | 2015-2018 | TYPE446 |
| LAD | pre-2015 | TYPE464 |
| CTYUA | 2023+ | TYPE423 |
| CTYUA | 2021-2022 | TYPE431 |
| CTYUA | 2015-2020 | TYPE446 |
| CTYUA | pre-2015 | TYPE463 |
| LSOA | 2021+ | TYPE151 |
| LSOA | pre-2021 | TYPE304 |
| MSOA | 2021+ | TYPE152 |
| MSOA | pre-2021 | TYPE305 |
| RGN | all | TYPE480 |
| CTRY | all | TYPE499 |
| WD | 2025+ | TYPE182 |
| CAUTH | 2025+ | TYPE442 |
| TTWA | 2011+ | TYPE447 |
| TTWA | pre-2011 | TYPE444 |
| ITL | 2025+ | TYPE419 |
| ITL | 2021-2024 | TYPE421 |

Source: NOMIS geography dimension metadata. To list all mappings
programmatically:

```python
from kindtech import list_geography_mappings

for m in list_geography_mappings():
    print(m)
```

### Join keys

Both APIs return standard ONS geography codes (e.g. `E06000001`):

- **ArcGIS** returns fields like `LAD24CD` (code) and `LAD24NM` (name),
  where the field name includes a 2-digit year suffix
- **NOMIS** returns `GEOGRAPHY_CODE` and `GEOGRAPHY_NAME` columns

The `geo_code_field()` and `geo_name_field()` helpers derive the ArcGIS
field names:

```python
from kindtech._mapping import geo_code_field, geo_name_field

geo_code_field("LAD", 2024)  # "LAD24CD"
geo_name_field("LAD", 2024)  # "LAD24NM"
```

---

## Architecture

KindTech ingests from two completely separate APIs into two independent CSV
catalogs. They share no data or endpoints — one provides geographic
boundaries (maps), the other provides statistical tables (numbers).

```
┌─────────────────────────────────────────────────────────────────────┐
│                        TWO SEPARATE DATA SOURCES                    │
├──────────────────────────────┬──────────────────────────────────────┤
│                              │                                      │
│  ONS Open Geography Portal   │  NOMIS                               │
│  (ArcGIS FeatureServer)      │  (Durham University for ONS)         │
│  geoportal.statistics.gov.uk │  nomisweb.co.uk                      │
│                              │                                      │
│  What: UK boundary maps      │  What: UK statistics                  │
│  Format: GeoJSON polygons    │  Format: CSV tabular data             │
│                              │                                      │
├──────────────────────────────┼──────────────────────────────────────┤
│                              │                                      │
│  INGESTION (dev-time)        │  INGESTION (dev-time)                 │
│                              │                                      │
│  Source URL:                 │  Source URL:                           │
│  services1.arcgis.com/       │  nomisweb.co.uk/api/v01/              │
│    ESMARspQHYMw9BZ9/         │    dataset/def.sdmx.json              │
│    arcgis/rest/services      │                                      │
│    ?f=json                   │  1 HTTP request → parse JSON          │
│                              │  → extract id, name, source           │
│  1 HTTP request → parse JSON │    from annotations                   │
│  → regex-parse ~3,700        │                                      │
│    service names             │  Output:                              │
│  → normalise resolution      │  ons/data/nomis_tables.csv            │
│    codes                     │  (1,615 datasets)                     │
│                              │                                      │
│  Output:                     │  uv run python -m                     │
│  geo/data/arcgis_services.csv│    kindtech.ons._ingestion            │
│  (615 boundary datasets)     │                                      │
│                              │                                      │
│  uv run python -m            │                                      │
│    kindtech.geo._ingestion   │                                      │
│                              │                                      │
├──────────────────────────────┼──────────────────────────────────────┤
│                              │                                      │
│  RUNTIME (user-facing)       │  RUNTIME (user-facing)                │
│                              │                                      │
│  load_geodata("LAD")         │  load_ons("NM_1_1", time="latest")   │
│    → look up CSV catalog     │    → look up CSV catalog              │
│    → query ArcGIS            │    → query NOMIS                      │
│      FeatureServer           │      dataset/{id}.data.csv            │
│    → return GeoJSON dict     │    → return DataFrame                 │
│                              │      (pandas or polars)               │
│                              │                                      │
└──────────────────────────────┴──────────────────────────────────────┘
```

Both ingestion scripts are stdlib-only (`csv`, `re`, `requests`). The
resulting CSV catalogs ship with the package. Users never run ingestion —
they call `load_geodata()` or `load_ons()` and get data back as GeoJSON or
a DataFrame.

To refresh the catalogs when ONS publishes updates:

```bash
# Geo boundaries — from ArcGIS
uv run python -m kindtech.geo._ingestion

# Statistics — from NOMIS
uv run python -m kindtech.ons._ingestion
```

Then commit the updated CSV files.

---

## References

### ONS Open Geography Portal

- [Portal homepage](https://geoportal.statistics.gov.uk/)
- [ONS Geography overview](https://www.ons.gov.uk/methodology/geography)
- [Digital boundaries (resolution types)](https://www.ons.gov.uk/methodology/geography/geographicalproducts/digitalboundaries)
- [Names, codes and lookups (GSS policy)](https://www.ons.gov.uk/methodology/geography/geographicalproducts/namescodesandlookups)
- [Boundary Dataset Guidance: 2021 Onwards](https://geoportal.statistics.gov.uk/datasets/ons::boundary-dataset-guidance-2021-onwards/about)
- [Boundary changes](https://www.ons.gov.uk/methodology/geography/ukgeographies/administrativegeography/ourchanginggeography/boundarychanges) — May vs December release cycle
- [Rural-Urban Classification](https://www.ons.gov.uk/methodology/geography/geographicalproducts/ruralurbanclassifications)
- [Health geographies](https://www.ons.gov.uk/methodology/geography/ukgeographies/healthgeography) — NHSER, ICB, Local Offices
- [Statistical geographies](https://www.ons.gov.uk/methodology/geography/ukgeographies/statisticalgeographies) — OA, LSOA, MSOA hierarchy
- [Enumeration Districts and Output Areas](https://www.ons.gov.uk/census/2001censusandearlier/dataandproducts/outputgeography/outputareas)
- [Licensing terms (OGL v3.0)](https://www.ons.gov.uk/methodology/geography/licences)
- [ArcGIS REST services directory](https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services/)
- [ArcGIS REST API reference (Esri)](https://developers.arcgis.com/rest/services-reference/online/)
- [ONS ArcGIS Online organisation](https://ons.maps.arcgis.com)

### NOMIS

- [NOMIS homepage](https://www.nomisweb.co.uk/)
- [About NOMIS](https://www.nomisweb.co.uk/home/about.asp) — University of Durham for ONS, since 1981
- [API documentation](https://www.nomisweb.co.uk/api/v01/help)
- [Copyright and licensing](https://www.nomisweb.co.uk/home/copyright.asp) — OGL, "Source: Office for National Statistics"
- [Dataset listing (SDMX JSON)](https://www.nomisweb.co.uk/api/v01/dataset/def.sdmx.json)
- [Content type sources](https://www.nomisweb.co.uk/api/v01/contenttype/sources.json)
- [Query builder](https://www.nomisweb.co.uk/query/advanced.aspx)

### Standards

- [SDMX (Statistical Data and Metadata eXchange)](https://sdmx.org/) — ISO 17369
- [Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/)
