# Connector for chat assistants

The `kindtech.connector` module offers the lenses and open data to a chat
assistant, such as Claude or ChatGPT, over the
[Model Context Protocol](https://modelcontextprotocol.io/). A charity worker
asks a question in their own words; the assistant calls a tool; figures come
back with their sources.

Every tool is read-only, and every tool keeps one rule: **the assistant sees
totals, never rows**.

## Start it

The server needs the `connector` extra:

```bash
uv add "kindtech[connector]"
uv run python -m kindtech.connector
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
        "run", "--directory", "/path/to/kindtech", "--extra", "connector",
        "python", "-m", "kindtech.connector"
      ]
    }
  }
}
```

To host it, run the same server over Streamable HTTP. The address to give an
assistant then ends in `/mcp`:

```bash
uv run python -m kindtech.connector --transport streamable-http --port 8000
```

## Tools

| Tool | What it does |
| --- | --- |
| `find_lens` | Finds the lens that answers a question, and says what data it needs. |
| `describe_place` | Describes a place in England from the Indices of Deprivation 2025. |
| `run_lens_on_counts` | Runs a lens on counts that are already totalled by area. |

### `find_lens`

`query` is the question in the person's words, or left out to list every lens.
The answer holds each lens description, best match first.

### `describe_place`

`place` is a local authority name or code, a 2021 LSOA code, a postcode
district such as `SE13`, or the postcode of a venue or office.

```python
from kindtech.connector import describe_place

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

A postcode or postcode district is looked up in the
[postcode table on this machine](postcodes.md) when one is installed, so it is
not sent anywhere. Without a table it is sent to postcodes.io. Either way the
answer says which happened under `privacy`, and the postcode is never repeated
in the answer. When you host the connector, install the table when the image
is built (`uk-open-data postcodes download`), so venue postcodes stay on your
server.

### `run_lens_on_counts`

`lens_id` names the lens. `counts` holds one object per area, keyed by the role
names of an input mode the lens marks as `aggregated`, for example
`{"lsoa_code": "E01003189", "count": 12}`. `options` changes the lens options.

The answer holds the lens result without the rows of its detail tables, so an
assistant is not handed a row per neighbourhood. Rows about individual people,
such as one postcode per person, are refused.

## The privacy rule

- No tool accepts rows about people. `run_lens_on_counts` takes only input
  modes a lens marks as `aggregated`.
- Every result passes through `ensure_totals_only` before it is returned. If a
  value from the input, such as a postcode or an area code sent with a count,
  appears anywhere in a result, the result is withheld.
- Error messages name the argument that was wrong and never quote its value.
- `tests/test_connector_privacy.py` calls every tool the way an assistant does
  and fails if a row-level value reaches a result. A new tool must add a case
  there.
