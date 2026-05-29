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

__generated_with = "0.23.8"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo

    return (mo,)


@app.cell
def _(mo):
    mo.md("""
    # Material Focus: Travel Time to the Nearest Recycling Point

    A reproduction of the [Material Focus case
    study](../docs/case-studies/material-focus-recycling.md) using **kindtech**.

    Material Focus wanted to show **how far people have to travel to recycle
    small electricals** across England, and whether **proximity to a collection
    point influences recycling rates** — evidence for where new collection
    points would help most.

    This notebook combines:

    - **LAD boundaries with centroids** from the ONS Geoportal (`kindtech.geo`)
    - **LAD population** (`kindtech.ons`, mid-year estimates) — so the headline
      is *people-weighted*, not area-weighted
    - **Synthetic recycling-point locations** — the real collection-point list
      isn't public, so we scatter points where people live (supermarket
      take-back follows population) and measure the distance to the nearest one

    > **⚠️ Straight-line, not road routing.** The original used road
    > **travel time**. We approximate with straight-line (haversine) distance
    > converted to minutes at an average effective road speed. This reproduces
    > the *pattern* well; a true drive-time map needs a routing engine (see the
    > closing note). Everything joins on `geography_code`.
    """)
    return


@app.cell
def _():
    import altair as alt
    import numpy as np
    import pandas as pd

    from kindtech import geodata_to_properties, load_geodata, load_ons

    return alt, geodata_to_properties, load_geodata, load_ons, np, pd


@app.cell
def _(mo):
    run = mo.ui.run_button(label="Run analysis (fetches live ONS data)")
    run
    return (run,)


@app.cell
def _(mo, run):
    mo.stop(
        not run.value,
        mo.md("*Click the button above to fetch boundaries + population.*"),
    )
    return


@app.cell
def _(mo):
    mo.md("""
    ## Step 1: LAD boundaries and population

    Ultra-generalised boundaries (`BUC`) keep the payload small and carry
    `LAT`/`LONG` centroids. We pull total population per LAD (mid-year estimate,
    `gender=0`, all ages) so the travel-time headline can be weighted by where
    people actually live. England only (`E…` codes).
    """)
    return


@app.cell
def _(geodata_to_properties, load_geodata, load_ons, pd, run):
    run.value

    geojson = load_geodata(geography_type="LAD", year="2025", boundary_type="BUC")
    geo = pd.DataFrame(geodata_to_properties(geojson, "LAD", 2025))
    geo = geo[geo["geography_code"].str.startswith("E")][
        ["geography_code", "geography_name", "LAT", "LONG"]
    ].dropna()

    pop = load_ons(
        "population",
        geography_type="LAD",
        time="latest",
        measures=20100,
        gender=0,  # all persons
        c_age=200,  # all ages
        select=["geography_code", "obs_value"],
    ).rename(columns={"obs_value": "population"})

    lads = geo.merge(pop, on="geography_code", how="inner").reset_index(drop=True)
    return geojson, lads


@app.cell
def _(lads, mo):
    mo.md(
        f"Loaded **{len(lads)} English Local Authorities**, total population "
        f"**{int(lads['population'].sum()):,}**."
    )
    return


@app.cell
def _(mo):
    mo.md("""
    ## Step 2: Synthetic recycling points

    The real collection-point list isn't public, so we place **300 points**
    where people live — sampling LAD centroids in proportion to population (with
    a little jitter), because supermarket take-back and household waste sites
    cluster around population. `rng(5)` makes it reproducible.
    """)
    return


@app.cell
def _(lads, np):
    rng = np.random.default_rng(5)
    n_points = 300

    lat = lads["LAT"].to_numpy()
    lon = lads["LONG"].to_numpy()
    weights = lads["population"].to_numpy() / lads["population"].sum()

    # Points sit near population centres, with ~4-6km of jitter.
    idx = rng.choice(len(lads), size=n_points, replace=True, p=weights)
    point_lat = lat[idx] + rng.normal(0.0, 0.04, n_points)
    point_lon = lon[idx] + rng.normal(0.0, 0.06, n_points)
    return point_lat, point_lon, rng


@app.cell
def _(mo):
    mo.md("""
    ## Step 3: Travel time to the nearest point

    For each LAD centroid we take the straight-line distance to the nearest
    recycling point and convert it to minutes at an effective road speed of
    **40 km/h**, capped at **20 minutes** (the study's reported maximum). We
    then compute the **share of *people*** — population-weighted — within a
    12-minute trip.
    """)
    return


@app.cell
def _(lads, np, point_lat, point_lon):
    def _haversine_km(lat1, lon1, lat2, lon2):
        r = 6371.0
        p1, p2 = np.radians(lat1), np.radians(lat2)
        dphi = np.radians(lat2 - lat1)
        dlmb = np.radians(lon2 - lon1)
        a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dlmb / 2) ** 2
        return 2 * r * np.arcsin(np.sqrt(a))

    speed_kmh = 40.0
    max_minutes = 20.0

    lat = lads["LAT"].to_numpy()
    lon = lads["LONG"].to_numpy()
    nearest_km = np.full(len(lads), np.inf)
    for plat, plon in zip(point_lat, point_lon, strict=False):
        nearest_km = np.minimum(nearest_km, _haversine_km(lat, lon, plat, plon))

    travel = lads.copy()
    travel["nearest_km"] = nearest_km
    travel["travel_minutes"] = np.minimum(nearest_km / speed_kmh * 60, max_minutes)
    return (travel,)


@app.cell
def _(mo, travel):
    pop = travel["population"]
    within_12 = pop[travel["travel_minutes"] <= 12].sum() / pop.sum()
    mo.md(
        f"**{within_12:.0%} of people** live in a LAD within a **12-minute** "
        f"trip of a recycling point (median LAD trip "
        f"**{travel['travel_minutes'].median():.0f} min**, max "
        f"**{travel['travel_minutes'].max():.0f} min**) — reproducing the "
        f"study's finding that most people have nearby access."
    )
    return


@app.cell
def _(mo):
    mo.md("""
    ## Step 4: The travel-time map

    Average travel time (minutes) to the nearest recycling point per LAD — the
    study's headline visualisation. Dark = a longer trip = a candidate for a new
    collection point.
    """)
    return


@app.cell
def _(alt, geojson, travel):
    code_to_value = dict(
        zip(travel["geography_code"], travel["travel_minutes"], strict=False)
    )
    code_to_name = dict(
        zip(travel["geography_code"], travel["geography_name"], strict=False)
    )
    features = []
    for f in geojson["features"]:
        props = f.get("properties", {})
        code = next(
            (v for k, v in props.items() if k.endswith("CD") and v in code_to_value),
            None,
        )
        if code is None:
            continue
        features.append(
            {
                **f,
                "properties": {
                    "geography_name": code_to_name[code],
                    "travel_minutes": code_to_value[code],
                },
            }
        )

    travel_map = (
        alt.Chart(alt.Data(values=features))
        .mark_geoshape(stroke="white", strokeWidth=0.2)
        .encode(
            color=alt.Color(
                "properties.travel_minutes:Q",
                title="Minutes to nearest point",
                scale=alt.Scale(scheme="yelloworangered"),
            ),
            tooltip=[
                "properties.geography_name:N",
                alt.Tooltip("properties.travel_minutes:Q", format=".1f"),
            ],
        )
        .project(type="mercator")
        .properties(
            width=460, height=560, title="Travel time to nearest recycling point"
        )
    )
    travel_map
    return


@app.cell
def _(mo):
    mo.md("""
    ## Step 5: Does proximity influence recycling?

    The study's second question: do people closer to a collection point recycle
    more? Real participation rates aren't public, so we synthesise a rate that
    **falls as travel time rises** (plus noise), then plot it against travel
    time. A downward trend is the relationship Material Focus argued for —
    shorter trips, more recycling.
    """)
    return


@app.cell
def _(np, rng, travel):
    behav = travel.copy()
    # Recycling rate declines with travel time; deterministic given rng(5).
    # Noise is sizeable: proximity is one driver among many (car ownership,
    # kerbside collection, demographics), so the trend is real but loose.
    noise = rng.normal(0.0, 0.09, len(behav))
    behav["recycling_rate"] = np.clip(
        0.52 - 0.012 * behav["travel_minutes"] + noise, 0.05, 0.95
    )
    return (behav,)


@app.cell
def _(alt, behav):
    correlation = behav["travel_minutes"].corr(behav["recycling_rate"])
    scatter = (
        alt.Chart(behav)
        .mark_circle(size=55, opacity=0.55)
        .encode(
            x=alt.X("travel_minutes:Q", title="Travel time to nearest point (min)"),
            y=alt.Y(
                "recycling_rate:Q",
                title="Electrical recycling rate",
                axis=alt.Axis(format=".0%"),
            ),
            tooltip=[
                "geography_name:N",
                alt.Tooltip("travel_minutes:Q", format=".1f"),
                alt.Tooltip("recycling_rate:Q", format=".0%"),
            ],
        )
        .properties(
            width=560,
            height=360,
            title=f"Proximity vs recycling rate (r = {correlation:.2f})",
        )
    )
    scatter + scatter.transform_regression(
        "travel_minutes", "recycling_rate"
    ).mark_line(color="seagreen")
    return (correlation,)


@app.cell
def _(correlation, mo, travel):
    pop = travel["population"]
    within_12 = pop[travel["travel_minutes"] <= 12].sum() / pop.sum()
    mo.md(f"""
    ## What this shows

    - **Good baseline coverage**: ~**{within_12:.0%}** of people are within a
      12-minute trip of a recycling point — the study's headline that
      infrastructure is broadly accessible, with a long tail of harder-to-reach
      areas.
    - **Proximity tracks recycling** (r = **{correlation:.2f}**): the synthetic
      participation rate falls as travel time rises, the direction Material
      Focus argued — closer points, more recycling.
    - **Targeting**: the darkest LADs on the map are where a new collection
      point would cut the longest trips, the evidence the campaign needed.

    To run on real data, swap the synthetic points for Material Focus's actual
    collection-point coordinates and the synthetic rate for measured
    participation; the population join and maps are unchanged.

    !!! note "Straight-line is an approximation"
        Distances here are as-the-crow-flies. A faithful **road travel-time**
        map (the study's literal output) needs a routing engine — e.g. OSRM or
        OpenRouteService — to turn point pairs into drive-time. KindTech doesn't
        wrap one yet; if more case studies need real travel time it would be
        worth adding a small routing connector.
    """)
    return


if __name__ == "__main__":
    app.run()
