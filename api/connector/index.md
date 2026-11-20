# Connector for chat assistants

The `uk_open_data.connector` module offers the analyses and open data to a chat
assistant, such as Claude or ChatGPT, over the
[Model Context Protocol](https://modelcontextprotocol.io/). A charity worker
asks a question in their own words; the assistant calls a tool; figures come
back with their sources.

Every tool is read-only, and every tool keeps one rule: **the assistant sees
totals, never rows**.

## Start it

The server needs the `connector` extra:

```bash
uv add "uk-open-data[connector]"
uv run uk-open-data connector
```

With pip it is `pip install "uk-open-data[connector]"`, then
`uk-open-data connector`. Started without the extra, the command ends with one
sentence that says how to install it.

`python -m uk_open_data.connector` starts the same thing and takes the same
options. That runs over stdio, which is how a desktop assistant starts a local
connector. For Claude Desktop or Claude Code, add this to the MCP
configuration, with the path to your checkout:

```json
{
  "mcpServers": {
    "kindtech": {
      "command": "uv",
      "args": [
        "run", "--directory", "/path/to/uk-open-data", "--extra", "connector",
        "uk-open-data", "connector"
      ]
    }
  }
}
```

To host it, run the same server over Streamable HTTP. The address to give an
assistant then ends in `/mcp`:

```bash
uv run uk-open-data connector --transport streamable-http --port 8000
```

## Tools

| Tool | What it does |
| --- | --- |
| `find_analysis` | Finds the analysis that answers a question, and says what data it needs. |
| `describe_place` | Describes a place in England from the Indices of Deprivation 2025. |
| `run_analysis_on_counts` | Runs an analysis on counts that are already totalled by area or by group. |

### `find_analysis`

`query` is the question in the person's words, or left out to list every analysis.
The answer holds each analysis description, best match first.

An analysis that takes no totals cannot run in a chat. `needs_rows` in the answer
names the listed analyses of that kind and says where they can run. The access
and distance analysis is one: it needs a row per site that says where the site
is.

### `describe_place`

`place` is a local authority name or code, a 2021 LSOA code or a postcode
district such as `SE13`.

```python
from uk_open_data.connector import describe_place

answer = describe_place("Lewisham")
answer["status"]            # "found"
answer["place"]["code"]     # "E09000023"
answer["figures"]           # neighbourhoods, residents, shares in the most deprived areas
answer["tables"]            # by deprivation decile, and by type of deprivation
answer["sources"]           # publisher, edition, licence and link
```

`status` is `found`, `choose` (several places match, listed in `matches`),
`not_found`, `not_covered` (outside England), `not_accepted` (a full postcode
or a street address) or `unavailable` (a data source could not be reached).

A full postcode is not accepted, even a venue's, because nothing tells a
venue's postcode from a person's home. It is not looked up, sent anywhere or
repeated, and the message asks for the first half of the postcode or the name
of the place. For one neighbourhood, pass its 2021 LSOA code.

A street address is not accepted either: a postcode inside other words, or a
number beside a word such as "Road", "Flat" or "House". The tool describes
areas, not buildings, and an address can be a person's home. The message says
an address should not be sent and asks for the council area or the first half
of the postcode.

The tool describes places in England only, because the deprivation index it
reads is England's. A council, code or postcode in Wales gives `not_covered`
with a message that says the place is in Wales and that the analyses which
cover England and Wales still work for it.

The deprivation index is read from a copy kept on this machine when there is
one, and the source in the answer then says so. When you host the connector,
keep it when the image is built (`uk_open_data.imd.download_imd`), so the first
call does not wait on a download. A copy kept with `uk_open_data.imd.keep_imd`
that leaves out the types of deprivation gives the same answer without that
table, and says so in `warnings`. A copy that cannot be read gives the status
`unavailable`.

A postcode district is looked up in the
[postcode table on this machine](postcodes.md) when one is installed, so it is
not sent anywhere. Without a table it is sent to postcodes.io. Either way the
answer says which happened under `privacy`. When you host the connector,
install the table when the image is built (`uk-open-data postcodes download`),
so a district stays on your server.

### `run_analysis_on_counts`

`analysis_id` names the analysis. `counts` holds one object per area or group, keyed by
the role names of an input mode the analysis marks as `aggregated`. `options`
changes the analysis options.

| Analysis | One row of `counts` | Options it needs |
| --- | --- | --- |
| `reach-deprivation` | `{"lsoa_code": "E01003189", "count": 12}` | none |
| `need-reach` | `{"local_authority": "Lewisham", "count": 120}` | none |
| `who-we-miss` | `{"group": "Black Caribbean", "count": 40}` | `catchment`, the area you serve |
| `provision-gap` | `{"local_authority": "Lewisham", "volume": 1200}` | none |

A `volume` is what the charity provides in that place, such as sessions, places
or hours. The provision gap analysis hides no small figure, because a volume is
not a count of people, and its result says so.

The answer holds the analysis result without the rows of its detail tables, so an
assistant is not handed a row per neighbourhood. Such a table comes back with
its columns and no rows, and `rows_left_out` in the answer names those tables
and says they are not empty, so that an assistant does not report "nothing
found". Where the result's map is drawn from one of them, the note says the
map cannot be drawn from the answer. Rows about individual people,
such as one postcode per person, are refused, and so is one row per site.

The result holds `answer`, one or two sentences that answer the analysis's
question, and `key_figures`, the ids of the figures behind them. Both come
through as the analysis wrote them. Where a result has an answer, `open_with`
tells the assistant to begin its reply with that sentence in its exact words,
so a person reads the same words in a chat as on the Kindtech Evidence page
and at the command line. The sentence passes the same check as the rest of the
result: it is withheld if it repeats a value from the rows.

The result also holds what a person needs to check it. A share or a rate has
`exact`, its value before rounding, and the result has `code`, the Python that
runs the analysis again with the same settings. Both are described under
[the working](analyses.md) and come through as the analysis wrote them. The
code leaves the names of the person's columns to be filled in, and a setting
that holds their own labels, such as `groups` for `who-we-miss`, is written as
`{}`, so it passes the same check as the rest of the result. The server's
instructions and the tool's description tell an assistant to quote figures as
they are shown, rounded, and to give an exact value or the code only when the
person asks how a figure was worked out or asks for the code.

A count or volume given as text that is nothing but a number, such as
`"1200"` or `"1,200"`, is read as a number, because assistants often send one
that way. This applies to the roles an analysis marks `amount` in its description
and to no other. Any other text there is left for the analysis, which says how
many rows to correct.

```python
from uk_open_data.connector import run_analysis_on_counts

answer = run_analysis_on_counts(
    "need-reach",
    [
        {"local_authority": "Lewisham", "count": 120},
        {"local_authority": "Greenwich", "count": 40},
    ],
    options={"catchment": ["Lewisham", "Greenwich", "Bexley", "Bromley"]},
)
answer["status"]              # "ok"
answer["result"]["answer"]    # the sentence to open with
answer["result"]["figures"]   # headline figures, small counts hidden
answer["result"]["tables"]    # the high-need places, lowest reach first
```

`catchment` is the area you serve: every place the charity serves, whether or
not it reaches anyone there yet. Without it, need against reach compares only
the local authorities that hold at least 5% of the people in the rows, so it
cannot show a place the charity does not reach yet, and its result says so in
a warning. With one place there is nothing to compare, and the answer says
that too. An assistant should ask the person for the area they serve when the
question is about where they are missing.

`status` is `ok`, `would_hide_counts`, `input_problem` (`problems` lists what
to fix, for example an option the analysis needs), `needs_rows`, `unknown_analysis` or
`unavailable` (a data source the analysis needs could not be reached).

A problem sentence is written for the person and names an option by the label
they read, in quotes: "Change 'Area you serve' to include them." An assistant
passes options by their code names, so when the analysis says which one a
problem is about, the answer also has `option` (for example `catchment`) or
`role` (the column, for example `count`). `find_analysis` lists each option's
label beside its name.

`needs_rows` is the answer for an analysis that takes no totals, such as the access
and distance analysis, whatever rows are passed. Its message says the analysis cannot
run in a chat, because it needs a row for each site and this tool takes totals
only, and that it runs on the Kindtech Evidence page or with the command line tool.

#### The map

An analysis result describes a map, and the table that feeds it is one of the
tables left out of an answer. So the server draws the map itself, one picture
for each thing the map can be coloured by, and sends the pictures beside the
answer: in the tool result's `_meta`, under `kindtech/map`, which is for the
app the person is using and is not part of what a model is given. The tool
points to a small page, `ui://kindtech/analysis-map.html`, that shows them. An
assistant app that supports [MCP Apps](https://github.com/modelcontextprotocol/ext-apps)
shows that page with the answer, so the person sees the map in the chat. An
app that does not shows the answer alone, as before.

The answer itself gains `map`, with `drawn` and a `note` for the assistant: a
picture was drawn for the person and the assistant is not given it, or why
none was drawn. An analysis with no map has no `map` in its answer, and neither has
a result that was held back. The plain Python function `run_analysis_on_counts`
draws nothing; only the server does.

The outlines are fetched from the ONS Open Geography Portal each time a map is
drawn. What is sent is public area codes only: those of the areas on the map
and of the local authorities near it, which are drawn pale around it. When
the outlines cannot be fetched the figures come back as usual and the note
says no map was drawn.

The figures do not wait long for a picture. A map in a chat is drawn from the
quick outlines, simplified to 200 metres, where the page and the command line
ask for finer ones. Outlines usually come in a few seconds, but at times the
boundary service has taken a minute or more for one map, and it is not known
why. So the server waits 15 seconds for the outlines and then sends the answer
without a map, with a note that says so and suggests running the analysis
again in a few minutes. The fetch is left to finish. The outlines of every
local authority are kept in memory once fetched, for as long as the server
runs.

When you host the connector, keep the outlines on your server and pass a
function that reads them, so that no run waits on another service:

```python
from uk_open_data.connector import build_server

server = build_server(map_boundaries=outlines_kept_here)  # takes an analysis result
```

Pictures of more than about 1.5 MB together are not sent: the first layers
that fit are, and when not even one fits the note says so.

#### When counts would be hidden

An analysis hides a count from 1 to 4, and where it hides one count in a table it
hides a second, so the first cannot be worked out from the total. In a chat
that second count can be a number the person has just typed, which reads as a
fault. So when the answer would hide any figure or table row, the first call
holds it back and says so:

```python
answer = run_analysis_on_counts(
    "reach-deprivation",
    [
        {"lsoa_code": "E01003189", "count": 3},
        {"lsoa_code": "E01003190", "count": 30},
    ],
)
answer["status"]       # "would_hide_counts"
answer["would_hide"]   # {"figures_and_rows": 3, "counts_below": 5}
answer["choices"]      # combine the small counts first, or run as it is
```

The answer holds no figure from the run and nothing from the rows. The person
then chooses. They can add each small count to a neighbouring area's count, or
to a broader group's, and send the rows again, saying with the figures which
rows were combined. Or they can take the result with those counts hidden:

```python
answer = run_analysis_on_counts(analysis_id, counts, hidden_counts="accept")
answer["status"]       # "ok"
```

An analysis that hides nothing, such as the provision gap analysis, never asks.

When you host the connector, keep the public figures three of the analyses
compare with on the server when the image is built, so a run does not wait on
Nomis: `uk_open_data.analyses.need_reach.download_need_figures` for the need against
reach analysis, the same function called with `"residents"` for the provision gap
analysis, which sets provision against everyone who lives in a place unless told
otherwise, and `uk_open_data.analyses.who_we_miss.download_residents` for the who we
are missing analysis.

The `"residents"` figures serve two analyses. Need against reach uses them too,
to shade its map by people in need for each 1,000 residents. When the need
figures are kept and the residents are not, it does not fetch them: the map is
shaded by the count and the result says so in its choices. Keep both and the
map goes by the rate.

## The privacy rule

- No tool accepts rows about people. `run_analysis_on_counts` takes only input
  modes an analysis marks as `aggregated`.
- Every result passes through `ensure_totals_only` before it is returned. If a
  value from the input, such as a postcode or an area code sent with a count,
  appears anywhere in a result, the result is withheld.
- The one exception is a role an analysis marks as `reported`: a column that holds
  names the result uses too. For local authorities every value is a public
  name. For a column that also holds a person's own words, such as their
  ethnic group, the role lists the exact names the result uses
  (`reported_values`, for example "White"), and only those may come back: a
  charity's own label, such as "Black Caribbean", is still withheld if a
  result repeats it. Small counts are still hidden, and a value with the
  shape of a postcode is always withheld.
- Error messages name the argument that was wrong and never quote its value.
- The log follows the same rule. When a data source cannot be reached, the log
  holds the kind of error and not the web address. The code that asks the
  boundary service logs the address it asked, which holds the area codes of
  the map, so the connector's command replaces each warning or error from
  that code with one sentence that says a line was left out. A program that
  builds the server itself and lets it fetch outlines calls
  `uk_open_data.connector.maps.keep_addresses_out_of_the_log()` once to do
  the same. When a tool crashes, the
  assistant is told only that the tool failed, and the log says which tool
  stopped, with what kind of error and where in the code, and leaves out the
  error's own text, which can quote a value from the rows.
- An answer given through `run_analysis_on_counts` is counted with one line on
  the `uk_open_data.runs` logger, written by
  [`record_run`](analyses.md#record_runanalysis_id-input_mode-door):
  `run analysis=need-reach mode=area_counts door=chat`. It holds the analysis,
  the input mode and the word "chat", each from a fixed list, and nothing from
  the rows or the options. A run that was held back, refused or withheld is not
  counted. Nothing is sent anywhere: on your own machine the line goes to
  stderr with the rest of the log, at any `--log-level`, and a host counts the
  lines in the logs it keeps.
- `tests/test_connector_privacy.py` calls every tool the way an assistant does
  and fails if a row-level value reaches a result. A new tool must add a case
  there.
