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
    # Smart Works: Women's Unemployment vs Service Reach

    A reproduction of the [Smart Works case
    study](../docs/case-studies/smart-works-woman-unemployment.md) using
    **kindtech**.

    Smart Works supports unemployed women back into work. With hundreds of
    thousands of unemployed women across England, they wanted to know **where
    their reach falls short of the need** — which Local Authorities have high
    female unemployment but few Smart Works clients — and whether any
    **age group is under-served**.

    This notebook combines:

    - **Census 2021** female unemployment by Local Authority and age band
      (NOMIS `NM_2124_1`, table RM024) — full coverage, no survey suppression
    - **LAD boundaries** from the ONS Geoportal
    - **Synthetic Smart Works client records** — the real client list is
      private, so we generate a realistic stand-in clustered around Smart
      Works' actual centre cities

    > **Why Census, not the Annual Population Survey?** APS unemployment
    > *counts* by sex are suppressed for small samples — only ~40 of 350 LADs
    > return data, and age bands are sparser still. Census 2021 covers every
    > LAD in England & Wales.
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
        mo.md("*Click the button above to fetch boundaries + Census data.*"),
    )
    return


@app.cell
def _(mo):
    mo.md("""
    ## Step 1: Female unemployment by Local Authority

    Census 2021 table RM024 ("Economic activity status by sex by age"). We
    select **female** (`c_sex=1`), **unemployed** (`c2021_eastat_7=2`), broken
    down across the four working-age bands.
    """)
    return


@app.cell
def _(load_ons, run):
    run.value  # depend on the trigger

    age_bands = {
        2: "16-24",
        3: "25-34",
        4: "35-49",
        5: "50-64",
    }

    unemp_long = load_ons(
        "NM_2124_1",
        geography_type="LAD",
        time="latest",
        c2021_eastat_7=2,
        c_sex=1,
        c2021_age_7=list(age_bands),
        select=[
            "geography_code",
            "geography_name",
            "c2021_age_7",
            "obs_value",
        ],
    )
    unemp_long["age_band"] = unemp_long["c2021_age_7"].map(age_bands)

    # Wide: one row per LAD, one column per age band + total
    unemp = unemp_long.pivot_table(
        index=["geography_code", "geography_name"],
        columns="age_band",
        values="obs_value",
        aggfunc="sum",
    ).reset_index()
    unemp["unemployed_total"] = unemp[list(age_bands.values())].sum(axis=1)
    return age_bands, unemp


@app.cell
def _(mo, unemp):
    total = int(unemp["unemployed_total"].sum())
    mo.md(
        f"Loaded **{len(unemp)} Local Authorities** (England & Wales), "
        f"**{total:,} unemployed women** in total."
    )
    return


@app.cell
def _(mo, unemp):
    mo.ui.table(
        unemp.sort_values("unemployed_total", ascending=False).head(10),
        selection=None,
    )
    return


@app.cell
def _(mo):
    mo.md("""
    ## Step 2: LAD boundaries (with centroids)

    Ultra-generalised clipped boundaries (`BUC`) keep the payload small. The
    ONS features include `LAT`/`LONG` centroids, which we'll use to model how
    far each LAD is from the nearest Smart Works centre.
    """)
    return


@app.cell
def _(geodata_to_properties, load_geodata, pd, run):
    run.value

    geojson = load_geodata(geography_type="LAD", year="2025", boundary_type="BUC")
    geo = pd.DataFrame(geodata_to_properties(geojson, "LAD", 2025))
    geo = geo[["geography_code", "geography_name", "LAT", "LONG"]]
    return geo, geojson


@app.cell
def _(mo):
    mo.md("""
    ## Step 3: Synthetic Smart Works clients

    The real client list is private, so we generate a defensible stand-in.
    Smart Works runs centres in a set of real cities. We assume client reach
    **decays with distance** from the nearest centre (people travel to attend),
    and scales with local female unemployment.

    The result deliberately reproduces the case study's structure: high-need
    LADs that sit far from any centre end up under-served.

    The generation is **deterministic** (`rng(42)`) so the maps are stable.
    """)
    return


@app.cell
def _(geo, np, unemp):
    # Real Smart Works centre cities (matched by LAD name).
    centre_names = [
        "Birmingham",
        "Bristol, City of",
        "Manchester",
        "Leeds",
        "Newcastle upon Tyne",
        "Reading",
        "Luton",
        "Slough",
        "Lambeth",
        "Islington",
    ]

    geo_centres = geo[geo["geography_name"].isin(centre_names)]
    missing = sorted(set(centre_names) - set(geo_centres["geography_name"]))
    centre_coords = geo_centres[["LAT", "LONG"]].to_numpy()

    def _haversine_km(lat1, lon1, lat2, lon2):
        r = 6371.0
        p1, p2 = np.radians(lat1), np.radians(lat2)
        dphi = np.radians(lat2 - lat1)
        dlmb = np.radians(lon2 - lon1)
        a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dlmb / 2) ** 2
        return 2 * r * np.arcsin(np.sqrt(a))

    base = unemp.merge(geo, on=["geography_code", "geography_name"], how="inner")

    # Distance from each LAD centroid to the nearest centre.
    dist = np.full(len(base), np.inf)
    for clat, clon in centre_coords:
        d = _haversine_km(
            base["LAT"].to_numpy(),
            base["LONG"].to_numpy(),
            clat,
            clon,
        )
        dist = np.minimum(dist, d)
    base["dist_to_centre_km"] = dist

    # Reach decays with distance (~40km scale); clients scale with need.
    rng = np.random.default_rng(42)
    decay_km = 40.0
    base_capture = 0.06  # ~6% of unemployed women reached at a centre's doorstep
    reach = np.exp(-base["dist_to_centre_km"] / decay_km)
    noise = rng.lognormal(mean=0.0, sigma=0.35, size=len(base))
    expected = base["unemployed_total"] * base_capture * reach * noise
    base["clients_total"] = rng.poisson(np.maximum(expected, 0)).astype(int)
    return base, missing, rng


@app.cell
def _(base, missing, mo):
    note = (
        f"⚠️ Centre names not found in boundary data: {missing}"
        if missing
        else "All centre cities matched to LADs."
    )
    mo.md(
        f"Generated **{int(base['clients_total'].sum()):,} synthetic clients** "
        f"across {int((base['clients_total'] > 0).sum())} LADs. {note}"
    )
    return


@app.cell
def _(mo):
    mo.md("""
    ## Step 4: The service gap

    `clients_per_100_unemployed` measures reach. A LAD with **high
    unemployment** but a **low** value is a service gap — exactly the
    "high need, low provision" areas Smart Works wanted to find.
    """)
    return


@app.cell
def _(base):
    gap = base.copy()
    gap["clients_per_100_unemployed"] = (
        100 * gap["clients_total"] / gap["unemployed_total"].clip(lower=1)
    )
    # Priority = high unemployment AND low reach.
    median_unemp = gap["unemployed_total"].median()
    underserved = (
        gap[gap["unemployed_total"] >= median_unemp]
        .sort_values("clients_per_100_unemployed")
        .head(10)
    )
    return gap, underserved


@app.cell
def _(mo):
    mo.md("""
    **Top 10 under-served Local Authorities** "
        "(above-median need, lowest reach):
    """)
    return


@app.cell
def _(mo, underserved):
    mo.ui.table(
        underserved[
            [
                "geography_name",
                "unemployed_total",
                "clients_total",
                "clients_per_100_unemployed",
                "dist_to_centre_km",
            ]
        ].round(2),
        selection=None,
    )
    return


@app.cell
def _(mo):
    mo.md("""
    ## Step 5: Maps — need vs reach

    Left: female unemployment (the need). Right: clients per 100 unemployed
    women (the reach). Dark areas on the left with pale areas on the right are
    the gaps.
    """)
    return


@app.cell
def _(alt, gap, geojson):
    def _choropleth(value_col, title, scheme):
        code_to_value = dict(zip(gap["geography_code"], gap[value_col], strict=False))
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
                        "geography_name": props.get("LAD25NM", ""),
                        value_col: code_to_value[code],
                    },
                }
            )
        return (
            alt.Chart(alt.Data(values=features))
            .mark_geoshape(stroke="white", strokeWidth=0.2)
            .encode(
                color=alt.Color(
                    f"properties.{value_col}:Q",
                    title=title,
                    scale=alt.Scale(scheme=scheme),
                ),
                tooltip=[
                    "properties.geography_name:N",
                    f"properties.{value_col}:Q",
                ],
            )
            .project(type="mercator")
            .properties(width=330, height=460, title=title)
        )

    need_map = _choropleth("unemployed_total", "Unemployed women", "reds")
    reach_map = _choropleth(
        "clients_per_100_unemployed", "Clients per 100 unemployed", "blues"
    )
    # Independent colour scales: the two metrics live on very different
    # ranges (counts in the thousands vs a 0-6 ratio), so a shared scale
    # would wash the reach map out.
    (need_map | reach_map).resolve_scale(color="independent")
    return


@app.cell
def _(mo):
    mo.md("""
    ## Step 6: Are young women under-served?

    Compare the **age distribution of unemployed women** (the need) against the
    **age distribution of Smart Works clients** (who we actually reach). If the
    client mix skews older, young women are under-represented relative to need.

    *(The synthetic client age profile intentionally under-weights the 16-24
    band, reproducing the case study's headline finding so the visualisation
    can be demonstrated.)*
    """)
    return


@app.cell
def _(age_bands, base, np, pd, rng):
    bands = list(age_bands.values())

    # Need: actual share of unemployment by age band.
    need_by_age = base[bands].sum()
    need_share = (need_by_age / need_by_age.sum()).rename("need")

    # Reach: distribute each LAD's clients across age bands using a client
    # profile that under-weights the youngest band, then add mild noise.
    client_profile = np.array([0.12, 0.34, 0.39, 0.15])  # 16-24, 25-34, 35-49, 50-64
    weighted = rng.dirichlet(client_profile * 60, size=len(base))
    client_by_age = (base["clients_total"].to_numpy()[:, None] * weighted).sum(axis=0)
    client_share = pd.Series(
        client_by_age / client_by_age.sum(), index=bands, name="client"
    )

    age_compare = (
        pd.concat([need_share, client_share], axis=1)
        .reset_index()
        .rename(columns={"index": "age_band"})
        .melt(id_vars="age_band", var_name="group", value_name="share")
    )
    return (age_compare,)


@app.cell
def _(age_compare, alt):
    alt.Chart(age_compare).mark_bar().encode(
        x=alt.X("age_band:N", title="Age band"),
        xOffset="group:N",
        y=alt.Y("share:Q", title="Share", axis=alt.Axis(format="%")),
        color=alt.Color(
            "group:N",
            title="",
            scale=alt.Scale(
                domain=["need", "client"],
                range=["#d6604d", "#4393c3"],
            ),
        ),
        tooltip=["age_band:N", "group:N", alt.Tooltip("share:Q", format=".1%")],
    ).properties(
        width=420,
        height=300,
        title="Unemployment need vs client reach, by age",
    )
    return


@app.cell
def _(mo):
    mo.md("""
    ## What this shows

    - **Geographic gaps**: several high-unemployment LADs sit far from any
      Smart Works centre and show very low reach — candidate locations for
      outreach or new centres.
    - **Demographic gap**: the 16-24 band is a larger share of *need* than of
      *clients reached*, flagging young women as under-served.

    With real client postcodes, the only change is swapping the synthetic
    `clients_total` for a `postcode → LAD` aggregation — see the planned
    postcode-lookup connector. Everything else (the Census join, the gap
    metric, the maps) stays identical.
    """)
    return


if __name__ == "__main__":
    app.run()
