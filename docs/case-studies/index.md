# Case Studies

End-to-end reproductions of real [DataKind UK](https://www.datakind.org.uk/)
charity projects, rebuilt with KindTech. Each one chains several connectors on a
shared `geography_code`, and — because real client data is private — pairs the
public data with a transparent synthetic stand-in so the full analysis runs.

Every study has a runnable [marimo](https://marimo.io/) notebook: open it in the
molab cloud runtime to run it **in your browser** (it fetches live ONS data), or
locally with `uv run marimo edit examples/<notebook>.py`.

| Case study | What it shows | Run |
|---|---|---|
| [Smart Works](smart-works-woman-unemployment.md) | Women's unemployment vs service reach (Census 2021 + LAD boundaries) | [![Open in molab](https://marimo.io/molab-shield.svg)](https://molab.marimo.io/github/KindTechUK/kindtech/blob/main/examples/smart_works_unemployment.py) |
| [Citizens Advice Lewisham](cal-vulnerable-client.md) | Deprivation vs service usage (postcodes + IMD + LSOA boundaries) | [![Open in molab](https://marimo.io/molab-shield.svg)](https://molab.marimo.io/github/KindTechUK/kindtech/blob/main/examples/cal_vulnerable_client.py) |
| [Sobus](sobus-bame-analysis.md) | BAME mental-health referrals in Hammersmith & Fulham (outcodes + Census ethnicity) | [![Open in molab](https://marimo.io/molab-shield.svg)](https://molab.marimo.io/github/KindTechUK/kindtech/blob/main/examples/sobus_bame_referrals.py) |
| [Starlight](starlight-children-mapping.md) | Hospital play provision vs need across ICBs | [![Open in molab](https://marimo.io/molab-shield.svg)](https://molab.marimo.io/github/KindTechUK/kindtech/blob/main/examples/starlight_play_provision.py) |
| [Material Focus](material-focus-recycling.md) | Travel time to the nearest recycling point (LAD boundaries + population) | [![Open in molab](https://marimo.io/molab-shield.svg)](https://molab.marimo.io/github/KindTechUK/kindtech/blob/main/examples/material_focus_recycling.py) |

## How each study is structured

- **Problem statement** — the question the charity set out to answer.
- **Dataset involved** — the open (and, where relevant, synthetic) data used.
- **Desired output** — what the original analysis produced.
- **Reproduction with KindTech** — the connector pipeline, with figures.
- **Lessons learned** — takeaways and where the approach generalises.

## Have a case study to share?

Using KindTech in your own work? We'd love to feature it — open an issue or PR
on the [GitHub repository](https://github.com/KindTechUK/kindtech).
