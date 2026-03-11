# How We Found the APIs Behind UK Public Data

## Posted March 2026

This is the story of how we reverse-engineered the programmatic APIs behind
two major UK public data portals — the
[ONS Open Geography Portal](https://geoportal.statistics.gov.uk/) (boundary
maps) and [NOMIS](https://www.nomisweb.co.uk/) (labour market and census
statistics). Neither exposes a clean, well-documented developer API. Both
turned out to have one hiding behind their web interfaces.

This is a good case study for anyone trying to build programmatic access to
a government service that was designed for humans clicking buttons in
browsers.

---

## The starting point: click, download, unzip, repeat

If you work with UK geographic or statistical data, you know the drill.

For **boundary data** (local authority districts, wards, regions, output
areas), you go to the
[ONS Open Geography Portal](https://geoportal.statistics.gov.uk/). You
browse hundreds of datasets. You find the one you want — say, Local
Authority Districts for 2024 in generalised clipped resolution. You pick a
format (GeoJSON, Shapefile, KML). You click download. You unzip. You load
it into your GIS tool or DataFrame library.

Now do that for every geography type (24 of them), every year, every
resolution. Good luck.

For **statistics** (employment, population, housing, deprivation), you go to
[NOMIS](https://www.nomisweb.co.uk/). You browse 1,600+ datasets through
their [query builder](https://www.nomisweb.co.uk/query/advanced.aspx). You
select measures, geographies, and time periods. You download a CSV. Then you
realise you wanted a different geography level and start over.

None of this is scriptable. You can't write a pipeline that pulls the latest
boundaries and joins them with unemployment data. You end up with a `data/`
folder full of manually downloaded files that go stale the moment ONS
publishes an update.

---

## Part 1: The ONS Geoportal is just ArcGIS

### Finding the backend

The [Open Geography Portal](https://geoportal.statistics.gov.uk/) —
officially "The UK's official Office for National Statistics Open Data
Geography Site" — looks like a bespoke government website. It was
[launched in July 2020](https://www.arcgis.com/sharing/rest/portals/ESMARspQHYMw9BZ9?f=json)
as an [Esri ArcGIS Hub](https://hub.arcgis.com/) deployment, though the
ONS Geography team has been using
[ArcGIS Online since June 2015](https://www.arcgis.com/sharing/rest/community/users/ONSGeography_data?f=json).

If you open DevTools and watch the network requests, it becomes clear: every
boundary dataset is served as an ArcGIS FeatureServer under the ONS
organisation ID `ESMARspQHYMw9BZ9` (you can verify this at
[`ons.maps.arcgis.com`](https://ons.maps.arcgis.com)).

Once we knew this, the URL pattern was straightforward:

```
https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services/
  LAD_DEC_2024_UK_BGC/FeatureServer/0/query?where=1%3D1&outFields=*&f=geojson
```

Standard [ArcGIS REST API](https://developers.arcgis.com/rest/services-reference/online/).
`where=1=1` gets all features, `outFields=*` selects all columns,
`f=geojson` returns GeoJSON. No authentication needed. The data is public,
licensed under
[OGL v3.0](https://www.ons.gov.uk/methodology/geography/licences), and the
API is fully functional — it's just not advertised.

ONS doesn't publish their own API documentation for this endpoint. They rely
on Esri's standard
[ArcGIS REST API reference](https://developers.arcgis.com/rest/services-reference/online/).

### The catalog problem

The hard part isn't querying a single dataset — it's discovering which
datasets exist. The portal's
[services listing page](https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services/)
renders its content with client-side JavaScript. If you fetch the HTML with
`requests` and parse it with BeautifulSoup, you get an empty `<ul>` — the
list items are injected by JavaScript after page load. Scraping doesn't work.

We tried several approaches:

1. **HTML scraping** — zero results (JS-rendered page)
2. **`?f=pjson`** (ArcGIS pretty-printed JSON) — works but intermittently
   returns empty results
3. **`?f=json`** — the winner

Appending `?f=json` to the services root gives you a machine-readable
catalog:

```
https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services?f=json
```

This returns ~3,700 services (the portal hosts
[over 1,200 FeatureServers](https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services?f=json)
plus MapServers, lookup tables, and other service types). We filter for
`"type": "FeatureServer"` and parse the service names to extract metadata.

!!! warning "Rate limiting"
    The JSON endpoint is intermittently rate-limited. Some requests return an
    empty `services` array. If ingestion returns 0 services, wait a minute
    and try again — it's the API being flaky, not the code.

### Parsing the service names

This is where things got interesting. The ArcGIS catalog has two naming
conventions, both following the
[GSS Coding and Naming Policy](https://www.ons.gov.uk/methodology/geography/geographicalproducts/namescodesandlookups)
(implemented 1 January 2011):

**Short form** (most common, used for newer datasets):
```
LAD_DEC_2024_UK_BGC
│   │   │    │  └── Resolution: Generalised Clipped Boundaries
│   │   │    └───── Coverage: United Kingdom
│   │   └────────── Year: 2024
│   └────────────── Month: December
└────────────────── Geography: Local Authority Districts
```

**Long form** (older datasets, pre-2021):
```
Local_Authority_Districts_December_2024_Boundaries_UK_BGC
```

The short-form naming was introduced around 2021 (see the
[Boundary Dataset Guidance: 2021 Onwards](https://geoportal.statistics.gov.uk/datasets/ons::boundary-dataset-guidance-2021-onwards/about)).
Pre-2021 datasets on [data.gov.uk](https://www.data.gov.uk/) use full
descriptive titles like "Counties and Unitary Authorities (December 2016)
Full Clipped Boundaries in England and Wales". We wrote a regex for
short-form names and a prefix-mapping table for long-form names. Both
normalise into the same schema: `(geography, year, month, region,
resolution)`.

**Resolution codes** — the
[ONS digital boundaries page](https://www.ons.gov.uk/methodology/geography/geographicalproducts/digitalboundaries)
defines five standard resolutions:

| Code | Full name | Detail |
|------|-----------|--------|
| BFE | Full resolution, Extent of the Realm | Mean Low Water mark |
| BFC | Full resolution, Clipped to coastline | Mean High Water mark |
| BGC | Generalised Clipped | 20m tolerance |
| BSC | Super Generalised Clipped | 200m tolerance |
| BUC | Ultra Generalised Clipped | 500m tolerance |

Older ArcGIS service names use rearranged abbreviations for the same
resolutions:

| Old service suffix | New service suffix |
|--------------------|-------------------|
| FCB | BFC |
| FEB | BFE |
| GCB | BGC |
| SGCB | BSC |
| UGCB | BUC |

These old abbreviations don't appear in official ONS documentation — the
pre-2021 convention used full descriptive text ("Full Clipped Boundaries",
"Generalised Clipped Boundaries", etc.), not abbreviations. The FCB/GCB
codes seem to be an ArcGIS-internal convention. Our ingestion normalises
all of them to the current standard.

### The weird entries

When we first ran the ingestion across all geography types (not just LAD),
the catalog contained some surprises.

**Historical datasets going back to 1921:**

| Service | Year | Geography |
|---------|------|-----------|
| `CTRY_DEC_1921_GB_BGC` | 1921 | Countries |
| `CTY_DEC_1921_EW_BGC` | 1921 | Counties |
| `ED_1971_EW_BGC` | 1971 | Enumeration Districts |
| `ED_1981_EW_BGC` | 1981 | Enumeration Districts |
| `WD_1998_UK_BGC` | 1998 | Wards |

These are legitimate. The ONS maintains
[historical census boundaries](https://geoportal.statistics.gov.uk/)
as part of their geographic products — the 1921 boundaries were digitised
and published around the 2021 Census centenary. The 1971 and 1981 entries
are [Enumeration Districts](https://www.ons.gov.uk/census/2001censusandearlier/glossary/ag)
(EDs) — the operational geographic units used for censuses from 1961 to
1991, where each ED represented the workload for a single census
enumerator. EDs were
[superseded by Output Areas (OAs)](https://www.ons.gov.uk/census/2001censusandearlier/dataandproducts/outputgeography/outputareas)
for the 2001 Census, which were designed specifically for statistical
purposes rather than operational ones. We keep all historical entries in the
catalog.

**Same-year "duplicates" that aren't duplicates:**

We found ~60 entries where the same geography type appeared multiple times
for the same year. At first this looked like a bug. On closer inspection,
they're different monthly releases:

```
WD_MAY_2024_UK_BGC    # Wards as of May 2024
WD_DEC_2024_UK_BGC    # Wards as of December 2024
```

Administrative boundaries
[change during the year](https://www.ons.gov.uk/methodology/geography/ukgeographies/administrativegeography/ourchanginggeography/boundarychanges)
(mergers, splits, name changes). **May** boundaries reflect changes that
take effect on the first Thursday in May (local election day), when ward
and division boundary reviews by the Local Government Boundary Commission
come into force. **December** boundaries provide a year-end snapshot aligned
with the 1 December reference date used for electoral statistics since 2001.
The month column in our catalog differentiates these.

**Genuinely different datasets sharing a composite key:**

We found 9 cases where two services had the same
`(geography, year, month, region, resolution)` tuple. We investigated each
one by querying the ArcGIS field metadata:

1. **Short-form + long-form names** for the same dataset (e.g.,
   `LAD_DEC_2008_GB_BGC` and
   `Local_Authority_Districts_December_2008_Boundaries_GB_BGC`). Same data,
   different name. Harmless duplicates.

2. **NHSER variants** — "NHS England Regions" (`nhser18cd`) vs "NHS England
   Region Local Offices" (`nhsrlo18cd`). These represent different
   [administrative levels](https://www.ons.gov.uk/methodology/geography/ukgeographies/healthgeography).
   When NHS England was created in 2013, it had 27 Area Teams. In 2015 these
   were restructured into a smaller number of Local Offices sitting below the
   7 Regions. The Local Office tier was
   [effectively abolished by April 2020](https://geoportal.statistics.gov.uk/datasets/ons::nhs-england-region-local-office-to-nhs-england-region-april-2017-lookup-in-en/about).
   10 fields each, but different field codes — genuinely different datasets.

3. **OA RUC variants** — Output Areas with and without the
   [Rural-Urban Classification](https://www.ons.gov.uk/methodology/geography/geographicalproducts/ruralurbanclassifications)
   (12 vs 17 columns). Same geometries, different attribute sets. The
   [RUC](https://www.ons.gov.uk/methodology/geography/geographicalproducts/ruralurbanclassifications/2021ruralurbanclassification),
   first introduced in 2004 and updated for each census, classifies OAs as
   urban (in built-up areas of 10,000+ population) or rural, with further
   subdivision into settlement types and sparsity levels.

4. **Trailing underscore typos** — `Wards_May_2024_Boundaries_UK_BFE_`
   (note the trailing `_`). We strip these during ingestion.

We decided to keep all entries and let the runtime catalog handle selection.
No hardcoded skip lists, no manual curation — the raw data goes into the CSV
as-is (minus typo cleanup).

### What we ended up with

The geo ingestion parses ~3,700 ArcGIS services down to **615 boundary
datasets** across **24 geography types**, spanning from 1921 to 2025. The
entire ingestion is stdlib-only — just `csv`, `re`, and `requests`.

```bash
uv run python -m kindtech.geo._ingestion
# Successfully ingested 615 services
```

---

## Part 2: NOMIS has an API (we just used it wrong at first)

### What is NOMIS?

[NOMIS](https://www.nomisweb.co.uk/home/about.asp) is a web-based database
of labour market and population statistics, operated by the
**University of Durham** on behalf of the Office for National Statistics.
It was [first launched in **1981**](https://www.nomisweb.co.uk/home/about.asp)
— making it one of the longest-running official statistical web services in
the UK. It provides free access to data on employment, unemployment,
earnings, population, and Census results, all licensed under the
[Open Government Licence](https://www.nomisweb.co.uk/home/copyright.asp).

### The R package that pointed the way

We knew NOMIS had an API at
[`nomisweb.co.uk/api/v01`](https://www.nomisweb.co.uk/api/v01/help). But
the [documentation](https://www.nomisweb.co.uk/api/v01/help) is
comprehensive yet hard to navigate, and the website pushes you toward the
interactive [query builder](https://www.nomisweb.co.uk/query/advanced.aspx).

The breakthrough was finding
[**nomisr**](https://github.com/ropensci/nomisr), an R package by
[Evan Odell](https://orcid.org/0000-0003-1845-808X) (published in
[JOSS, July 2018](https://doi.org/10.21105/joss.00859), peer-reviewed under
[rOpenSci](https://ropensci.org/)). Reading its source code (~700 lines, 13
files) showed us the key endpoints:

- **`dataset/def.sdmx.json`** — bulk listing of all datasets in
  [SDMX](https://sdmx.org/) JSON format
- **`dataset/{id}.data.csv`** — data download as CSV with query parameters
- **`contenttype/sources.json`** — source groupings (Census, Annual
  Population Survey, etc.)
- **`dataset/{id}/{concept}/def.sdmx.xml`** — dimension metadata in SDMX-ML

The SDMX (Statistical Data and Metadata eXchange,
[ISO 17369](https://sdmx.org/?page_id=5008)) format is worth a note: NOMIS
uses SDMX 2.0 structures (KeyFamilies, Dimensions, Codelists), and their
JSON serialisation (`.sdmx.json`) is a NOMIS-specific convenience — not the
later SDMX-JSON standard from SDMX 2.1. The standard format is XML
(`.sdmx.xml`), which is what nomisr uses for metadata queries via the
[rsdmx](https://cran.r-project.org/package=rsdmx) package.

!!! note "nomisr status"
    nomisr was [removed from CRAN](https://cran.r-project.org/web/packages/nomisr/index.html)
    in July 2025 due to a policy violation. The source is still available on
    [GitHub](https://github.com/ropensci/nomisr). There are
    **no official client libraries** from NOMIS, ONS, or Durham University —
    all wrappers are community-built.

### The N+1 query trap

Our first ingestion approach was:

1. Fetch the bulk dataset listing (1 request) — gives us IDs and names
2. For each dataset, fetch its individual overview to extract the source
   annotation (1,615 requests)

Step 2 took minutes. Some requests would timeout. Two datasets (`NM_45_1`
and `NM_2064_1`) consistently failed, so we added a hardcoded skip list.

This is wrong. We looked at every NOMIS wrapper in the ecosystem:

| Package | Language | Skip lists? |
|---------|----------|-------------|
| [nomisr](https://github.com/ropensci/nomisr) | R | None |
| [UKCensusAPI](https://github.com/virgesmith/UKCensusAPI) | Python | None (skips specific *fields*, not datasets) |
| [nomisweb](https://github.com/ouseful-datasupply/nomisweb) | Python | None |
| [Consensus](https://github.com/Ilkka-LBL/Consensus) | Python | None |

Nobody maintains skip lists. The datasets aren't broken — we were just
making too many requests.

### The fix: read the response you already have

When we looked more carefully at the bulk listing response
(`dataset/def.sdmx.json`), we realised the source annotation was already
there — embedded in each dataset's `annotations` array:

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

1,572 out of 1,615 datasets have the `contenttype/sources` annotation right
there in the bulk listing. The remaining 43 genuinely lack source information
— they get an empty `sourceName`, no skip list needed.

The rewritten ingestion makes **one HTTP request** and completes in **~6
seconds**:

```bash
uv run python -m kindtech.ons._ingestion
# Successfully ingested 1615 NOMIS tables
```

Down from 1,616 requests and several minutes.

### The NOMIS "weird entries"

NOMIS has its own historical curiosities. The catalog includes:

- **31 datasets from the 1961 Census** (NM_1230 through NM_1257) — dwelling
  types, population by nationality, household arrangements, worker surveys.
  These were
  [digitised and uploaded around January 2021](https://www.nomisweb.co.uk/api/v01/dataset/NM_1230_1.overview.json)
  (based on the `LastUpdated` annotation), covering England and Wales at
  district, county, parish, ward, and enumeration district levels.
- **1981 and 1991 Census data** — small area statistics and workplace
  statistics.
- **1968 SIC VAT registrations** — industrial classification data using the
  1968 Standard Industrial Classification.

These are all legitimate. NOMIS serves as the UK's long-term statistical
archive, not just current data. The 1961 Census tables were digitised
decades after the original census — which explains why a 1960s dataset
might show a 2021 upload date in its metadata.

The two datasets we originally skipped (`NM_45_1` — "JSA seasonally
adjusted", `NM_2064_1` — "TS046 Central heating") are completely normal.
They are among the 43 datasets that lack `contenttype/sources` annotations
in the bulk listing. When we stopped making per-dataset overview requests,
they stopped causing problems.

### NOMIS rate limits and authentication

For reference, the
[official limits](https://www.nomisweb.co.uk/api/v01/help):

| Access level | Limit |
|---|---|
| Guest (unauthenticated) | 25,000 cells per request |
| Authenticated (with UID) | No cell limit |
| KML / RSS formats | 1,000 cells |

Authentication is free — create an account on nomisweb.co.uk and get a
Unique ID (UID) from "my account" > "web services". This is relevant for
`load_ons()` users who hit the 25,000 cell truncation warning.

---

## The pattern: APIs hiding behind portals

Both the ONS Geoportal and NOMIS follow the same pattern:

1. A **user-facing portal** optimised for manual browsing and downloading
2. A **backend API** that the portal calls internally, but which isn't
   prominently documented for developers
3. **Naming conventions** and **metadata formats** that encode rich
   information if you know how to parse them

The API is there. It's just not the intended interface. The portal is. But
once you find the API, you can build proper programmatic access and
democratise what was previously a click-and-download-and-unzip workflow.

This pattern is common across UK government data services. The data is
public and freely licensed
([OGL v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/)),
but the access patterns are optimised for a human with a browser. Packages
like kindtech, nomisr, and UKCensusAPI exist to bridge that gap.

---

## How it all fits together in kindtech

```
                    Ingestion (dev-time)              Runtime
                    ┌─────────────────┐    ┌──────────────────────────┐
ArcGIS REST API ──> │ geo/_ingestion  │──> │ data/arcgis_services.csv │
  ?f=json           │ parse names     │    │ (615 services)           │
  (~3,700 services) │ normalise codes │    │         ↓                │
                    └─────────────────┘    │ _catalog.find_services() │
                                           │         ↓                │
                                           │ api.load_geodata()       │
                                           │   → ArcGIS query         │
                    ┌─────────────────┐    │                          │
NOMIS SDMX JSON ──>│ ons/_ingestion  │──> │ data/nomis_tables.csv    │
  def.sdmx.json     │ extract annots  │    │ (1,615 datasets)         │
  (1 request)       │                 │    │         ↓                │
                    └─────────────────┘    │ _catalog.list_tables()   │
                                           │         ↓                │
                                           │ api.load_ons()           │
                                           │   → NOMIS CSV download   │
                                           └──────────────────────────┘
```

Both ingestion scripts are stdlib-only — just `csv`, `re`, and `requests`.
No pandas, no polars, no BeautifulSoup. They run as CLI tools and the
resulting CSV catalogs ship with the package.

Users never need to run ingestion. They call `load_geodata()` or
`load_ons()` and get data back as a DataFrame in whatever backend they
prefer. The catalog lookup is instant (CSV loaded at import time), and the
only network request at runtime is for the actual data.

### Running ingestion

To refresh the catalogs (e.g., when ONS publishes new boundaries or NOMIS
adds new datasets):

```bash
# Geo boundaries — ~3,700 services parsed to 615 boundary datasets
uv run python -m kindtech.geo._ingestion

# ONS statistics — 1,615 datasets in one request
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
- [Enumeration Districts and Output Areas](https://www.ons.gov.uk/census/2001censusandearlier/dataandproducts/outputgeography/outputareas) — ED to OA transition
- [Licensing terms (OGL v3.0)](https://www.ons.gov.uk/methodology/geography/licences)
- [ArcGIS REST services directory](https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services/)
- [ArcGIS REST API reference (Esri)](https://developers.arcgis.com/rest/services-reference/online/)
- [ONS ArcGIS Online organisation](https://ons.maps.arcgis.com)

### NOMIS

- [NOMIS homepage](https://www.nomisweb.co.uk/)
- [About NOMIS](https://www.nomisweb.co.uk/home/about.asp) — operated by University of Durham for ONS, since 1981
- [API documentation](https://www.nomisweb.co.uk/api/v01/help)
- [Copyright and licensing](https://www.nomisweb.co.uk/home/copyright.asp) — OGL, attribution: "Source: Office for National Statistics"
- [Dataset listing (SDMX JSON)](https://www.nomisweb.co.uk/api/v01/dataset/def.sdmx.json)
- [Content type sources](https://www.nomisweb.co.uk/api/v01/contenttype/sources.json)
- [Query builder](https://www.nomisweb.co.uk/query/advanced.aspx)

### Community packages

- [nomisr](https://github.com/ropensci/nomisr) — R, Evan Odell, rOpenSci. [JOSS paper (2018)](https://doi.org/10.21105/joss.00859)
- [UKCensusAPI](https://github.com/virgesmith/UKCensusAPI) — Python, virgesmith
- [nomisweb](https://github.com/ouseful-datasupply/nomisweb) — Python, Tony Hirst
- [Consensus](https://github.com/Ilkka-LBL/Consensus) — Python, Ilkka-LBL

### Standards

- [SDMX (Statistical Data and Metadata eXchange)](https://sdmx.org/) — ISO 17369
- [Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/)
