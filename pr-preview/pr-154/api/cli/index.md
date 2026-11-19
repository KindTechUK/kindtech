# Command line

The package installs one command under two names, `uk-open-data` and
`kindtech`. It runs [analyses](analyses.md) on a file without writing any Python.

```bash
uv add uk-open-data pandas        # the command needs pandas or polars installed
uv run uk-open-data analysis list
```

## Commands

### `analysis list`

Lists every analysis with the question it answers. Add `--json` for the full
descriptions.

```bash
uk-open-data analysis list
# reach-deprivation: Are we reaching people in the most deprived neighbourhoods?
```

### `analysis describe ANALYSIS_ID`

Shows what an analysis needs: the shapes of data it accepts, the columns, and the
options with their defaults. Add `--json` for the same as JSON.

```bash
uk-open-data analysis describe reach-deprivation
```

### `analysis run ANALYSIS_ID FILE`

Runs an analysis on a `.csv`, `.xlsx` or `.ods` file and prints a plain-text report:
a sentence or two that answer the question, then the figures, the tables, the
checks to make before using them, what the figures cannot say, the choices
made, the working, the figures before rounding, the sources, a privacy
summary and the Python that runs it again. A number has its unit
after it, such as "64.7 km", unless the label beside it already says the unit.

```bash
uk-open-data analysis run reach-deprivation clients.csv \
    --column postcode="Client postcode"
```

| Flag | Meaning |
| --- | --- |
| `--column ROLE=COLUMN` | Which of your columns plays a role. Repeat it for each role |
| `--option NAME=VALUE` | Change an option. Repeat it for each option |
| `--sheet NAME` | The sheet to read from a spreadsheet. The first sheet is read by default |
| `--json` | Print the whole result as JSON instead of a report |
| `--summary` | With `--json`, leave out the rows of long tables such as map data |
| `--output PATH` | Write to a file instead of the screen |
| `--map PATH` | Also draw the map and save it as an `.svg` file |
| `--map-layer LAYER` | What the map is coloured by, for example `people`. The first layer is used by default |

An option value is read as JSON when it is JSON, and as text otherwise:

```bash
uk-open-data analysis run reach-deprivation clients.csv \
    --column postcode="Client postcode" \
    --option suppress_below=10 \
    --option catchment='["Lewisham", "Greenwich"]'
```

When the file, a column or an option cannot be used, the command prints what is
wrong and exits with status 2. The message never repeats a value from your
data, so it is safe to paste into a chat or an issue.

A message names an option by its plain name, as a page shows it, such as
'Area you serve'. When an error is about one option or one column, a last line
says what to type here: "On the command line this is --option
catchment=VALUE." `analysis describe` lists every option with both names.

The outlines for `--map` come from the ONS Open Geography Portal. They
usually come in a few seconds, but at times the service takes a minute or two
to answer, so the command first writes "Fetching the outlines for the map
..." to standard error. The report on standard output is not changed by it. When the outlines
cannot be fetched, the report is still printed or written, no map file is made,
and the command says so in one sentence and exits with status 3. Status 3 means
the report is whole and only the map is missing, so a script can keep the
report. Status 2 means nothing was made.

A run that prints its answer writes one line to the `uk_open_data.runs` logger,
with the analysis, the input mode and the word `cli`. Nothing collects it on
your machine and nothing is sent anywhere. See
[`record_run`](analyses.md#record_runanalysis_id-input_mode-door).

### `postcodes download`

Fetches the postcode table, a few megabytes, so that analyses look postcodes up on
your machine and send none of them out. Run it once. `--force` fetches it
again, and `--url` with `--sha256` fetches a copy you host yourself.

```bash
uk-open-data postcodes download
```

### `postcodes info`

Shows the installed table's edition, size and the credits to show when you
publish something made with it. With no table installed it says so, says first
that an analysis still works, by looking postcodes up with postcodes.io and
saying so in its result, and then says how to get a table. That is not an
error.

### `postcodes build SOURCE TABLE --edition EDITION`

Builds a table from the ONS best-fit postcode lookup (`.csv`, or the `.zip` it
comes in) and prints its SHA-256. This is how a new edition is published; you
do not need it to use the package.

### `connector`

Starts the [connector](connector.md), which offers the analyses to a chat
assistant as tools. It is the same as `python -m uk_open_data.connector` and
takes the same options:

```bash
uk-open-data connector
uk-open-data connector --transport streamable-http --port 8000
```

It needs the `connector` extra, and says so when the extra is not installed:

```bash
uv add "uk-open-data[connector]"
```

Over stdio, the default, the command prints nothing and waits: the assistant
starts it and talks to it. It runs until the assistant, or you, stop it.

## Using it from an assistant

Give an assistant the JSON summary, not your file:

```bash
uk-open-data analysis run reach-deprivation clients.csv \
    --column postcode="Client postcode" --json --summary
```

The summary holds totals only, with small counts hidden. Your rows stay on your
machine.
