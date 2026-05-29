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
    # Starlight: Hospital Play Provision vs Need

    A reproduction of the [Starlight case
    study](../docs/case-studies/starlight-children-mapping.md) using
    **kindtech**.

    Starlight Children's Foundation supplies play resources to hospitals. They
    wanted to know whether their provision is **directed to where need is
    greatest** — or spread evenly regardless of how many children each area
    admits — so they could be more strategic about allocation.

    This notebook combines:

    - **ICB boundaries** from the ONS Geoportal (`kindtech.geo`) — England's 42
      Integrated Care Boards, the NHS commissioning geography that replaced CCGs
    - **Synthetic admissions & provision** — the original relied on freedom-of-
      information returns from 140 trusts; we generate a realistic stand-in
      where **provision is spread evenly** while **need varies**, reproducing
      the study's headline mismatch

    Everything joins on `geography_code`, so admissions, provision and
    boundaries line up with no crosswalk.
    """)
    return


@app.cell
def _():
    import altair as alt
    import numpy as np
    import pandas as pd

    from kindtech import geodata_to_properties, load_geodata

    return alt, geodata_to_properties, load_geodata, np, pd


@app.cell
def _(mo):
    run = mo.ui.run_button(label="Run analysis (fetches live ONS boundaries)")
    run
    return (run,)


@app.cell
def _(mo, run):
    mo.stop(
        not run.value,
        mo.md("*Click the button above to fetch ICB boundaries.*"),
    )
    return


@app.cell
def _(mo):
    mo.md("""
    ## Step 1: ICB boundaries

    Load England's Integrated Care Board boundaries (super-generalised, 2023).
    ICBs are the NHS commissioning bodies that replaced Clinical Commissioning
    Groups in July 2022 — the natural unit for mapping hospital play provision.
    """)
    return


@app.cell
def _(geodata_to_properties, load_geodata, pd, run):
    run.value

    geojson = load_geodata(
        geography_type="ICB", year="2023", coverage="EN", boundary_type="BSC"
    )
    icbs = pd.DataFrame(geodata_to_properties(geojson, "ICB", 2023))[
        ["geography_code", "geography_name"]
    ]
    icbs["short_name"] = (
        icbs["geography_name"]
        .str.replace("^NHS ", "", regex=True)
        .str.replace(" Integrated Care Board$", "", regex=True)
    )
    return geojson, icbs


@app.cell
def _(icbs, mo):
    mo.md(f"Loaded **{len(icbs)} Integrated Care Boards** across England.")
    return


@app.cell
def _(mo):
    mo.md("""
    ## Step 2: Synthetic admissions and provision

    The original study collected child-admission and play-provision figures by
    FOI; those returns aren't public, so we generate a defensible stand-in
    (`rng(3)`, deterministic):

    - **Child admissions** (the *need*) vary widely between ICBs — some areas
      admit far more children than others.
    - **Play provision** (boxes distributed — the *resource*) is spread
      **roughly evenly**, *independent of admissions*. This is the behaviour
      the study found and flagged as a missed opportunity.

    `boxes_per_1000_admissions` is the coverage measure: low values mark
    under-served, high-need areas.
    """)
    return


@app.cell
def _(icbs, np):
    rng = np.random.default_rng(3)
    base = icbs.copy()

    # Need: child admissions vary substantially between ICBs.
    base["child_admissions"] = (
        rng.lognormal(mean=10.4, sigma=0.45, size=len(base)).round().astype(int)
    )

    # Provision: boxes are handed out roughly evenly, NOT scaled to need —
    # the even-distribution pattern the study identified.
    base["boxes_distributed"] = (
        rng.normal(loc=1200, scale=180, size=len(base))
        .clip(min=300)
        .round()
        .astype(int)
    )

    base["boxes_per_1000_admissions"] = (
        1000 * base["boxes_distributed"] / base["child_admissions"]
    )
    return (base,)


@app.cell
def _(base, mo):
    total_adm = int(base["child_admissions"].sum())
    total_box = int(base["boxes_distributed"].sum())
    mo.md(
        f"Generated **{total_adm:,} child admissions** and "
        f"**{total_box:,} boxes** across {len(base)} ICBs. Coverage "
        f"(boxes per 1,000 admissions) ranges "
        f"**{base['boxes_per_1000_admissions'].min():.0f}**–"
        f"**{base['boxes_per_1000_admissions'].max():.0f}**."
    )
    return


@app.cell
def _(mo):
    mo.md("""
    ## Step 3: Maps — need vs provision

    Left: child admissions (the need). Right: boxes distributed (the resource).
    If provision tracked need, the two maps would share their dark areas. They
    **don't** — provision is roughly flat while need is concentrated, which is
    exactly the strategic gap Starlight wanted to surface.
    """)
    return


@app.cell
def _(alt, base, geojson):
    def _choropleth(value_col, title, scheme):
        code_to_value = dict(zip(base["geography_code"], base[value_col], strict=False))
        code_to_name = dict(
            zip(base["geography_code"], base["short_name"], strict=False)
        )
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
                        "geography_name": code_to_name[code],
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
                ),
                tooltip=[
                    "properties.geography_name:N",
                    f"properties.{value_col}:Q",
                ],
            )
            .project(type="mercator")
            .properties(width=330, height=460, title=title)
        )

    need_map = _choropleth("child_admissions", "Child admissions (need)", "reds")
    provision_map = _choropleth(
        "boxes_distributed", "Boxes distributed (provision)", "greens"
    )
    # Independent scales: the point is the *pattern* mismatch, not the units.
    (need_map | provision_map).resolve_scale(color="independent")
    return


@app.cell
def _(mo):
    mo.md("""
    ## Step 4: Does provision follow need?

    Plot each ICB's admissions against the boxes it received. A flat cloud (no
    upward trend) means provision is **decoupled from need** — high-admission
    ICBs get no more than low-admission ones. That is the case for "be more
    strategic".
    """)
    return


@app.cell
def _(alt, base):
    correlation = base["child_admissions"].corr(base["boxes_distributed"])
    scatter = (
        alt.Chart(base)
        .mark_circle(size=70, opacity=0.6)
        .encode(
            x=alt.X("child_admissions:Q", title="Child admissions (need)"),
            y=alt.Y("boxes_distributed:Q", title="Boxes distributed (provision)"),
            tooltip=[
                "short_name:N",
                "child_admissions:Q",
                "boxes_distributed:Q",
            ],
        )
        .properties(
            width=520,
            height=360,
            title=f"Provision vs need (r = {correlation:.2f})",
        )
    )
    scatter + scatter.transform_regression(
        "child_admissions", "boxes_distributed"
    ).mark_line(color="firebrick")
    return (correlation,)


@app.cell
def _(mo):
    mo.md("""
    ## Step 5: The under-served ICBs

    Rank ICBs by coverage (boxes per 1,000 admissions). The lowest-coverage,
    highest-need boards are where redirecting resources would help most.
    """)
    return


@app.cell
def _(base, mo):
    underserved = base.sort_values("boxes_per_1000_admissions").head(10)
    mo.ui.table(
        underserved[
            [
                "short_name",
                "child_admissions",
                "boxes_distributed",
                "boxes_per_1000_admissions",
            ]
        ].round(1),
        selection=None,
    )
    return


@app.cell
def _(base, correlation, mo):
    mo.md(f"""
    ## What this shows

    - **Provision is decoupled from need**: admissions vary widely between ICBs,
      but boxes are spread roughly evenly — the scatter is near-flat
      (r = **{correlation:.2f}**), reproducing the study's "even distribution"
      finding.
    - **Clear mismatch**: the need and provision maps don't share their dark
      areas, so several high-admission ICBs are under-served while lower-need
      ones receive comparable resource.
    - **A strategic opening**: ranking by coverage points directly at the boards
      where redirecting boxes would close the biggest gaps.

    To run on real data, replace the synthetic columns with Starlight's FOI
    returns keyed by ICB (or by trust, then mapped to ICB). The boundary join,
    coverage maths and maps are unchanged.
    """)
    return


if __name__ == "__main__":
    app.run()
