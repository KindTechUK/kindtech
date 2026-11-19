# Connector for chat assistants

The `uk_open_data.connector` module offers the lenses and open data to a chat
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
uv run python -m uk_open_data.connector
```

That runs over stdio, which is how a desktop assistant starts a local
connector. For Claude Desktop or Claude Code, add this to the MCP
configuration, with the path to your checkout:

```json
{
  "mcpServers": {
    "kindtech": {
      "command": "uv",
      "args": [
        "run", "--directory", "/path/to/uk-open-data", "--extra", "connector",
        "python", "-m", "uk_open_data.connector"
      ]
    }
  }
}
```

To host it, run the same server over Streamable HTTP. The address to give an
assistant then ends in `/mcp`:

```bash
uv run python -m uk_open_data.connector --transport streamable-http --port 8000
```

## Tools

| Tool | What it does |
| --- | --- |
| `find_lens` | Finds the lens that answers a question, and says what data it needs. |
| `describe_place` | Describes a place in England from the Indices of Deprivation 2025. |
| `run_lens_on_counts` | Runs a lens on counts that are already totalled by area or by group. |

### `find_lens`

`query` is the question in the person's words, or left out to list every lens.
The answer holds each lens description, best match first.

### `describe_place`

`place` is a local authority name or code, a 2021 LSOA code, a postcode
district such as `SE13`, or the postcode of a venue or office.

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
`not_found`, `not_covered` (outside England) or `unavailable` (a data source
could not be reached).

The tool describes places in England only, because the deprivation index it
reads is England's. A council, code or postcode in Wales gives `not_covered`
with a message that says the place is in Wales and that the lenses which
cover England and Wales still work for it.

The deprivation index is read from a copy kept on this machine when there is
one, and the source in the answer then says so. When you host the connector,
keep it when the image is built (`uk_open_data.imd.download_imd`), so the first
call does not wait on a download. A copy kept with `uk_open_data.imd.keep_imd`
that leaves out the types of deprivation gives the same answer without that
table, and says so in `warnings`. A copy that cannot be read gives the status
`unavailable`.

A postcode or postcode district is looked up in the
[postcode table on this machine](postcodes.md) when one is installed, so it is
not sent anywhere. Without a table it is sent to postcodes.io. Either way the
answer says which happened under `privacy`, and the postcode is never repeated
in the answer. When you host the connector, install the table when the image
is built (`uk-open-data postcodes download`), so venue postcodes stay on your
server.

### `run_lens_on_counts`

`lens_id` names the lens. `counts` holds one object per area or group, keyed by
the role names of an input mode the lens marks as `aggregated`. `options`
changes the lens options.

| Lens | One row of `counts` | Options it needs |
| --- | --- | --- |
| `reach-deprivation` | `{"lsoa_code": "E01003189", "count": 12}` | none |
| `need-reach` | `{"local_authority": "Lewisham", "count": 120}` | none |
| `who-we-miss` | `{"group": "Black Caribbean", "count": 40}` | `catchment`, the area the charity serves |
| `provision-gap` | `{"local_authority": "Lewisham", "volume": 1200}` | none |

A `volume` is what the charity provides in that place, such as sessions, places
or hours. The provision gap lens hides no small figure, because a volume is
not a count of people, and its result says so.

The answer holds the lens result without the rows of its detail tables, so an
assistant is not handed a row per neighbourhood. Such a table comes back with
its columns and no rows, and `rows_left_out` in the answer names those tables
and says they are not empty, so that an assistant does not report "nothing
found". Where the result's map is drawn from one of them, the note says the
map cannot be drawn from the answer. Rows about individual people,
such as one postcode per person, are refused, and so is one row per site.

A count or volume given as text that is nothing but a number, such as
`"1200"` or `"1,200"`, is read as a number, because assistants often send one
that way. This applies to the roles a lens marks `amount` in its description
and to no other. Any other text there is left for the lens, which says how
many rows to correct.

```python
from uk_open_data.connector import run_lens_on_counts

answer = run_lens_on_counts(
    "need-reach",
    [
        {"local_authority": "Lewisham", "count": 120},
        {"local_authority": "Greenwich", "count": 40},
    ],
)
answer["status"]              # "ok"
answer["result"]["figures"]   # headline figures, small counts hidden
answer["result"]["tables"]    # the places to look at first
```

`status` is `ok`, `input_problem` (`problems` lists what to fix, for example
an option the lens needs), `unknown_lens` or `unavailable` (a data source the
lens needs could not be reached).

When you host the connector, keep the public figures three of the lenses
compare with on the server when the image is built, so a run does not wait on
Nomis: `uk_open_data.lenses.need_reach.download_need_figures` for the need against
reach lens, the same function called with `"residents"` for the provision gap
lens, which sets provision against everyone who lives in a place unless told
otherwise, and `uk_open_data.lenses.who_we_miss.download_residents` for the who we
are missing lens.

## The privacy rule

- No tool accepts rows about people. `run_lens_on_counts` takes only input
  modes a lens marks as `aggregated`.
- Every result passes through `ensure_totals_only` before it is returned. If a
  value from the input, such as a postcode or an area code sent with a count,
  appears anywhere in a result, the result is withheld.
- The one exception is a role a lens marks as `reported`: a column that holds
  names the result uses too. For local authorities every value is a public
  name. For a column that also holds a person's own words, such as their
  ethnic group, the role lists the exact names the result uses
  (`reported_values`, for example "White"), and only those may come back: a
  charity's own label, such as "Black Caribbean", is still withheld if a
  result repeats it. Small counts are still hidden, and a value with the
  shape of a postcode is always withheld.
- Error messages name the argument that was wrong and never quote its value.
- The log follows the same rule. When a data source cannot be reached, the log
  holds the kind of error and not the web address. When a tool crashes, the
  assistant is told only that the tool failed, and the log says which tool
  stopped, with what kind of error and where in the code, and leaves out the
  error's own text, which can quote a value from the rows.
- `tests/test_connector_privacy.py` calls every tool the way an assistant does
  and fails if a row-level value reaches a result. A new tool must add a case
  there.
