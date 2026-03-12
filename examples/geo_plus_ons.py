# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "marimo",
#     "kindtech",
#     "pandas>=2.0.0",
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
    # Geo + ONS: Joining Boundaries with Statistics

    This notebook demonstrates combining geographic boundary
    data with ONS statistics — the core use case for
    **kindtech**.

    We'll load Local Authority District (LAD) boundaries and
    join them with a NOMIS dataset to see statistics by area.

    Both sources are normalised automatically so they share a
    `geography_code` column — no manual column matching needed.

    > **Note:** This example uses **pandas**. kindtech also supports
    > polars — see the docs for BYODF (Bring Your Own DataFrame).
    """)
    return


@app.cell
def _():
    import pandas as pd

    from kindtech import geodata_to_properties, load_geodata, load_ons

    return geodata_to_properties, load_geodata, load_ons, pd


@app.cell
def _(mo):
    mo.md("""
    ## Step 1: Load geographic boundaries

    We'll fetch LAD boundaries (generalised clipped) for the
    whole UK.
    """)
    return


@app.cell
def _(mo):
    geo_button = mo.ui.run_button(label="Fetch LAD boundaries")
    geo_button
    return (geo_button,)


@app.cell
def _(geo_button, geodata_to_properties, load_geodata, mo, pd):
    mo.stop(
        not geo_button.value,
        mo.md("*Click to fetch LAD boundaries.*"),
    )

    geojson = load_geodata(
        geography_type="LAD",
        boundary_type="BGC",
    )
    geo_df = pd.DataFrame(geodata_to_properties(geojson, "LAD", 2024))
    mo.md(
        f"Loaded **{len(geo_df)} LAD boundaries** — "
        f"columns include `geography_code` and `geography_name`"
    )
    return geo_df, geojson


@app.cell
def _(geo_df, mo):
    mo.ui.table(geo_df.head(10), selection=None)
    return


@app.cell
def _(mo):
    mo.md("""
    ## Step 2: Load ONS statistics

    Search for a dataset and load it. We'll use JSA claimants
    (`NM_1_1`) by default, filtered to LAD-level geography.

    Column names are normalised automatically (`GEOGRAPHY_CODE`
    → `geography_code`), so they match the geo data.
    """)
    return


@app.cell
def _(mo):
    dataset_input = mo.ui.text(value="NM_1_1", label="Dataset ID")
    dataset_input
    return (dataset_input,)


@app.cell
def _(mo):
    ons_button = mo.ui.run_button(label="Load ONS data")
    ons_button
    return (ons_button,)


@app.cell
def _(dataset_input, load_ons, mo, ons_button):
    mo.stop(
        not ons_button.value,
        mo.md("*Click to load ONS data.*"),
    )

    ons_df = load_ons(
        dataset_input.value.strip(),
        geography_type="LAD",
        time="latest",
    )
    mo.md(f"Loaded **{len(ons_df)} rows** from `{dataset_input.value}`")
    return (ons_df,)


@app.cell
def _(mo, ons_df):
    mo.md(f"**Columns:** {', '.join(f'`{c}`' for c in ons_df.columns)}")
    return


@app.cell
def _(mo, ons_df):
    mo.ui.table(ons_df.head(10), selection=None)
    return


@app.cell
def _(mo):
    mo.md("""
    ## Step 3: Join geo + statistics

    Both DataFrames share a `geography_code` column thanks to
    kindtech's normalisation layer — just merge directly.
    """)
    return


@app.cell
def _(geo_df, mo, ons_df, pd):
    merged = pd.merge(
        geo_df,
        ons_df,
        on="geography_code",
        how="inner",
    )
    mo.md(f"Joined result: **{len(merged)} rows** × **{len(merged.columns)} columns**")
    return (merged,)


@app.cell
def _(merged, mo):
    mo.ui.table(merged.head(20), selection=None)
    return


@app.cell
def _(mo):
    mo.md("""
    ## Step 4: Choropleth map

    Visualise the joined data on a map, coloured by `obs_value`.
    """)
    return


@app.cell
def _(geojson, merged):
    import altair as alt

    # Map geography_code → obs_value from the merged DataFrame
    code_to_value = dict(
        zip(merged["geography_code"], merged["obs_value"], strict=False)
    )

    # Build a geography_code → feature index so we don't rely
    # on positional alignment between geojson and geo_df
    code_to_feature: dict = {}
    for f in geojson["features"]:
        props = f.get("properties", {})
        # Find the code field (ends with "CD", e.g. LAD24CD)
        for key, val in props.items():
            if key.endswith("CD") and val in code_to_value:
                code_to_feature[val] = f
                break

    enriched = {
        "type": "FeatureCollection",
        "features": [
            {
                **f,
                "properties": {
                    **f["properties"],
                    "obs_value": code_to_value[code],
                },
            }
            for code, f in code_to_feature.items()
        ],
    }

    chart = (
        alt.Chart(alt.Data(values=enriched["features"]))
        .mark_geoshape(stroke="white", strokeWidth=0.3)
        .encode(
            color=alt.Color("properties.obs_value:Q", title="Value"),
            tooltip=[
                "properties.geography_code:N",
                "properties.obs_value:Q",
            ],
        )
        .project(type="mercator")
        .properties(width=500, height=700)
    )
    chart
    return


if __name__ == "__main__":
    app.run()
