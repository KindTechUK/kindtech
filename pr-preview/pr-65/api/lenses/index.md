# Lenses

A lens answers one question a charity asks of its own data. You give it a
table, say which column is which, and it joins your data to UK open data and
returns figures you can check and reuse.

Every lens returns the same things:

- **figures**: the headline numbers
- **tables**: totals behind the figures
- **a map description**: which areas to draw and what to colour them by, when
  the lens has a map
- **chart descriptions**: which table and columns to draw as a bar chart
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

A role with `reported` set to `True` holds names the result uses too, such as
local authorities, so the same names can appear in the result. Values of every
other role are never repeated.

A reported role can also list `reported_values`. That is for a column that
holds a person's own words as well, such as their ethnic group: only the
listed values are names the result uses, and no other value in the column is
ever repeated. If you check a result for values repeated from the input, leave
out the listed values when there are any, compared without case, and check
every other value in the column. Leave the whole column out only when the
role is reported and lists no values.

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

## Charts

`result.charts` describes the charts a result is best shown with, so a page
can draw them without knowing the lens. Each `Chart` names a table of the
result, the column that names each group of bars (`category_column`) and one
or more `series`, each a column with a label and a unit. Every series in a
chart has the same unit, so one axis serves them all.

```python
chart = result.charts[0]
frame = result.table(chart.table).to_frame()
frame.plot.bar(x=chart.category_column, y=[s.column for s in chart.series])
```

A value hidden to protect a small count is `None` in the table. Draw no bar
for it.

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

In `postcodes` mode the lens looks postcodes up in the
[postcode table on your machine](postcodes.md#looking-up-postcodes-on-this-machine)
when one is installed, and then no postcode is sent anywhere. Install it once
with `uk-open-data postcodes download`. Without the table, the distinct,
well-formed postcodes are sent to [postcodes.io](https://postcodes.io/); no
other column leaves your machine, and rows that are blank or not shaped like a
postcode are never sent. The result says which happened, under `choices` and
`privacy`. In `neighbourhood_counts` mode nothing leaves your machine.

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

The chart `people_by_decile` sets the share of your people in each decile
against the share of catchment residents.

| Table | Rows |
| --- | --- |
| `by_decile` | One per deprivation decile: people, share of people, residents, share of residents, people per 1,000 |
| `by_local_authority` | One per local authority; authorities outside the catchment with few people share one unnamed row |
| `by_neighbourhood` | One per catchment neighbourhood: decile, residents, and people in bands. This feeds the map |

| Option | Default | Meaning |
| --- | --- | --- |
| `suppress_below` | `5` | Counts above zero and below this are hidden |
| `postcode_lookup` | `"auto"` | `"offline"` uses the table on your machine and fails without one, `"online"` uses postcodes.io, `"auto"` uses the table when it is installed |
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

## Need against reach

`need-reach` answers: where is need high and our presence low? It covers
England and Wales, by local authority, and is the method of the
[Smart Works case study](../case-studies/smart-works-woman-unemployment.md)
turned into a function.

It accepts two shapes of data:

| Input mode | Columns | What it is |
| --- | --- | --- |
| `postcodes` | `postcode` | One row per person or case, with a home postcode |
| `area_counts` | `local_authority`, `count` | Already totalled by local authority, named or coded |

Postcodes are placed as in the first lens: on your machine when the postcode
table is installed, and with postcodes.io otherwise.

The lens loads a count of **people in need** in every local authority from
[Nomis](ons.md), divides the people you helped in each one by it, and lists
the high-need local authorities where you reach the fewest people per 100 in
need. A local authority is high need when its count is at or above the middle
value of the area compared.

Choose the need with the `need` option:

| `need` | People counted |
| --- | --- |
| `"unemployed"` (default) | Unemployed people aged 16 to 64, not counting full-time students, Census 2021 |
| `"unemployed_women"` | Unemployed women aged 16 to 64, not counting full-time students, Census 2021 |
| `"unemployed_men"` | Unemployed men aged 16 to 64, not counting full-time students, Census 2021 |
| `{"dataset": ..., "label": ..., "filters": {...}}` | Any table Nomis publishes by local authority. The filters are the category codes to add up |

The three built-in needs count the census group "Economically active
(excluding full-time students): Unemployed", as the case study does. Full-time
students who were looking for work are a separate census group and are not
counted. To count them too, give the table form with both groups:

```python
options = {
    "need": {
        "dataset": "NM_2124_1",
        "label": "Unemployed people aged 16 to 64, with full-time students",
        "filters": {
            "c2021_eastat_7": [2, 4],
            "c_sex": 0,
            "c2021_age_7": [2, 3, 4, 5],
        },
    }
}
```

The need figures are public. They are fetched from Nomis once for each need
and then kept in memory for as long as the program runs;
`clear_need_cache()` forgets them. To run with no request to Nomis at all,
keep a copy on the machine, in the same data folder as the
[postcode table](postcodes.md#looking-up-postcodes-on-this-machine):

```python
from kindtech.lenses.need_reach import download_need_figures, keep_need_figures

download_need_figures("unemployed")   # fetch once, when a server is built

# or keep figures of your own under a built-in need, for a demonstration
keep_need_figures(
    "unemployed",
    [("E09000023", "Lewisham", 9000), ("E09000011", "Greenwich", 8000)],
    note="invented for a demonstration.",
)
```

A result that used a kept copy says so in its `sources` and its `working`,
with the note the copy was kept with.

By default every local authority in England and Wales is compared. If you
serve a smaller area, name it with `catchment`, so that places you could not
reach are not listed as gaps.

| Figure | Meaning |
| --- | --- |
| `people_supplied` | People in the data you gave |
| `people_located` | People placed in a local authority in England or Wales |
| `people_in_catchment` | People who live in the area compared |
| `areas_compared` | Local authorities compared |
| `people_in_need` | People in need in the area compared |
| `reach_per_100_in_need` | People you reached per 100 people in need, across the area |
| `high_need_areas` | Local authorities with high need |
| `high_need_areas_without_people` | High-need local authorities where you reached nobody |
| `share_of_people_in_high_need_areas` | Share of your people who live in high-need local authorities |
| `share_of_need_in_high_need_areas` | Share of people in need who live there, for comparison |

The charts `need_in_priority_areas` and `reach_in_priority_areas` show people
in need and people reached per 100 in need for the places in `priority_areas`.

| Table | Rows |
| --- | --- |
| `priority_areas` | The high-need local authorities with the lowest reach, lowest first: people in need, people, people per 100 in need |
| `by_local_authority` | One per local authority compared, with need and reach in bands. This feeds the map |

| Option | Default | Meaning |
| --- | --- | --- |
| `suppress_below` | `5` | Counts above zero and below this are hidden |
| `postcode_lookup` | `"auto"` | As for the first lens |
| `need` | `"unemployed"` | The need to compare your reach with |
| `catchment` | England and Wales | A local authority name or code, a list of them, or `"England"`, `"Wales"` or `"England and Wales"` |
| `top` | `10` | How many places to list, from 1 to 50 |

```python
result = run_lens(
    "need-reach",
    clients,
    columns={"postcode": "Client postcode"},
    options={"need": "unemployed_women"},
)

result.table("priority_areas").to_frame()
```

A local authority with a hidden count is still ranked. It is ranked as if it
had the largest count that would be hidden, which depends on the threshold
alone, so the order of the list gives nothing away.

!!! note "Before you use the figures"
    Read `result.checks` and `result.caveats`. Low reach is not the same as
    unmet need: another organisation may already serve the place. Need is a
    count of people, so large local authorities are more likely to be listed.

## Who we are missing

`who-we-miss` answers: who do we reach less than their share of the people who
live here? It covers England and Wales, and is the method of the
[Sobus case study](../case-studies/sobus-bame-analysis.md) turned into a
function.

It accepts three shapes of data:

| Input mode | Columns | What it is |
| --- | --- | --- |
| `postcodes` | `group`, `postcode` | One row per person, with their group and home postcode |
| `group_counts` | `group`, `count` | Already totalled by group |
| `people` | `group` | One row per person, with their group and no location |

The `group` column holds each person's ethnic group, or their sex, in your own
words. The lens matches each label to a group the 2021 Census publishes,
counts your people by group, and sets each group's share of your people
against its share of the residents of your **catchment**. A group is
**under-represented** when its share of your people is below four fifths of
its share of residents.

Choose what the column holds with the `characteristic` option:

| `characteristic` | Groups compared | Census table |
| --- | --- | --- |
| `"ethnic_group"` (default) | Asian, Black, Mixed, White, Other | TS021 |
| `"sex"` | Female, Male | TS008 |

Labels are matched by their wording. "Black Caribbean" is Black, "White and
Black Caribbean" is Mixed, "Any other ethnic group" is Other, and "Not stated"
matches nothing. People whose label matches nothing are counted, left out of
the shares, and a warning says how many there are. Codes and short forms
cannot be matched by wording, so say where they belong with the `groups`
option:

```python
result = run_lens(
    "who-we-miss",
    clients,
    columns={"group": "Ethnicity", "postcode": "Client postcode"},
    options={"groups": {"BAF": "Black", "WBR": "White"}},
)

result.table("by_group").to_frame()
```

The result names the census groups. It never repeats one of your own labels.
The `group` role lists the census group names as its `reported_values`,
because a label of yours can be the same as one of them.

With postcodes the lens works out your catchment as the first lens does: the
local authorities that each hold at least 5% of the people it could place.
People who live outside it are left out, because they are set against the
residents of the catchment. Without postcodes the lens cannot tell where you
work, so you must name the area with `catchment`.

The residents come from [Nomis](ons.md), for every local authority at once.
They are public, are fetched once for each characteristic and are then kept in
memory; `clear_residents_cache()` forgets them. To run with no request to
Nomis, keep a copy on the machine, as for need figures:

```python
from kindtech.lenses.who_we_miss import download_residents, keep_residents

download_residents("ethnic_group")   # fetch once, when a server is built

# or keep figures of your own, for a demonstration
keep_residents(
    "sex",
    [("E09000023", "Lewisham", {"Female": 156000, "Male": 144000})],
    note="invented for a demonstration.",
)
```

| Figure | Meaning |
| --- | --- |
| `people_supplied` | People in the data you gave |
| `people_in_catchment` | People set against residents: with postcodes, those who live in the catchment |
| `people_matched` | People whose label matched a census group. The shares are of these people |
| `people_not_matched` | People with no label, or one that matched no census group |
| `residents` | Residents of the catchment in the 2021 Census |
| `groups_under_represented` | Groups you reach less than their share of residents |

The chart `people_against_residents` sets the share of your people in each
group against the share of residents.

| Table | Rows |
| --- | --- |
| `by_group` | One per census group: people, share of people, residents, share of residents, `representation` (the first share divided by the second) and whether the group is under-represented |

| Option | Default | Meaning |
| --- | --- | --- |
| `suppress_below` | `5` | Counts above zero and below this are hidden |
| `postcode_lookup` | `"auto"` | As for the first lens |
| `characteristic` | `"ethnic_group"` | What the group column holds |
| `groups` | none | Your label to census group, for labels the wording does not settle |
| `catchment` | worked out from postcodes | A local authority name or code, a list of them, or `"England"`, `"Wales"` or `"England and Wales"`. Needed when there are no postcodes |
| `catchment_min_share` | `0.05` | The share a local authority needs to join a worked-out catchment |
| `under_represented_below` | `0.8` | A group is under-represented below this fraction of its share of residents |

A group with a hidden count is not judged. A group nobody came from has a
count of zero, which is shown, and is under-represented.

This lens has no map yet. The residents are compared across the whole
catchment, not place by place.

!!! note "Before you use the figures"
    Read `result.checks` and `result.caveats`. A gap is not proof of a
    barrier: groups differ in age and in need, and the census counts
    residents of every age. With few people, a gap can be chance. Do not
    publish two runs with different catchments side by side, because a small
    count can be worked out by taking one from the other.

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
