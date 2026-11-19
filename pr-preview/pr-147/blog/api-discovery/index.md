# How We Found the APIs Behind UK Public Data

If you work with UK geographic or statistical data, you know the drill: browse
a portal, click download, unzip, load into your tool, realise you need a
different geography level, start over. None of it is scriptable.

We wanted to build a Python package that lets you write
`load_geodata(geography_type="LAD")` and get GeoJSON back. Or
`load_ons("NM_1_1", time="latest")` and get a DataFrame. No manual downloads,
no stale files.

The problem: neither the
[ONS Open Geography Portal](https://geoportal.statistics.gov.uk/) nor
[NOMIS](https://www.nomisweb.co.uk/) prominently documents a developer API.
Both turned out to have one hiding behind their web interfaces.

## The ONS Geoportal is just ArcGIS

The Open Geography Portal looks like a bespoke government website. Open
DevTools and you'll see every boundary dataset is served by an ArcGIS
FeatureServer. The URL pattern is straightforward once you know it:

```
https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services/
  LAD_DEC_2024_UK_BGC/FeatureServer/0/query?where=1%3D1&outFields=*&f=geojson
```

No authentication. Public data. Standard ArcGIS REST API.

The harder problem was discovering *which* datasets exist. The portal's
service listing page is JS-rendered — scraping returns nothing. Appending
`?f=json` to the services URL gives you a machine-readable catalog of ~3,700
services. From there, parsing the service names extracts geography type, year,
month, coverage area, and resolution.

We ended up with 615 boundary datasets across 24 geography types, spanning
1921 to 2025.

## NOMIS has an API (we just used it wrong)

[NOMIS](https://www.nomisweb.co.uk/home/about.asp) — run by Durham University
for ONS since 1981 — does have
[API docs](https://www.nomisweb.co.uk/api/v01/help), but the website pushes
you toward the interactive query builder. The breakthrough was reading the
source of [nomisr](https://github.com/ropensci/nomisr), an R package by Evan
Odell ([JOSS, 2018](https://doi.org/10.21105/joss.00859)), which showed us the
key endpoints.

Our first ingestion fetched metadata for each of 1,615 datasets individually —
classic N+1 problem. When we looked closer at the bulk listing response
(`dataset/def.sdmx.json`), we found the source annotations were already
embedded in each dataset's `annotations` array. One request, ~6 seconds, done.

## The pattern

Both portals follow the same pattern: a user-facing website optimised for
manual browsing, backed by an API that works fine for programmatic access but
isn't the intended interface. The data is public and freely licensed
([OGL v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/)),
the APIs are functional — they're just not advertised.

For the full technical details — endpoints, naming conventions, resolution
codes, catalog quirks, ingestion architecture, and 30+ reference links — see
the [Data Sources](../api/data-sources.md) reference.
