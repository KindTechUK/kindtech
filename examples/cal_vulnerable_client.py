# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "marimo",
#     "kindtech",
#     "pandas>=2.0.0",
#     "numpy>=1.24.0",
#     "altair",
# ]
# ///

import marimo

__generated_with = "0.20.4"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo

    return (mo,)


@app.cell
def _(mo):
    mo.md("""
    # Citizens Advice Lewisham: Vulnerability Hotspots

    A reproduction of the [CAL case
    study](../docs/case-studies/cal-vulnerable-client.md) using **kindtech**.

    Citizens Advice Lewisham wanted to find **vulnerability hotspots** — areas
    of high need with limited access to help — and to check whether their
    clients actually come from the most deprived parts of the borough.

    This notebook combines:

    - **Postcode → LSOA** mapping (`kindtech.postcodes`, via postcodes.io) —
      how real client postcodes become a geography to aggregate on
    - **IMD 2025** deprivation by LSOA (`kindtech.imd`) — on **2021 LSOAs**, a
      native join to everything else
    - **Synthetic client records** — real client data is private, so we
      generate a realistic stand-in concentrated in more-deprived areas

    Everything joins on `geography_code` (2021 LSOA), so there is no crosswalk.
    """)
    return


@app.cell
def _():
    import altair as alt
    import numpy as np
    import pandas as pd

    from kindtech import (
        geodata_to_properties,
        load_geodata,
        load_imd,
        postcodes_to_geography,
    )

    return (
        alt,
        geodata_to_properties,
        load_geodata,
        load_imd,
        np,
        pd,
        postcodes_to_geography,
    )


@app.cell
def _(mo):
    run = mo.ui.run_button(label="Run analysis (fetches live data)")
    run
    return (run,)


@app.cell
def _(mo, run):
    mo.stop(not run.value, mo.md("*Click the button above to run.*"))
    return


@app.cell
def _(mo):
    mo.md("""
    ## Step 1: Postcodes → LSOA

    Real client records carry a postcode. `postcodes_to_geography` turns each
    into the LSOA it sits in — the unit we aggregate and map on. Here are a few
    real Lewisham postcodes to show the mechanism:
    """)
    return


@app.cell
def _(postcodes_to_geography, run):
    run.value
    sample = postcodes_to_geography(
        ["SE13 7HX", "SE6 4RU", "SE4 1AG", "SE23 1DA", "SE8 4AG"],
        geography_type="LSOA",
    )
    return (sample,)


@app.cell
def _(mo, sample):
    mo.ui.table(sample, selection=None)
    return


@app.cell
def _(mo):
    mo.md("""
    ## Step 2: Deprivation by LSOA (IMD 2025)

    Load the latest English deprivation index and keep Lewisham's LSOAs. IMD
    2025 is on **2021 LSOAs** and ships a population denominator, so we get
    deprivation *and* the per-capita base in one call.

    `imd_decile` runs 1 (most deprived 10% of England) to 10 (least deprived).
    """)
    return


@app.cell
def _(load_imd):
    imd = load_imd(nation="England")  # IoD 2025, 2021 LSOAs
    lewisham = imd[imd["geography_name"].str.startswith("Lewisham")][
        ["geography_code", "geography_name", "imd_score", "imd_decile", "population"]
    ].reset_index(drop=True)
    return (lewisham,)


@app.cell
def _(lewisham, mo):
    mo.md(
        f"Lewisham has **{len(lewisham)} LSOAs**, total population "
        f"**{int(lewisham['population'].sum()):,}**. Deprivation deciles range "
        f"from **{int(lewisham['imd_decile'].min())}** (most deprived) to "
        f"**{int(lewisham['imd_decile'].max())}**."
    )
    return


@app.cell
def _(mo):
    mo.md("""
    ## Step 3: LSOA boundaries

    Fetch just Lewisham's LSOA boundaries (super-generalised, 2021). The ONS
    service is queried by code; we batch the codes to keep each request URL a
    sensible length.
    """)
    return


@app.cell
def _(geodata_to_properties, lewisham, load_geodata, pd):
    def _fetch_lsoa_boundaries(codes, chunk=50):
        features = []
        for start in range(0, len(codes), chunk):
            batch = codes[start : start + chunk]
            geojson = load_geodata(
                "LSOA",
                year="2021",
                coverage="EW",
                boundary_type="BSC",
                LSOA21CD=batch,
            )
            features.extend(geojson["features"])
        return {"type": "FeatureCollection", "features": features}

    geojson = _fetch_lsoa_boundaries(lewisham["geography_code"].tolist())
    geo = pd.DataFrame(geodata_to_properties(geojson, "LSOA", 2021))[
        ["geography_code", "geography_name"]
    ]
    return geo, geojson


@app.cell
def _(geo, mo):
    mo.md(f"Loaded **{len(geo)} LSOA boundaries** for Lewisham.")
    return


@app.cell
def _(mo):
    mo.md("""
    ## Step 4: Synthetic client records

    Real client postcodes are private. We generate a realistic stand-in:
    clients are drawn per LSOA at a rate that **rises with deprivation**, so
    more-deprived areas produce more clients — deliberately setting up the
    correlation the case study tested for. `rng(11)` makes it reproducible.

    `clients_per_1000` normalises by population — the true measure of service
    demand, independent of how many people live in each LSOA.
    """)
    return


@app.cell
def _(geo, lewisham, np):
    base = lewisham.merge(geo[["geography_code"]], on="geography_code", how="inner")

    rng = np.random.default_rng(11)
    # Reach rises as deprivation rises (decile 1 = most deprived -> highest rate).
    deprivation_weight = (11 - base["imd_decile"]) / 10
    noise = rng.lognormal(mean=0.0, sigma=0.3, size=len(base))
    expected = base["population"] * 0.012 * deprivation_weight * noise
    base["clients"] = rng.poisson(np.maximum(expected, 0)).astype(int)
    base["clients_per_1000"] = 1000 * base["clients"] / base["population"]
    return (base,)


@app.cell
def _(base, mo):
    mo.md(
        f"Generated **{int(base['clients'].sum()):,} synthetic clients** across "
        f"{len(base)} LSOAs."
    )
    return


@app.cell
def _(mo):
    mo.md("""
    ## Step 5: Deprivation vs service usage

    Left: deprivation (IMD decile, dark = most deprived). Right: CAL clients per
    1,000 residents (dark = highest usage). If CAL is reaching the right areas,
    the two maps should look alike.
    """)
    return


@app.cell
def _(alt, base, geojson):
    def _choropleth(value_col, title, scheme, reverse):
        code_to_value = dict(zip(base["geography_code"], base[value_col], strict=False))
        features = []
        for f in geojson["features"]:
            props = f.get("properties", {})
            code = next(
                (
                    v
                    for k, v in props.items()
                    if k.endswith("CD") and v in code_to_value
                ),
                None,
            )
            if code is None:
                continue
            features.append(
                {
                    **f,
                    "properties": {
                        "geography_code": code,
                        value_col: code_to_value[code],
                    },
                }
            )
        return (
            alt.Chart(alt.Data(values=features))
            .mark_geoshape(stroke="white", strokeWidth=0.3)
            .encode(
                color=alt.Color(
                    f"properties.{value_col}:Q",
                    title=title,
                    scale=alt.Scale(scheme=scheme, reverse=reverse),
                ),
                tooltip=[
                    "properties.geography_code:N",
                    f"properties.{value_col}:Q",
                ],
            )
            .project(type="mercator")
            .properties(width=360, height=360, title=title)
        )

    # IMD decile: reverse so decile 1 (most deprived) is darkest.
    depr_map = _choropleth("imd_decile", "Deprivation (IMD decile)", "reds", True)
    usage_map = _choropleth("clients_per_1000", "CAL clients per 1,000", "reds", False)
    (depr_map | usage_map).resolve_scale(color="independent")
    return


@app.cell
def _(mo):
    mo.md("""
    ## Step 6: Does usage track deprivation?

    Plot each LSOA's deprivation score against its client rate. A rising trend
    means CAL's clients really do come from the most deprived areas —
    validating their targeting.
    """)
    return


@app.cell
def _(alt, base):
    correlation = base["imd_score"].corr(base["clients_per_1000"])
    scatter = (
        alt.Chart(base)
        .mark_circle(size=60, opacity=0.6)
        .encode(
            x=alt.X("imd_score:Q", title="IMD score (higher = more deprived)"),
            y=alt.Y("clients_per_1000:Q", title="CAL clients per 1,000"),
            tooltip=["geography_name:N", "imd_decile:Q", "clients_per_1000:Q"],
        )
        .properties(
            width=520,
            height=360,
            title=f"Deprivation vs service usage (r = {correlation:.2f})",
        )
    )
    scatter + scatter.transform_regression("imd_score", "clients_per_1000").mark_line(
        color="steelblue"
    )
    return (correlation,)


@app.cell
def _(correlation, mo):
    mo.md(f"""
    ## What this shows

    - **Hotspots line up**: the deprivation map and the client-usage map share
      the same dark areas — CAL's clients come disproportionately from the
      most-deprived LSOAs.
    - **Clear positive correlation** (r = **{correlation:.2f}**) between
      deprivation and clients per capita, validating CAL's geographic
      targeting — the direction the original study found.

    To run on real data, replace the synthetic clients with a list of client
    postcodes through `postcodes_to_geography(..., "LSOA")` (Step 1) and
    aggregate per `geography_code`. The IMD join, per-capita maths and maps are
    unchanged.
    """)
    return


if __name__ == "__main__":
    app.run()
