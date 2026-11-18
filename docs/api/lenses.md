# Lenses

A lens answers one question a charity asks of its own data. You give it a
table, say which column is which, and it joins your data to UK open data and
returns figures you can check and reuse.

Every lens returns the same things:

- **figures**: the headline numbers
- **tables**: totals behind the figures
- **a map description**: which areas to draw and what to colour them by
- **the working**: each step taken, with how many rows went in and came out
- **choices**: what the lens decided for you, and the option that changes it
- **checks**: what a person must confirm before using the figures
- **caveats**: what the figures cannot say
- **sources**: publisher, edition, licence and link for every dataset used
- **a privacy summary**: what was hidden, and what left your machine

A result holds totals only. Nothing in it describes one person, and no value
from your data is repeated back, not even in a warning or an error message.

## Quick start

```python
import pandas as pd
from kindtech.lenses import run_lens

clients = pd.read_csv("clients.csv")

result = run_lens(
    "reach-deprivation",
    clients,
    columns={"postcode": "Client postcode"},
)

result.figure("share_most_deprived_20").value   # 41.3 (per cent)
result.table("by_decile").to_frame()            # pandas or polars DataFrame
[check.question for check in result.checks]     # what to confirm first
result.to_dict()                                # everything, as plain JSON types
```

`data` can be a pandas or polars DataFrame, or a list of row dictionaries.
`columns` maps each role the lens needs to one of your column names. You can
leave a role out when your data already has a column with that name.

To run a lens on a file without writing Python, use the
[command line](cli.md).

## Functions

### `list_lenses()`

Returns a `LensInfo` for every lens: its `id`, `title`, the `question` it
answers, a `summary`, its `roles` (the columns it can use), its `input_modes`
(the shapes of data it accepts), its `options` and its `coverage`.

### `describe_lens(lens_id)`

Returns the `LensInfo` for one lens. Raises `KeyError` for an unknown id.

### `run_lens(lens_id, data, columns=None, options=None)`

Runs a lens and returns a `LensResult`.

Raises `LensInputError` (a `ValueError`) when the data, the column mapping or
an option cannot be used. The message is written for a person and
`error.problems` lists each problem separately.

## Drawing the map

A result describes its map; `render_map` draws it as an SVG picture with a
legend and the credits the data licences ask for.

```python
from kindtech.lenses import render_map

svg = render_map(result)                  # the first layer: deprivation decile
svg = render_map(result, layer="people")  # people reached, in bands

with open("map.svg", "w", encoding="utf-8") as handle:
    handle.write(svg)
```

The picture is drawn from the result's own table of totals, so it shows
nothing the result does not already hold. People are shown in bands, and the
lowest band includes zero. Hover over an area in a browser to see its name and
value. The colours adapt to a dark page.

`render_map` fetches the outline of each area from the ONS Open Geography
Portal. Only the public area codes of the catchment are sent. To draw without
the network, pass `boundaries=` a GeoJSON FeatureCollection you already have;
`load_map_boundaries(result)` fetches one you can save and reuse.

## Small counts

A count from 1 to 4 that is about a named place or a group is returned as
`None`, with `suppressed` set to `True`, and so is anything worked out from it.
When hiding one cell would let it be worked out from a total, a second cell is
hidden with it. Change the threshold with the `suppress_below` option; it
cannot go below 3.

## Reach against deprivation

`reach-deprivation` answers: are we reaching people in the most deprived
neighbourhoods? It covers England, using the English Indices of Deprivation
2025 on 2021 neighbourhoods (LSOAs).

It accepts two shapes of data:

| Input mode | Columns | What it is |
| --- | --- | --- |
| `postcodes` | `postcode` | One row per person or case, with a home postcode |
| `neighbourhood_counts` | `lsoa_code`, `count` | Already totalled by 2021 LSOA |

In `postcodes` mode the distinct, well-formed postcodes are sent to
[postcodes.io](https://postcodes.io/) to find their neighbourhoods. No other
column leaves your machine, and rows that are blank or not shaped like a
postcode are never sent. In `neighbourhood_counts` mode nothing leaves your
machine.

The lens then works out your **catchment**: the local authorities that each
hold at least 5% of the people it could place. The decile figures and the map
are about the people who live there, so they can be set against everyone who
lives there. People outside the catchment are counted in the local authority
table, and a warning says how many there are.

| Figure | Meaning |
| --- | --- |
| `people_supplied` | People in the data you gave |
| `people_located` | People placed in an English neighbourhood |
| `people_in_catchment` | People who live in the catchment |
| `share_most_deprived_10` | Share of them in the 10% most deprived neighbourhoods in England |
| `share_most_deprived_20` | Share of them in the 20% most deprived neighbourhoods in England |
| `catchment_share_most_deprived_20` | Share of catchment residents who live in those neighbourhoods, for comparison |
| `reach_per_1000_most_deprived_20` | People reached per 1,000 residents of those neighbourhoods |
| `reach_per_1000_elsewhere` | People reached per 1,000 residents in the rest of the catchment |

| Table | Rows |
| --- | --- |
| `by_decile` | One per deprivation decile: people, share of people, residents, share of residents, people per 1,000 |
| `by_local_authority` | One per local authority; authorities outside the catchment with few people share one unnamed row |
| `by_neighbourhood` | One per catchment neighbourhood: decile, residents, and people in bands. This feeds the map |

| Option | Default | Meaning |
| --- | --- | --- |
| `suppress_below` | `5` | Counts above zero and below this are hidden |
| `catchment` | worked out | A local authority name or code, a list of them, or `"England"` |
| `catchment_min_share` | `0.05` | The share a local authority needs to join a worked-out catchment |

```python
result = run_lens(
    "reach-deprivation",
    clients,
    columns={"postcode": "Client postcode"},
    options={"catchment": ["Lewisham", "Greenwich"]},
)
```

!!! note "Before you use the figures"
    Read `result.checks` and `result.caveats`. Deprivation is measured for
    neighbourhoods, not people: someone who lives in a deprived neighbourhood
    is not necessarily deprived.

## Writing a lens

A lens is a `LensInfo` and a function that takes a `LensInput` and returns a
`LensResult`. Register it with `register_lens`. The rules every lens keeps:

1. Totals, never rows. Report problems by how many rows they affect.
2. Hide small counts and anything that gives them away. Do not publish two
   breakdowns that can be taken from each other to get a small count.
3. Give every figure a source.
4. State every choice and name the option that changes it.
5. Leave checks for a person to answer.
6. List anything sent off the machine in `privacy.sent_to_third_parties`.
