# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "marimo",
#     "kindtech",
# ]
# ///

import marimo

__generated_with = "0.20.4"
app = marimo.App(width="medium")


@app.cell
def _():
    import inspect

    import marimo as mo

    return (inspect, mo)


@app.cell
def _(mo):
    mo.md("""
    # UK Geographic Boundaries Explorer

    Load and explore geographic boundary data from the
    [ONS Geoportal](https://geoportal.statistics.gov.uk/)
    using **kindtech**.

    This notebook demonstrates:
    - Loading boundaries with `load_geodata()`
    - Available geography types and boundary resolutions
    - Filtering by specific areas
    """)
    return


@app.cell
def _():
    from kindtech.geo import (
        get_available_boundary_types,
        get_available_geography_types,
        load_geodata,
    )

    return (
        get_available_boundary_types,
        get_available_geography_types,
        load_geodata,
    )


@app.cell
def _(get_available_geography_types, mo):
    geo_types = get_available_geography_types()
    mo.md("## Available geography types")
    return (geo_types,)


@app.cell
def _(geo_types, mo):
    mo.stop(not geo_types, mo.md("*No geography types available from the API.*"))

    geo_options = {f"{g['code']} — {g['description']}": g["code"] for g in geo_types}
    _geo_codes = list(geo_options.values())
    geo_dropdown = mo.ui.dropdown(
        options=geo_options,
        value="LAD" if "LAD" in _geo_codes else _geo_codes[0],
        label="Geography type",
    )
    geo_dropdown
    return (geo_dropdown,)


@app.cell
def _(get_available_boundary_types, mo):
    boundary_types = get_available_boundary_types()
    mo.stop(
        not boundary_types,
        mo.md("*No boundary types available from the API.*"),
    )

    boundary_options = {
        f"{b['code']} — {b['description']}": b["code"] for b in boundary_types
    }
    _boundary_codes = list(boundary_options.values())
    boundary_dropdown = mo.ui.dropdown(
        options=boundary_options,
        value="BGC" if "BGC" in _boundary_codes else _boundary_codes[0],
        label="Boundary resolution",
    )
    boundary_dropdown
    return (boundary_dropdown,)


@app.cell
def _(mo):
    fetch_button = mo.ui.run_button(label="Fetch boundaries")
    fetch_button
    return (fetch_button,)


@app.cell
def _(boundary_dropdown, fetch_button, geo_dropdown, load_geodata, mo):
    mo.stop(
        not fetch_button.value,
        mo.md("*Select a geography type and click 'Fetch boundaries'.*"),
    )

    geojson = load_geodata(
        geography_type=geo_dropdown.value,
        boundary_type=boundary_dropdown.value,
    )
    n_features = len(geojson.get("features", []))
    mo.md(
        f"Loaded **{n_features} features** "
        f"(`{geo_dropdown.value}`, `{boundary_dropdown.value}`)"
    )
    return geojson, n_features


@app.cell
def _(geojson, mo, n_features):
    mo.stop(n_features == 0, mo.md("*No features loaded.*"))

    # Show properties from the first feature as a preview
    sample = geojson["features"][0]["properties"]
    fields = list(sample.keys())
    mo.md(f"**Fields per feature:** {', '.join(f'`{f}`' for f in fields)}")
    return


@app.cell
def _(geojson, mo, n_features):
    mo.stop(n_features == 0)

    # Build a table of feature properties (no geometry)
    rows = [f["properties"] for f in geojson["features"]]
    mo.ui.table(rows, page_size=15)
    return


@app.cell
def _(mo):
    mo.md("""
    ## Filter by area name

    You can pass field filters as keyword arguments to
    `load_geodata()`. The field names depend on the geography
    type and year — check the fields table above.
    """)
    return


@app.cell
def _(mo):
    filter_field = mo.ui.text(
        value="LAD24NM",
        label="Filter field",
    )
    filter_value = mo.ui.text(
        value="Manchester",
        label="Filter value",
    )
    mo.hstack([filter_field, filter_value], justify="start", gap=1)
    return filter_field, filter_value


@app.cell
def _(
    boundary_dropdown,
    filter_field,
    filter_value,
    geo_dropdown,
    inspect,
    load_geodata,
    mo,
):
    _reserved = set(inspect.signature(load_geodata).parameters)
    _field = filter_field.value.strip()
    _value = filter_value.value.strip()

    mo.stop(
        not _field or not _value,
        mo.md("*Enter a field name and value to filter.*"),
    )
    mo.stop(
        _field in _reserved,
        mo.md(
            f"*`{_field}` is a reserved `load_geodata()` parameter "
            f"— choose a feature property name instead.*"
        ),
    )

    filtered = load_geodata(
        geography_type=geo_dropdown.value,
        boundary_type=boundary_dropdown.value,
        **{_field: _value},
    )
    n_filtered = len(filtered.get("features", []))
    mo.md(
        f"Filtered to **{n_filtered} feature(s)** where "
        f"`{filter_field.value}` = `{filter_value.value}`"
    )
    return filtered, n_filtered


@app.cell
def _(filtered, mo, n_filtered):
    mo.stop(n_filtered == 0, mo.md("*No matching features.*"))

    filtered_rows = [f["properties"] for f in filtered["features"]]
    mo.ui.table(filtered_rows, page_size=15)
    return


if __name__ == "__main__":
    app.run()
