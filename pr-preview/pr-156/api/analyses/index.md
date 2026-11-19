# Analyses

An analysis answers one question a charity asks of its own data. You give it a
table, say which column is which, and it joins your data to UK open data and
returns figures you can check and reuse.

Kindtech Evidence is built on these analyses. This page is about running them
from Python. You can also run them from the [command line](cli.md), or from a
chat assistant through the [connector](connector.md).

These analyses follow work first done by
[DataKind UK](https://www.datakind.org.uk/) volunteers with charities. The
[case studies](../case-studies/index.md) reproduce five of those projects.

Every analysis returns the same things:

- **an answer**: one or two sentences that answer the question, and the
  three figures to show first
- **figures**: the headline numbers
- **tables**: totals behind the figures
- **a map description**: which areas to draw and what to colour them by, when
  the analysis has a map
- **chart descriptions**: which table and columns to draw as a bar chart
- **the working**: each step taken, with how many rows went in and came out,
  the figures before rounding and the code that runs it again
- **choices**: what the analysis decided for you, and the option that changes it
- **checks**: what a person must confirm before using the figures
- **caveats**: what the figures cannot say
- **sources**: publisher, edition, licence and link for every dataset used
- **a privacy summary**: what was hidden, and what left your machine

A result holds totals only. Nothing in it describes one person, and no value
from your data is repeated back, not even in a warning or an error message.

## Quick start

```python
import pandas as pd
from uk_open_data.analyses import run_analysis

clients = pd.read_csv("clients.csv")

result = run_analysis(
    "reach-deprivation",
    clients,
    columns={"postcode": "Client postcode"},
)

result.answer                                   # the question, answered in a sentence
result.figure("share_most_deprived_20").value   # 41.3 (per cent)
result.table("by_decile").to_frame()            # pandas or polars DataFrame
[check.question for check in result.checks]     # what to confirm first
result.to_dict()                                # everything, as plain JSON types
```

`data` can be a pandas or polars DataFrame, or a list of row dictionaries.
`columns` maps each role the analysis needs to one of your column names. You can
leave a role out when your data already has a column with that name.

To run an analysis on a file without writing Python, use the
[command line](cli.md).

## Functions

### `list_analyses()`

Returns an `AnalysisInfo` for every analysis: its `id`, `title`, the `question` it
answers, a `summary`, its `roles` (the columns it can use), its `input_modes`
(the shapes of data it accepts), its `options` and its `coverage`.

Every option has two names. `name` is its code name, the one a call is
written with, such as `catchment`. `label` is its short plain name, such as
"Area you serve". Show the label beside the option. Every message that points a
person at an option uses the label, in quotes ("Change 'Area you serve' to
include them."), and never the code name, so the sentence matches what is on
the screen. An option has the same label in every analysis that has it, and
the result's `choices` use the same label for the choice it made:

| `name` | `label` |
| --- | --- |
| `catchment` | Area you serve |
| `catchment_min_share` | Share that makes a place part of your area |
| `suppress_below` | Smallest count shown |
| `postcode_lookup` | Where postcodes are looked up |
| `need` | People you are trying to reach |
| `top` | Places listed |
| `characteristic` | What people are grouped by |
| `groups` | How your labels match census groups |
| `under_represented_below` | What counts as under-represented |
| `within_km` | Distance within reach, in kilometres |

The area an analysis looks across has one name wherever a person reads it:
"the area you serve". `catchment` is only its code name.

A table's columns have plain names too. `table.columns` holds the ids, which a
program reads, and `table.headings` maps each id to the heading to show, such
as "Your people per 100 in need" for `people_per_100_in_need`. `table.units`
gives the unit of each column that has one, named as the units of figures
are: `"percent"` or `"km"`. Show a table with its headings and units and it
reads the same on a page, in a chat and on the command line. A place is a
"Local authority" in most tables and a "Neighbourhood" in the one behind the
first analysis's map.

An option that takes one of a fixed list of values lists them as `choices`,
each with a `value` and a `label` a person can read, so a page can show a list
to pick from. `choices` is empty when the option is free, such as a number or
a place name. For the `need` option the choices are the built-in needs; a table
of your own is still given as a mapping.

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

A role with `amount` set to `True` holds a number the analysis adds up: a count of
people or a volume. A total of it is in the result, so where one row is the
only one for its place or group, that row's number comes back as the total.
That is not a repeated value. A number in any other role, such as a latitude,
never comes back.

### `describe_analysis(analysis_id)`

Returns the `AnalysisInfo` for one analysis. Raises `KeyError` for an unknown id.

### `run_analysis(analysis_id, data, columns=None, options=None)`

Runs an analysis and returns an `AnalysisResult`.

Raises `AnalysisInputError` (a `ValueError`) when the data, the column mapping or
an option cannot be used. The message is written for a person and
`error.problems` lists each problem separately.

`error.option` is the code name of the option the error is about, and
`error.role` the name of the column role, so a page can mark the right box and
a program need not search the sentence. When the problems are about several,
it is the first of them. Each is `None` when the error is about neither, for
example when a source could not be read. The command line adds what to type:
"On the command line this is --option catchment=VALUE."

When the columns an analysis needs were not all found, `error.role` is the
first one still to be named. When an option was given that the analysis does
not have, the message lists each option it does have by both names:
"need ('People you are trying to reach')".

When a public data source the analysis needs cannot be reached, the
`requests.RequestException` is let out. Its text holds the whole web address
that was asked for, which can hold a postcode, so show a message of your own
rather than the text. The command line names the site alone, and says
whether the source could not be reached or answered with an error. An analysis
needs no network when the public figures it uses are kept on your machine.

### `record_run(analysis_id, input_mode, door)`

Records that a run has given a person an answer, so that a host can count how
often each analysis is used. It writes one record at `INFO` level to the
`uk_open_data.runs` logger, and that is all it does: the package adds no handler
and sends nothing anywhere. On a person's own machine nobody collects the
records. A host that keeps its logs can count them.

```python
from uk_open_data.analyses import record_run

record_run(result.analysis_id, result.input_mode, "page")
# run analysis=reach-deprivation mode=postcodes door=page
```

`run_analysis` never records a run by itself. Whatever gives the answer to a
person calls `record_run` once, after the answer has been given: the command
line does (`"cli"`), and a page (`"page"`) or a chat assistant (`"chat"`) built
on these analyses should. A run that fails is not recorded.

The record holds the three words and nothing else. Each must be on a fixed
list (a registered analysis, one of its input modes, one of the three doors),
so no word from a person's data can reach a log. A word that is not on its list
raises `KeyError` (the analysis) or `ValueError` (the mode or the door), and the
message does not repeat it. The same three words are on the record as
`record.analysis_id`, `record.input_mode` and `record.door`.

A host that keeps the records imports the logger's name, and the doors, from
the package, so neither is typed out a second time:

```python
import logging

from uk_open_data.analyses import DOORS, RUNS_LOGGER

logging.getLogger(RUNS_LOGGER).setLevel(logging.INFO)
```

## Drawing the map

A result describes its map; `render_map` draws it as an SVG picture with a
key and the credits the data licences ask for.

```python
from uk_open_data.analyses import render_map

svg = render_map(result)                  # the first layer: deprivation decile
svg = render_map(result, layer="people")  # people reached, in bands

with open("map.svg", "w", encoding="utf-8") as handle:
    handle.write(svg)
```

The picture is drawn from the result's own table of totals, so it shows
nothing the result does not already hold. People are shown in bands, and the
lowest band includes zero. Hover over an area in a browser to see its name and
value. The colours adapt to a dark page.

A picture shows one layer, and its title says what the colour shows: "People
reached, by neighbourhood". The first layer of a map is drawn in blue and the
second in orange, so two pictures of one result do not look like the same
measure. The shaded areas sit in a frame with a scale line. Up to twelve
local authorities are named one by one; neighbourhoods are named by the local
authority they are in. A name that would cover most of a small place is
written beside it, where there is room, so its colour can be seen. Text is broken into lines to fit the width you ask for.

The places around the map are drawn in pale grey, with their names where a
name fits, when you give their outlines. Only the part of each that the frame
shows is written to the picture, so a large neighbour does not make the file
large. Put them among the features of
`boundaries`, or in a list under `"surroundings"`. Codes listed under
`"focus"` are the surrounding places that hold the shaded areas: each gets a
darker line and its name. Codes listed under `"shore"` are surrounding places
whose outline is where the land ends. The shaded areas are drawn no further
than it, and the picture is framed on it. Use it when the outlines of the
areas run out over water and the outline of the place that holds them does
not.

```python
boundaries = {
    "type": "FeatureCollection",
    "features": areas,           # outlines you already have
    "surroundings": nearby,
    "focus": ["E09000023"],
    "shore": ["E09000023"],
}
svg = render_map(result, boundaries=boundaries)
```

`render_map` fetches the outline of each area from the ONS Open Geography
Portal. Only the public area codes of the area you serve, and of the local
authorities near it, are sent. To draw without the network, pass `boundaries=`
a GeoJSON FeatureCollection you already have; `load_map_boundaries(result)`
fetches one you can save and reuse.

`load_map_boundaries` fetches the places around the map as well, and lists
under `"focus"` the local authorities that hold a map's neighbourhoods. A map
of up to 1,000 neighbourhoods or 20 local authorities is drawn large, so its
outlines come from the full ones with detail finer than 10 or 20 metres left
out. So do the local authorities that hold its neighbourhoods, and the other
places a picture of the usual width shows when there are no more than 40 of
them, so that neighbours meet. A place further off keeps its 200 metre
outline.

The full outlines of local authorities stop at the shore. The only full
outlines of neighbourhoods that are open run out to low water and to the
middle of a river. So on a map of neighbourhoods the local authorities that
hold them are also listed under `"shore"`, and a river or a bay is left
clear. When the fine outline of one of them does not come, nothing is listed
and the neighbourhoods are drawn whole.

A map of more areas is drawn small and takes outlines simplified to 200
metres. Every map asks for every local authority at 200 metres, nearly three
megabytes, to find the ones near it. That answer is kept in memory for the
life of the process, so a second map does not ask again;
`uk_open_data.analyses.maps.clear_outline_cache()` forgets it. When the places around cannot be fetched, the map is drawn without
them and nothing is said.

The fine outlines usually come in a few seconds. At times the service has
taken from a quarter of a minute to a minute or two for one map, and it is
not known why. A program that cannot wait,
such as one answering in a chat, calls `load_map_boundaries(result,
fine=False)`. It then gets the 200 metre outlines of every area, and the
places around from the answer kept in memory, in a second or two.
`load_map_boundaries` is safe to call from two threads at once.

## The answer

`result.answer` is one or two sentences that answer the question the analysis
asks, for example:

> Of your people in the area you serve, 49.0% live in the 20% most deprived
> neighbourhoods in England. Of everyone who lives in that area, 20.0% do, so
> you reach those neighbourhoods more than their share.

Open with it wherever you show a result, so a report, a page and a chat
assistant all say the same thing. It is built from the figures and tables of
the result, after small counts are hidden, so it says nothing the result does
not already show. When the figure it rests on is hidden, it says so instead of
giving a number. The places and groups it names are the public names in the
result's tables, never text from your data.

The sentence is careful about what it calls a gap. A place is named as one to
look at first only when it falls below the rate for the whole area, so a list
of one or two places does not present the place you reach most as a gap, and a
place whose count is hidden is not named. A count of every resident is called
"residents", not "people in need". A group with nobody in your data is named
last, with a line saying so, because it may be a group you do not record.

`result.key_figures` holds the ids of up to three figures to show first, in
order. Each is a figure of the result, and none is hidden: when a figure that
would be shown first is hidden to protect a small count, the next one takes
its place.

```python
for figure_id in result.key_figures:
    figure = result.figure(figure_id)
    print(figure.label, figure.value, figure.unit)
```

## Checking a result and running it again

A result shows its working, so that anyone can check it or run it again.

`result.working` lists each step in plain words, with how many rows went in
and came out. `result.sources` gives each source and its date.

A share or a rate is rounded before it is shown. `figure.exact` is the value
before rounding:

```python
figure = result.figure("share_most_deprived_20")
figure.value   # 68.6
figure.exact   # 68.57142857142857
```

`exact` is `None` for a count, which is not rounded, and for a figure that is
hidden to protect a small count. It is also `None` for a distance from one
place to a site, which is rounded to the kilometre on purpose so that it says
less about where a site is.

`result.code` is the Python that runs the analysis again with the same
settings:

```python
print(result.code)
```

```python
# Version 0.1 of this analysis, run with
# uk-open-data 0.2.0. This runs it again with
# the same settings. No row or heading of your table is written
# here: put the name of your own column beside each role.
import pandas as pd

from uk_open_data.analyses import run_analysis

data = pd.read_csv("your-table.csv")
result = run_analysis(
    "reach-deprivation",
    data,
    columns={
        "postcode": "",  # the name of your column
    },
    options={
        "suppress_below": 10,
        "postcode_lookup": "auto",
        "catchment_min_share": 0.05,
    },
)
print(result.answer)
for figure in result.figures:
    print(figure.label, figure.value)
```

It prints the answer and every figure, to set beside the ones in the result.

Every setting that has a value is written out, the ones you left alone too,
so the code gives the same result if a default changes in a later version.
That is why it can hold a setting the list of choices in a result does not
mention. A setting the analysis works out for itself, such as the area you
serve when you named none, is left out. An area you named is written as you
gave it.

The setting for where postcodes are looked up is written as it was used. Code
copied from a run that kept postcodes on one machine says so, and on another
machine it stops and asks for the postcode table before it sends a postcode
anywhere.

The code holds no row and no heading of your table. The names of your columns
are left for you to fill in, because a heading can hold something private. A
setting that holds your own words, such as your own labels for groups in
`who-we-miss`, is written as `{}` with a note to fill it in. So the code is as
safe to share as the result is.

The command line prints both as the last two parts of its report, under
"Figures before rounding" and "To run it again in Python". The code starts at
the margin, so it runs as it is copied.

## Charts

`result.charts` describes the charts a result is best shown with, so a page
can draw them without knowing the analysis. Each `Chart` names a table of the
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
hidden with it. So a hidden count is not always small: do not report a hidden
cell as "fewer than 5". Every result says this in its privacy notes. Change
the threshold with the `suppress_below` option; it cannot go below 3.

A result says which threshold was used in `privacy.suppress_below`. The analyses
about sites, provision gap and access and distance, hide nothing, and for them
it is `None`.

## Reach against deprivation

`reach-deprivation` answers: are we reaching people in the most deprived
neighbourhoods? It covers England, using the English Indices of Deprivation
2025 on 2021 neighbourhoods (LSOAs).

It accepts two shapes of data:

| Input mode | Columns | What it is |
| --- | --- | --- |
| `postcodes` | `postcode` | One row per person or case, with a home postcode |
| `neighbourhood_counts` | `lsoa_code`, `count` | Already totalled by 2021 LSOA |

In `postcodes` mode the analysis looks postcodes up in the
[postcode table on your machine](postcodes.md#looking-up-postcodes-on-this-machine)
when one is installed, and then no postcode is sent anywhere. Install it once
with `uk-open-data postcodes download`. Without the table, the distinct,
well-formed postcodes are sent to [postcodes.io](https://postcodes.io/); no
other column leaves your machine, and rows that are blank or not shaped like a
postcode are never sent. The result says which happened, under `choices` and
`privacy`. In `neighbourhood_counts` mode nothing leaves your machine.

The deprivation index is downloaded from gov.uk, or read from a copy
[kept on your machine](imd.md#keeping-the-english-index-on-this-machine) when
there is one. A result that used a copy says so in its `sources` and its
`working`, with the note the copy was kept with.

The analysis then works out **the area you serve**: the local authorities that each
hold at least 5% of the people it could place. The decile figures and the map
are about the people who live there, so they can be set against everyone who
lives there. People outside the area you serve are counted in the local authority
table, and a warning says how many there are.

| Figure | Meaning |
| --- | --- |
| `people_supplied` | People in the data you gave |
| `people_located` | People placed in an English neighbourhood |
| `people_in_catchment` | People who live in the area you serve |
| `share_most_deprived_10` | Share of them in the 10% most deprived neighbourhoods in England |
| `share_most_deprived_20` | Share of them in the 20% most deprived neighbourhoods in England |
| `catchment_share_most_deprived_20` | Share of residents of the area you serve who live in those neighbourhoods, for comparison |
| `reach_per_1000_most_deprived_20` | People reached per 1,000 residents of those neighbourhoods |
| `reach_per_1000_elsewhere` | People reached per 1,000 residents in the rest of the area you serve |

The chart `people_by_decile` sets the share of your people in each decile
against the share of residents of the area you serve.

| Table | Rows |
| --- | --- |
| `by_decile` | One per deprivation decile: people, share of people, residents, share of residents, people per 1,000 |
| `by_local_authority` | One per local authority; authorities outside the area you serve with few people share one unnamed row |
| `by_neighbourhood` | One per neighbourhood in the area you serve: decile, residents, and people in bands. This feeds the map |

| Option | Default | Meaning |
| --- | --- | --- |
| `suppress_below` | `5` | Counts above zero and below this are hidden |
| `postcode_lookup` | `"auto"` | `"offline"` uses the table on your machine and fails without one, `"online"` uses postcodes.io, `"auto"` uses the table when it is installed |
| `catchment` | worked out | A local authority name or code, a list of them, or `"England"` |
| `catchment_min_share` | `0.05` | The share a local authority needs to join a worked-out area |

```python
result = run_analysis(
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

Postcodes are placed as in the first analysis: on your machine when the postcode
table is installed, and with postcodes.io otherwise.

The analysis loads a count of **people in need** in every local authority from
[Nomis](ons.md), divides the people you helped in each one by it, and lists
the high-need local authorities where you reach the fewest people per 100 in
need. A local authority is high need when its count is in the top quarter of
the area you serve. With fewer than four places, the one with the largest count
is high need.

Choose the need with the `need` option:

| `need` | People counted |
| --- | --- |
| `"unemployed"` (default) | Unemployed people aged 16 to 64, not counting full-time students, Census 2021 |
| `"unemployed_women"` | Unemployed women aged 16 to 64, not counting full-time students, Census 2021 |
| `"unemployed_men"` | Unemployed men aged 16 to 64, not counting full-time students, Census 2021 |
| `"residents"` | Everyone who lives there, of every age, Census 2021. Use it when what you offer is for anyone |
| `{"dataset": ..., "label": ..., "filters": {...}}` | Any table Nomis publishes by local authority. The filters are the category codes to add up. Counts are asked for (`measures` 20100) unless the filters name another measure |

The three unemployment needs count the census group "Economically active
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
from uk_open_data.analyses.need_reach import download_need_figures, keep_need_figures

download_need_figures("unemployed")   # fetch once, when a server is built
download_need_figures("residents")    # so the map can shade need by its rate

# or keep figures of your own under a built-in need, for a demonstration
keep_need_figures(
    "unemployed",
    [("E09000023", "Lewisham", 9000), ("E09000011", "Greenwich", 8000)],
    note="invented for a demonstration.",
)
```

A result that used a kept copy says so in its `sources` and its `working`,
with the note the copy was kept with.

The area you serve should hold the places you do not reach yet as well. Name it with `catchment`: a
list of local authorities, or a country. When you leave it out, the analysis
works the area out as the first analysis does: each local authority that holds
at least 5% of the people located (`catchment_min_share`). When none does,
every local authority in England and Wales is compared.

An area worked out this way holds only places you already reach, so it can
show where your reach is low against need but not where you reach nobody. The
result says so in a warning. To see the places you do not reach, name the area.

| Figure | Meaning |
| --- | --- |
| `people_supplied` | People in the data you gave |
| `people_located` | People placed in a local authority in England or Wales |
| `people_in_catchment` | People who live in the area you serve |
| `areas_compared` | Local authorities compared |
| `people_in_need` | People in need in the area you serve |
| `reach_per_100_in_need` | People you reached per 100 people in need, across the area |
| `high_need_areas` | Local authorities with high need |
| `high_need_areas_without_people` | High-need local authorities where you reached nobody |
| `share_of_people_in_high_need_areas` | Share of your people who live in high-need local authorities |
| `share_of_need_in_high_need_areas` | Share of people in need who live there, for comparison |

The charts `need_in_priority_areas` and `reach_in_priority_areas` show people
in need and people reached per 100 in need for the places in `priority_areas`.

The labels follow the need. When the need is every resident, the figures, the
headings, the list, the working and the source say "residents" and "the local
authorities with the most residents", not "people in need" and "high need".
The fourth and fifth analyses do the same.

The answer says so when the area was worked out from your data: it opens "In
the 7 local authorities where most of your people live". When a fifth or more
of the people in your data could not be placed in the area you serve, it ends
by saying how many are not counted. When some of them could not be placed in
any local authority, which is a name or a postcode to put right, and others
live outside the area, which is not a mistake, it says how many of each.

When only one local authority is compared every share is 100%, so
`key_figures` names the rate and the two counts behind it instead:
`reach_per_100_in_need`, `people_in_catchment` and `people_in_need`.

| Table | Rows |
| --- | --- |
| `priority_areas` | The high-need local authorities, your lowest reach first: people in need, people, people per 100 in need. It is a list in that order and no more: a place on it can have more reach than the area as a whole |
| `by_local_authority` | One per local authority compared, with need and reach in bands, and people in need for each 1,000 residents. This feeds the map |

The map shades need by its rate, people in need for each 1,000 residents, in
five equal groups. With fewer than five places, each is a group of its own,
from the lowest group to the highest, and one place alone is in the middle
group. The three groups of the reach layer work the same way. The note of a
layer says so when its places are fewer than its groups, and says nothing of
it otherwise. A count would
make the largest places darkest whatever their need. The list of high-need places still goes by the count, as
the case study does. The residents are the census count of everyone who lives
in each local authority, loaded beside the need figures.

The map falls back to the count in two cases, and the result says which way
it went in its choices (`map_need`) and in the note of the map's `need` layer.
One is when the need is every resident, so there is no rate to work out. The
other is when the need figures came from a copy kept on the machine and no
copy of the residents is kept beside it: the analysis does not fetch them, so
that a run kept off the network stays off it.

| Option | Default | Meaning |
| --- | --- | --- |
| `suppress_below` | `5` | Counts above zero and below this are hidden |
| `postcode_lookup` | `"auto"` | As for the first analysis |
| `need` | `"unemployed"` | The need to compare your reach with |
| `catchment` | worked out | A local authority name or code, a list of them, or `"England"`, `"Wales"` or `"England and Wales"` |
| `catchment_min_share` | `0.05` | The share a local authority needs to join a worked-out area |
| `top` | `10` | How many places to list, from 1 to 50 |

```python
result = run_analysis(
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
words. The analysis matches each label to a group the 2021 Census publishes,
counts your people by group, and sets each group's share of your people
against its share of the residents of **the area you serve**. A group is
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
result = run_analysis(
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

With postcodes the analysis works out the area you serve as the first analysis does: the
local authorities that each hold at least 5% of the people it could place.
People who live outside it are left out, because they are set against the
residents of the area you serve. Without postcodes the analysis cannot tell where you
work, so you must name the area with `catchment`.

The residents come from [Nomis](ons.md), for every local authority at once.
They are public, are fetched once for each characteristic and are then kept in
memory; `clear_residents_cache()` forgets them. To run with no request to
Nomis, keep a copy on the machine, as for need figures:

```python
from uk_open_data.analyses.who_we_miss import download_residents, keep_residents

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
| `people_in_catchment` | People set against residents: with postcodes, those who live in the area you serve |
| `people_matched` | People whose label matched a census group. The shares are of these people |
| `people_not_matched` | People with no label, or one that matched no census group |
| `residents` | Residents of the area you serve in the 2021 Census |
| `groups_under_represented` | Groups you reach less than their share of residents |
| `share_of_people_first_group` | Share of your people in the first of those groups |
| `share_of_residents_first_group` | Share of residents in that group |

The last two are the two shares the answer quotes, each with its value before
rounding. They are there when the answer quotes them: when a group is reached
less than its share and has people in your data.

The chart `people_against_residents` sets the share of your people in each
group against the share of residents.

| Table | Rows |
| --- | --- |
| `by_group` | One per census group: people, share of people, residents, share of residents, `representation` (the first share divided by the second) and whether the group is under-represented |

| Option | Default | Meaning |
| --- | --- | --- |
| `suppress_below` | `5` | Counts above zero and below this are hidden |
| `postcode_lookup` | `"auto"` | As for the first analysis |
| `characteristic` | `"ethnic_group"` | What the group column holds |
| `groups` | none | Your label to census group, for labels the wording does not settle |
| `catchment` | worked out from postcodes | A local authority name or code, a list of them, or `"England"`, `"Wales"` or `"England and Wales"`. Needed when there are no postcodes |
| `catchment_min_share` | `0.05` | The share a local authority needs to join a worked-out area |
| `under_represented_below` | `0.8` | A group is under-represented below this fraction of its share of residents |

A group with a hidden count is not judged. A group nobody came from has a
count of zero, which is shown, and is under-represented.

This analysis has no map yet. The residents are compared across the whole
area you serve, not place by place.

!!! note "Before you use the figures"
    Read `result.checks` and `result.caveats`. A gap is not proof of a
    barrier: groups differ in age and in need, and the census counts
    residents of every age. With few people, a gap can be chance. Do not
    publish two runs with different areas side by side, because a small
    count can be worked out by taking one from the other.

## Provision gap

`provision-gap` answers: where is provision thin against need across a region?
It covers England and Wales, by local authority, and follows the method of the
[Starlight case study](../case-studies/starlight-children-mapping.md): total
what is provided in each place, divide by the people it is for, and look at
the places where need is high and provision is thin.

The analysis is about sites and what they provide, not about people. It accepts
three shapes of data:

| Input mode | Columns | What it is |
| --- | --- | --- |
| `sites` | `postcode`, `volume` | One row per site or service, with how much it provides |
| `area_volumes` | `local_authority`, `volume` | Already totalled by local authority, named or coded |
| `site_list` | `postcode` | One row per site or service. Each site counts as one |

The volume is a number of zero or more: sessions, places, boxes, hours. A row
whose volume is not a number stops the run, and the message says how many rows
to correct. Postcodes are placed as in the first analysis: on your machine when
the postcode table is installed, and with postcodes.io otherwise.

The analysis loads a count of people in every local authority from
[Nomis](ons.md), divides the provision in each one by it, and lists
the high-need local authorities with the least provision per 1,000
people. A local authority is high need when its count is in the top quarter
of the area you serve, as in the second analysis.

The `need` option takes the same values as in the second analysis, and the same
kept copies (`keep_need_figures`, `download_need_figures`) are used. The
default here is `"residents"`, everyone who lives in the place, because
provision is often for anyone. Choose a narrower need when what you provide is
for a group Nomis counts.

| Figure | Meaning |
| --- | --- |
| `volume_supplied` | Provision in the data you gave |
| `volume_located` | Provision placed in a local authority in England or Wales |
| `volume_in_catchment` | Provision in the area you serve |
| `areas_compared` | Local authorities compared |
| `areas_without_provision` | Local authorities where you provide nothing |
| `people_in_need` | People in need in the area you serve |
| `volume_per_1000_in_need` | Provision per 1,000 people in need, across the area |
| `high_need_areas` | Local authorities with high need |
| `high_need_areas_without_provision` | High-need local authorities where you provide nothing |
| `share_of_provision_in_high_need_areas` | Share of your provision that is in high-need local authorities |
| `share_of_need_in_high_need_areas` | Share of people in need who live there, for comparison |

The charts `need_in_priority_areas` and `provision_in_priority_areas` show
people in need and provision per 1,000 in need for the places in
`priority_areas`. The map has two layers, `need` and `provision`.

| Table | Rows |
| --- | --- |
| `priority_areas` | The high-need local authorities, thinnest provision first: people in need, volume, volume per 1,000 in need. The labels follow the need, as in the second analysis |
| `by_local_authority` | One per local authority compared, with need and provision in bands. This feeds the map |

| Option | Default | Meaning |
| --- | --- | --- |
| `postcode_lookup` | `"auto"` | As for the first analysis |
| `need` | `"residents"` | The people to set your provision against |
| `catchment` | England and Wales | A local authority name or code, a list of them, or `"England"`, `"Wales"` or `"England and Wales"` |
| `top` | `10` | How many places to list, from 1 to 50 |

```python
result = run_analysis(
    "provision-gap",
    sites,
    columns={"postcode": "Site postcode", "volume": "Sessions a year"},
    options={"catchment": "Wales"},
)

result.table("priority_areas").to_frame()
```

This analysis hides no count, and has no `suppress_below` option. Provision is
what an organisation provides, not a number of people, so every total is shown,
however small. Where a local authority holds one site, the provision shown for
it is that site's. If your numbers are people, such as people seen at each site,
use the need against reach analysis instead, which hides small counts. The result
still names no site and repeats no postcode.

The case study compares England's Integrated Care Boards and uses hospital
admissions as the need. This analysis compares local authorities and takes the
need from Nomis. Health boards, and a need column of your own, are not in it
yet.

!!! note "Before you use the figures"
    Read `result.checks` and `result.caveats`. Thin provision is not the same
    as unmet need: another organisation may already provide there. Provision
    is counted where a site is, and people travel. Need is a count of people,
    so large local authorities are more likely to be listed.

## Access and distance

`access-distance` answers: how far are people from our nearest site, and where
would a new site help most? It covers England and Wales, by local authority,
and follows the method of the
[Material Focus case study](../case-studies/material-focus-recycling.md).

Like the provision gap analysis, it is about sites, not about people. It accepts
two shapes of data:

| Input mode | Columns | What it is |
| --- | --- | --- |
| `site_coordinates` | `latitude`, `longitude` | One row per site, in degrees. West is negative |
| `site_postcodes` | `postcode` | One row per site. Placed on your machine when the postcode table and the centres of neighbourhoods are there |

A row whose position is outside the United Kingdom is left out and counted;
that is also what happens when the two columns are swapped. A site in
Scotland or Northern Ireland still counts as a site.

### Site postcodes that stay on your machine

The [postcode table](postcodes.md#looking-up-postcodes-on-this-machine) holds
the neighbourhood of each postcode but no position. So the analysis places a site
at the centre of its neighbourhood, from a file of neighbourhood centres kept
on your machine. In a town that moves a site by a few hundred metres, and in
the countryside by up to a few kilometres; the result carries a caveat that
says so. Keep the centres once, when a server is built:

```python
from uk_open_data.analyses.access_distance import download_centres

download_centres("neighbourhood")   # about 35,700 centres, about 1 MB
```

What happens to site postcodes follows `postcode_lookup`:

| `postcode_lookup` | Postcode table installed | No postcode table |
| --- | --- | --- |
| `"auto"` (the default) | Placed on your machine. Nothing is sent | Sent to postcodes.io |
| `"offline"` | Placed on your machine. Nothing is sent | The analysis stops |
| `"online"` | Sent to postcodes.io | Sent to postcodes.io |

With a postcode table installed and no centres kept, the analysis stops and names
the function to run. It never falls back to sending postcodes, and it never
fetches the centres while an analysis runs. A server that sets `"offline"` cannot
send a postcode. The result says which happened, under `choices` and
`privacy.sent_to_third_parties`.

The table and the centres cover England and Wales. On your machine, a site
with a Scottish or Northern Irish postcode is not found and is left out and
counted; give its latitude and longitude instead.

The analysis loads the people in every local authority from [Nomis](ons.md) and
the centre of every local authority from the ONS Open Geography Portal. For
each local authority it measures the distance in a straight line from the
centre to your nearest site, to the nearest kilometre. A local authority is
within reach when that distance is `within_km` or less. The list shows the
local authorities beyond reach, with the most people first: the places where
a new site would bring the most people within reach.

**Distance is not travel time.** The package has no road or public transport
times, so the analysis does not turn kilometres into minutes. And it measures from
the centre of a local authority, not from where each person lives, which is
rough for a large rural one.

The `need` option takes the same values as in the second analysis, and the same
kept copies. The default is `"residents"`. The centres can be kept on the
machine too, so the analysis runs with no request at all:

```python
from uk_open_data.analyses.access_distance import download_centres, keep_centres

download_centres()   # fetch once, when a server is built

# or keep centres of your own, for a demonstration
keep_centres(
    [("E09000023", 51.45, -0.02), ("E09000011", 51.47, 0.05)],
    note="invented for a demonstration.",
)

# the same for the centres of neighbourhoods, which place site postcodes
keep_centres(
    [("E01003189", 51.46, -0.01)],
    note="invented for a demonstration.",
    level="neighbourhood",
)
```

| Figure | Meaning |
| --- | --- |
| `sites_supplied` | Sites in the data you gave |
| `sites_located` | Sites placed in the United Kingdom |
| `areas_compared` | Local authorities compared |
| `people_in_need` | People in the area you serve |
| `average_distance_km` | Average distance from the centre of each person's local authority to your nearest site. A place with many people counts for more |
| `share_of_people_within_reach` | Share of people in a local authority whose centre is within `within_km` of a site |
| `people_beyond_reach` | People in a local authority whose centre is farther than that |
| `areas_beyond_reach` | Local authorities whose centre is farther than that |
| `farthest_distance_km` | Distance from the centre of the farthest local authority to a site |

Every distance is from the centre of a local authority, the one the ONS
publishes for it, and every person is counted there. That is coarse. A London
borough is a few kilometres across, so 10 km says something about it. A large
rural local authority can be 50 km across: a site can be inside it and still
be farther than 10 km from its centre, and the place is then listed as far
from a site. The answer, the labels, the headings and a caveat all say that
distance is from the centre. Where the places you work in are large, set
`within_km` higher and read the distances, not only who is within reach.

The charts `people_in_priority_areas` and `distance_in_priority_areas` show
the people and the distance for the places in `priority_areas`. The map has
two layers, `distance` and `need`.

| Table | Rows |
| --- | --- |
| `priority_areas` | The local authorities beyond reach, most people first: people, distance in kilometres. Empty when every place is within reach |
| `by_local_authority` | One per local authority compared, with people and distance in bands. This feeds the map |

| Option | Default | Meaning |
| --- | --- | --- |
| `postcode_lookup` | `"auto"` | How site postcodes are placed. See the table above |
| `need` | `"residents"` | The people to measure distance for |
| `catchment` | England and Wales | A local authority name or code, a list of them, or `"England"`, `"Wales"` or `"England and Wales"` |
| `within_km` | `10` | How many kilometres from a site counts as within reach |
| `top` | `10` | How many places to list, from 1 to 50 |

```python
result = run_analysis(
    "access-distance",
    sites,
    columns={"latitude": "Lat", "longitude": "Long"},
    options={"catchment": "Wales", "within_km": 15},
)

result.table("priority_areas").to_frame()
```

This analysis hides no count, and has no `suppress_below` option. The result
names no site and repeats no postcode or position. Distances are rounded to
the kilometre, but the distances from several local authorities can still
show roughly where a site is.

!!! warning "Confidential addresses"
    Do not share a result if the address of a site is confidential, such as a
    refuge. A check in every result asks this.

!!! note "Before you use the figures"
    Read `result.checks` and `result.caveats`. The figures say how far people
    are from a site. They do not say how far the people you see travel, or
    whether anyone far away needs you.

## Writing an analysis

An analysis is an `AnalysisInfo` and a function that takes an `AnalysisInput` and
returns an `AnalysisResult`. Register it with `register_analysis`. The rules every
analysis keeps:

1. Totals, never rows. Report problems by how many rows they affect.
2. Hide small counts and anything that gives them away. Do not publish two
   breakdowns that can be taken from each other to get a small count. Say in
   the privacy notes that a hidden count is not always small.
3. Give every figure a source.
4. State every choice and name the option that changes it. Give each option
   a `label`, use the label in quotes whenever a sentence points at the
   option, and pass `option=` or `role=` when you raise `AnalysisInputError`.
   Give a table `headings` for any column the package has no heading for.
5. Leave checks for a person to answer.
6. List anything sent off the machine in `privacy.sent_to_third_parties`.
7. Answer the question in `answer`, from figures the result shows and nothing
   else, and name the figures to show first in `key_figures`.
8. Give a share or a rate its `exact` value, from `before_rounding`, when the
   figure is shown, and never when it is hidden. Mark an option `private`
   when the value a person gives holds words from their own data, so the
   code that runs the analysis again leaves it out. `run_analysis` writes
   `result.code` for you.
