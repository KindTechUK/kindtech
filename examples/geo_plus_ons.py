# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "marimo",
#     "kindtech",
#     "pandas>=2.0.0",
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

    > **Note:** This example uses **pandas**. kindtech also supports
    > polars — see the docs for BYODF (Bring Your Own DataFrame).
    """)
    return


@app.cell
def _():
    import pandas as pd

    from kindtech.geo import load_geodata
    from kindtech.ons import load_ons

    return load_geodata, load_ons, pd


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
def _(geo_button, load_geodata, mo):
    mo.stop(
        not geo_button.value,
        mo.md("*Click to fetch LAD boundaries.*"),
    )

    geojson = load_geodata(
        geography_type="LAD",
        boundary_type="BGC",
    )
    n_lads = len(geojson.get("features", []))
    mo.md(f"Loaded **{n_lads} LAD boundaries**")
    return geojson, n_lads


@app.cell
def _(geojson, mo, n_lads, pd):
    mo.stop(n_lads == 0)

    geo_df = pd.DataFrame([f["properties"] for f in geojson["features"]])
    mo.md(f"**Columns:** {', '.join(f'`{c}`' for c in geo_df.columns)}")
    return (geo_df,)


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
        geography="TYPE480",
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

    We need to match the geography code column from the ONS
    data with the LAD code column from the boundary data.

    Configure the join keys below — these depend on the
    dataset year and columns available.
    """)
    return


@app.cell
def _(geo_df, mo, ons_df):
    geo_col = mo.ui.dropdown(
        options=list(geo_df.columns),
        label="Geo join column",
    )
    ons_col = mo.ui.dropdown(
        options=list(ons_df.columns),
        label="ONS join column",
    )
    mo.hstack([geo_col, ons_col], justify="start", gap=1)
    return geo_col, ons_col


@app.cell
def _(mo):
    join_button = mo.ui.run_button(label="Join datasets")
    join_button
    return (join_button,)


@app.cell
def _(geo_col, geo_df, join_button, mo, ons_col, ons_df, pd):
    mo.stop(
        not join_button.value or not geo_col.value or not ons_col.value,
        mo.md("*Select join columns and click 'Join datasets'.*"),
    )

    merged = pd.merge(
        geo_df,
        ons_df,
        left_on=geo_col.value,
        right_on=ons_col.value,
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
    ---

    *This is a preview of what kindtech enables. Future
    versions will include opinionated transforms (see
    [issue #14](https://github.com/KindTechUK/kindtech/issues/14))
    to make common joins like this a one-liner.*
    """)
    return


if __name__ == "__main__":
    app.run()
