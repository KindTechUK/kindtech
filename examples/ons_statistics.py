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
    # ONS Statistics Explorer

    Browse and load UK statistical datasets from the
    [NOMIS API](https://www.nomisweb.co.uk/) using
    **kindtech**.

    This notebook demonstrates:
    - Searching the 1,600+ NOMIS dataset catalog
    - Loading data with `load_ons()`
    - Filtering by geography, time, and measures
    """)
    return


@app.cell
def _():
    from kindtech.ons import list_tables, load_ons

    return list_tables, load_ons


@app.cell
def _(mo):
    search_input = mo.ui.text(
        placeholder="e.g. population, earnings, employment",
        label="Search datasets",
    )
    search_input
    return (search_input,)


@app.cell
def _(list_tables, mo, search_input):
    query = search_input.value.strip() if search_input.value else None
    catalog = list_tables(name=query) if query else list_tables()
    mo.md(f"**{len(catalog)} datasets found**")
    return (catalog,)


@app.cell
def _(catalog, mo):
    mo.ui.table(catalog, selection=None, page_size=15)
    return


@app.cell
def _(mo):
    mo.md("""
    ## Load a dataset

    Pick a dataset ID from the catalog above (e.g. `NM_1_1`
    for JSA claimants) and optionally filter by geography and
    time period.
    """)
    return


@app.cell
def _(mo):
    dataset_input = mo.ui.text(
        value="NM_1_1",
        label="Dataset ID",
    )
    geography_input = mo.ui.text(
        value="TYPE480",
        label="Geography (e.g. TYPE480 for LADs)",
    )
    time_input = mo.ui.text(
        value="latest",
        label="Time period",
    )
    mo.hstack(
        [dataset_input, geography_input, time_input],
        justify="start",
        gap=1,
    )
    return dataset_input, geography_input, time_input


@app.cell
def _(mo):
    load_button = mo.ui.run_button(label="Load dataset")
    load_button
    return (load_button,)


@app.cell
def _(dataset_input, geography_input, load_button, load_ons, mo, time_input):
    mo.stop(not load_button.value, mo.md("*Click 'Load dataset' to fetch data.*"))

    kwargs = {}
    if geography_input.value.strip():
        kwargs["geography"] = geography_input.value.strip()
    if time_input.value.strip():
        kwargs["time"] = time_input.value.strip()

    df = load_ons(dataset_input.value.strip(), **kwargs)
    mo.md(
        f"Loaded **{len(df)} rows** × **{len(df.columns)} columns** "
        f"from `{dataset_input.value.strip()}`"
    )
    return (df,)


@app.cell
def _(df, mo):
    mo.ui.table(df, page_size=20)
    return


@app.cell
def _(df, mo):
    mo.md(f"**Columns:** {', '.join(f'`{c}`' for c in df.columns)}")
    return


if __name__ == "__main__":
    app.run()
