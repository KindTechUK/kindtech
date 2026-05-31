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
    # Sobus: BAME Mental-Health Referrals in Hammersmith & Fulham

    A reproduction of the [Sobus case
    study](../docs/case-studies/sobus-bame-analysis.md) using **kindtech**.

    Sobus wanted to map the **BAME mental-health landscape** in Hammersmith &
    Fulham — were Black, Asian and minority-ethnic residents
    **over-represented** in mental-health referrals relative to their share of
    the population, and *where* in the borough was need concentrated?

    This notebook combines:

    - **Outcode → LSOA** mapping (`kindtech.postcodes`, via postcodes.io) — how
      a referral's postcode prefix becomes a geography to aggregate on
    - **Census 2021** ethnic group by LSOA (NOMIS `NM_2041_1`, table TS021) —
      the population denominator and the BAME share of each small area
    - **LSOA boundaries** for Hammersmith & Fulham from the ONS Geoportal
    - **Synthetic referral records** — real NHS Trust referrals are
      confidential, so we generate a realistic stand-in whose BAME rate runs
      higher than the population's, reproducing the study's headline finding

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
        load_ons,
        outcode_to_geography,
    )

    return (
        alt,
        geodata_to_properties,
        load_geodata,
        load_ons,
        np,
        outcode_to_geography,
        pd,
    )


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
    ## Step 1: Outcode → LSOA

    Each referral carries a postcode. Where only the **outcode** (the prefix
    before the space, e.g. `W6`) survives anonymisation,
    `outcode_to_geography` resolves it to the LSOA containing the outcode's
    centroid. Here are Hammersmith & Fulham's outcodes:

    > ⚠️ An outcode spans many LSOAs, so this is a **rough** centroid-based
    > stand-in. With full postcodes, prefer `postcodes_to_geography` for an
    > exact per-area mapping. We use it here only to show the mechanism — the
    > analysis below works at true LSOA resolution from the census.
    """)
    return


@app.cell
def _(outcode_to_geography, run):
    run.value
    hf_outcodes = ["W6", "W12", "W14", "SW6", "SW10", "NW10"]
    outcode_demo = outcode_to_geography(hf_outcodes, geography_type="LSOA")
    return (outcode_demo,)


@app.cell
def _(mo, outcode_demo):
    mo.ui.table(outcode_demo, selection=None)
    return


@app.cell
def _(mo):
    mo.md("""
    ## Step 2: Ethnic composition by LSOA (Census 2021)

    Table TS021 ("Ethnic group") at LSOA, restricted to Hammersmith & Fulham
    (NOMIS area `1778385172`, expanded to its child LSOAs with `TYPE151`). We
    keep the high-level groups and compute, for each LSOA, the **BAME share** —
    everyone who is not in the *White* group — and the resident population that
    serves as the per-capita denominator.
    """)
    return


@app.cell
def _(load_ons, pd, run):
    run.value

    # High-level ethnic-group codes in TS021's c2021_eth_20 dimension.
    total_code, white_code = 0, 1004

    eth_long = load_ons(
        "NM_2041_1",
        geography="1778385172TYPE151",  # LSOAs within Hammersmith & Fulham
        time="latest",
        measures=20100,
        c2021_eth_20=[total_code, white_code],
        select=[
            "geography_code",
            "geography_name",
            "c2021_eth_20",
            "obs_value",
        ],
    )
    eth = eth_long.pivot_table(
        index=["geography_code", "geography_name"],
        columns="c2021_eth_20",
        values="obs_value",
        aggfunc="sum",
    ).reset_index()
    eth = eth.rename(columns={total_code: "population", white_code: "white"})
    eth["bame"] = eth["population"] - eth["white"]
    eth["bame_share"] = eth["bame"] / eth["population"]
    eth = eth[["geography_code", "geography_name", "population", "bame", "bame_share"]]
    return (eth,)


@app.cell
def _(eth, mo):
    borough_share = eth["bame"].sum() / eth["population"].sum()
    mo.md(
        f"Loaded **{len(eth)} LSOAs** in Hammersmith & Fulham, total population "
        f"**{int(eth['population'].sum()):,}**. Borough-wide BAME share: "
        f"**{borough_share:.0%}**, ranging from **{eth['bame_share'].min():.0%}** "
        f"to **{eth['bame_share'].max():.0%}** across LSOAs."
    )
    return


@app.cell
def _(mo):
    mo.md("""
    ## Step 3: LSOA boundaries

    Fetch just Hammersmith & Fulham's LSOA boundaries (super-generalised,
    2021). The ONS service is queried by code; we batch the codes to keep each
    request URL a sensible length.
    """)
    return


@app.cell
def _(eth, geodata_to_properties, load_geodata, pd):
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

    geojson = _fetch_lsoa_boundaries(eth["geography_code"].tolist())
    geo = pd.DataFrame(geodata_to_properties(geojson, "LSOA", 2021))[["geography_code"]]
    return geo, geojson


@app.cell
def _(geo, mo):
    mo.md(f"Loaded **{len(geo)} LSOA boundaries** for Hammersmith & Fulham.")
    return


@app.cell
def _(mo):
    mo.md("""
    ## Step 4: Synthetic referral records

    Real NHS Trust referrals are confidential. We generate a realistic
    stand-in: referrals are drawn per LSOA at a rate that **rises with the BAME
    share** of the area, so the referred population skews more BAME than the
    resident population — deliberately setting up the over-representation the
    study tested for. `rng(7)` makes it reproducible.

    `referrals_per_1000` normalises by population — the true measure of service
    demand. `bame_referral_share` estimates the BAME fraction *of referrals*,
    which we compare against the population share to get an
    over-representation ratio.
    """)
    return


@app.cell
def _(eth, geo, np):
    base = eth.merge(geo, on="geography_code", how="inner")

    rng = np.random.default_rng(7)
    # Referral rate rises with BAME share: a more-BAME LSOA refers more often.
    rate = 0.010 + 0.030 * base["bame_share"]
    noise = rng.lognormal(mean=0.0, sigma=0.25, size=len(base))
    expected = base["population"] * rate * noise
    base["referrals"] = rng.poisson(np.maximum(expected, 0)).astype(int)
    base["referrals_per_1000"] = 1000 * base["referrals"] / base["population"]

    # Within an LSOA, a BAME resident is modelled as ~2.5x more likely to be
    # referred than a White resident — so the BAME share of referrals exceeds
    # the BAME share of the population.
    bame_relative_risk = 2.5
    bame_weight = bame_relative_risk * base["bame_share"]
    base["bame_referral_share"] = bame_weight / (bame_weight + (1 - base["bame_share"]))
    base["overrep_ratio"] = base["bame_referral_share"] / base["bame_share"]
    return (base,)


@app.cell
def _(base, mo):
    pop_share = base["bame"].sum() / base["population"].sum()
    ref_bame = (base["bame_referral_share"] * base["referrals"]).sum()
    ref_share = ref_bame / base["referrals"].sum()
    mo.md(
        f"Generated **{int(base['referrals'].sum()):,} synthetic referrals** "
        f"across {len(base)} LSOAs. BAME residents are **{pop_share:.0%}** of "
        f"the population but an estimated **{ref_share:.0%}** of referrals — an "
        f"over-representation factor of **{ref_share / pop_share:.1f}×**."
    )
    return


@app.cell
def _(mo):
    mo.md("""
    ## Step 5: Maps — where is the need?

    Left: the BAME share of each LSOA (the community the service must reach).
    Right: synthetic referrals per 1,000 residents (observed demand). If
    referrals track ethnic composition, the two maps share their dark areas.
    """)
    return


@app.cell
def _(alt, base, geojson):
    def _choropleth(value_col, title, scheme, fmt):
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
                    scale=alt.Scale(scheme=scheme),
                    legend=alt.Legend(format=fmt),
                ),
                tooltip=[
                    "properties.geography_code:N",
                    alt.Tooltip(f"properties.{value_col}:Q", format=fmt),
                ],
            )
            .project(type="mercator")
            .properties(width=360, height=360, title=title)
        )

    bame_map = _choropleth("bame_share", "BAME share of population", "purples", ".0%")
    referral_map = _choropleth(
        "referrals_per_1000", "Referrals per 1,000", "reds", ".1f"
    )
    (bame_map | referral_map).resolve_scale(color="independent")
    return


@app.cell
def _(mo):
    mo.md("""
    ## Step 6: Are BAME residents over-represented?

    Plot each LSOA's BAME population share against its referral rate. A rising
    trend means referrals come disproportionately from more-BAME areas — the
    disparity the study set out to quantify.
    """)
    return


@app.cell
def _(alt, base):
    correlation = base["bame_share"].corr(base["referrals_per_1000"])
    scatter = (
        alt.Chart(base)
        .mark_circle(size=60, opacity=0.6)
        .encode(
            x=alt.X(
                "bame_share:Q",
                title="BAME share of population",
                axis=alt.Axis(format=".0%"),
            ),
            y=alt.Y("referrals_per_1000:Q", title="Referrals per 1,000 residents"),
            tooltip=[
                "geography_name:N",
                alt.Tooltip("bame_share:Q", format=".0%"),
                alt.Tooltip("referrals_per_1000:Q", format=".1f"),
            ],
        )
        .properties(
            width=520,
            height=360,
            title=f"BAME share vs referral rate (r = {correlation:.2f})",
        )
    )
    scatter + scatter.transform_regression(
        "bame_share", "referrals_per_1000"
    ).mark_line(color="purple")
    return (correlation,)


@app.cell
def _(base, correlation, mo):
    pop_share = base["bame"].sum() / base["population"].sum()
    ref_bame = (base["bame_referral_share"] * base["referrals"]).sum()
    ref_share = ref_bame / base["referrals"].sum()
    mo.md(f"""
    ## What this shows

    - **Need is geographic**: the BAME-share map and the referral-rate map
      share their dark areas — referrals come disproportionately from the
      most-BAME LSOAs (r = **{correlation:.2f}**).
    - **Over-representation**: BAME residents are **{pop_share:.0%}** of the
      borough but an estimated **{ref_share:.0%}** of referrals
      (**{ref_share / pop_share:.1f}×**) — the direction the original study
      found, evidence for targeting culturally-appropriate provision at the
      most-affected areas.

    To run on real data, feed each referral's postcode through
    `postcodes_to_geography(..., "LSOA")` (Step 1), tag it with the patient's
    ethnicity, and aggregate per `geography_code`. The census join, per-capita
    maths and maps are unchanged.
    """)
    return


if __name__ == "__main__":
    app.run()
