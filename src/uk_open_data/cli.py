"""Command line for the package.

    uk-open-data analysis list
    uk-open-data analysis describe reach-deprivation
    uk-open-data analysis run reach-deprivation clients.csv \\
        --column postcode="Client postcode"

The same command is also installed as ``kindtech``.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from collections.abc import Sequence
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import requests

from uk_open_data._frames import read_spreadsheet_rows
from uk_open_data.analyses import (
    AnalysisInfo,
    AnalysisInputError,
    AnalysisResult,
    Figure,
    Privacy,
    Table,
    describe_analysis,
    list_analyses,
    record_run,
    run_analysis,
)
from uk_open_data.analyses.maps import load_map_boundaries, render_map
from uk_open_data.postcodes import (
    PostcodeTableError,
    build_postcode_table,
    download_postcode_table,
    postcode_table_info,
    postcode_table_path,
)
from uk_open_data.postcodes.offline import NO_TABLE, how_to_get_a_table

EXIT_OK = 0
EXIT_INPUT_ERROR = 2
# The report was made and only its map was not: a caller can keep the report.
EXIT_MAP_NOT_DRAWN = 3
SPREADSHEET_SUFFIXES = (".xlsx", ".ods")
KEPT_FIGURES = (
    "An analysis can run without the network when the public figures it uses are "
    "kept on this machine: see the page for the analysis in the documentation."
)
MAP_NOT_DRAWN = (
    "The map was not drawn, because the outlines of its areas could not be "
    "fetched from the ONS Open Geography Portal. The report is complete "
    "without it. Check the connection and try again."
)
# Said before the outlines are asked for, so a wait is not a blank screen.
MAP_BEING_FETCHED = (
    "Fetching the outlines for the map from the ONS Open Geography Portal. "
    "This usually takes a few seconds. At times it takes a minute or two."
)
OUTLINES_LOGGER = "uk_open_data.geo"
# Said when no postcode table is installed, before how to get one, because
# it is what a person running an analysis needs to know.
NO_TABLE_IS_FINE = (
    "That is fine: an analysis then looks postcodes up with postcodes.io, and "
    "says so in its result."
)
WHAT_A_TABLE_IS_FOR = (
    "With a table, postcodes are looked up on this machine and none are sent out."
)
# What follows a number, for each unit that is not said in a label or heading.
UNIT_SUFFIX = {"percent": "%", "per_1000": " per 1,000", "km": " km"}
CONNECTOR = "connector"


class _MapNotDrawnError(Exception):
    """An analysis ran, but the outlines for its map could not be fetched."""

    def __init__(self, report: str) -> None:
        super().__init__(MAP_NOT_DRAWN)
        self.report = report


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line and return its exit status."""
    arguments = sys.argv[1:] if argv is None else list(argv)
    if arguments[:1] == [CONNECTOR]:
        return _start_connector(arguments[1:])
    parser = _build_parser()
    args = parser.parse_args(arguments)
    if not hasattr(args, "handler"):
        parser.print_help()
        return EXIT_INPUT_ERROR
    try:
        text = args.handler(args)
    except _MapNotDrawnError as error:
        _emit(error.report, getattr(args, "output", None))
        sys.stderr.write(MAP_NOT_DRAWN + "\n")
        return EXIT_MAP_NOT_DRAWN
    except AnalysisInputError as error:
        return _fail("\n".join([*error.problems, *_how_to_set(error)]))
    except PostcodeTableError as error:
        return _fail(str(error))
    except KeyError as error:
        return _fail(str(error.args[0]))
    except FileNotFoundError as error:
        return _fail(f"The file '{error.filename}' was not found.")
    except requests.RequestException as error:
        return _fail(_source_problem(error))
    except (OSError, ValueError) as error:
        return _fail(str(error))
    _emit(text, getattr(args, "output", None))
    return EXIT_OK


def _build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for every command."""
    parser = argparse.ArgumentParser(
        prog="uk-open-data",
        description="UK open data for charities: run an analysis on your own data.",
    )
    commands = parser.add_subparsers(title="commands")
    analysis = commands.add_parser("analysis", help="List, describe and run analyses.")
    analysis_commands = analysis.add_subparsers(title="analysis commands")

    listing = analysis_commands.add_parser("list", help="List the analyses.")
    listing.add_argument("--json", action="store_true", help="Print JSON.")
    listing.set_defaults(handler=_handle_list)

    describe = analysis_commands.add_parser("describe", help="Describe one analysis.")
    describe.add_argument("analysis_id", help="The id of the analysis.")
    describe.add_argument("--json", action="store_true", help="Print JSON.")
    describe.set_defaults(handler=_handle_describe)

    run = analysis_commands.add_parser("run", help="Run an analysis on a file.")
    run.add_argument("analysis_id", help="The id of the analysis.")
    run.add_argument("file", type=Path, help="A .csv, .xlsx or .ods file.")
    run.add_argument("--sheet", help="Sheet name, for a spreadsheet file.")
    run.add_argument(
        "--column",
        action="append",
        default=[],
        metavar="ROLE=COLUMN",
        help="Which column plays a role, for example postcode='Client postcode'.",
    )
    run.add_argument(
        "--option",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="Change an option, for example suppress_below=10.",
    )
    run.add_argument("--json", action="store_true", help="Print JSON.")
    run.add_argument(
        "--summary",
        action="store_true",
        help="With --json, leave out the rows of long tables such as map data.",
    )
    run.add_argument("--output", type=Path, help="Write to this file.")
    run.add_argument(
        "--map",
        type=Path,
        metavar="PATH",
        help="Also draw the map and save it to this .svg file.",
    )
    run.add_argument(
        "--map-layer",
        metavar="LAYER",
        help="What the map is coloured by. The first layer is used by default.",
    )
    run.set_defaults(handler=_handle_run)
    _add_postcode_commands(commands)

    # Listed here for the help text. main() hands its arguments on unread.
    commands.add_parser(
        CONNECTOR,
        help="Start the connector, which offers the analyses to a chat assistant.",
    )
    return parser


def _add_postcode_commands(commands: Any) -> None:
    """Add the commands that manage the postcode table on this machine."""
    postcodes = commands.add_parser(
        "postcodes", help="Manage the postcode table kept on this machine."
    )
    postcode_commands = postcodes.add_subparsers(title="postcodes commands")

    download = postcode_commands.add_parser(
        "download", help="Fetch the postcode table so lookups stay on this machine."
    )
    download.add_argument("--url", help="Fetch the table from this https address.")
    download.add_argument("--sha256", help="The SHA-256 the file must have.")
    download.add_argument(
        "--force", action="store_true", help="Fetch again even if one is installed."
    )
    download.set_defaults(handler=_handle_postcodes_download)

    info = postcode_commands.add_parser("info", help="Describe the installed table.")
    info.set_defaults(handler=_handle_postcodes_info)

    build = postcode_commands.add_parser(
        "build", help="Build a table from the ONS best-fit postcode lookup."
    )
    build.add_argument("source", type=Path, help="The ONS lookup, as .csv or .zip.")
    build.add_argument("table", type=Path, help="Where to write the .gz table.")
    build.add_argument("--edition", required=True, help="For example 'May 2026'.")
    build.set_defaults(handler=_handle_postcodes_build)


# --- handlers --------------------------------------------------------------


def _start_connector(arguments: Sequence[str]) -> int:
    """Start the connector, as ``python -m uk_open_data.connector`` does.

    The connector reads its own options, so they are passed on as given. It
    runs until the assistant or the person stops it.
    """
    from uk_open_data.connector.command import main as start

    try:
        start(arguments, prog="uk-open-data connector")
    except ImportError as error:
        return _fail(str(error))
    return EXIT_OK


def _handle_list(args: argparse.Namespace) -> str:
    """List every analysis."""
    analyses = list_analyses()
    if args.json:
        return _to_json([analysis.to_dict() for analysis in analyses])
    return "\n".join(f"{analysis.id}: {analysis.question}" for analysis in analyses)


def _handle_describe(args: argparse.Namespace) -> str:
    """Describe one analysis."""
    info = describe_analysis(args.analysis_id)
    if args.json:
        return _to_json(info.to_dict())
    return _describe_text(info)


def _handle_run(args: argparse.Namespace) -> str:
    """Run an analysis on a file."""
    info = describe_analysis(args.analysis_id)
    rows = _read_rows(args.file, args.sheet)
    columns = dict(_split_pair(pair, "--column") for pair in args.column)
    options = {
        name: _parse_value(value)
        for name, value in (_split_pair(pair, "--option") for pair in args.option)
    }
    result = run_analysis(args.analysis_id, rows, columns=columns, options=options)
    drawn = args.map is None or _write_map(result, args.map_layer, args.map)
    record_run(result.analysis_id, result.input_mode, "cli")
    if args.json:
        text = _to_json(result.to_dict(include_detail=not args.summary))
    else:
        text = _report_text(info, result)
    if not drawn:
        raise _MapNotDrawnError(text)
    return text


def _write_map(result: AnalysisResult, layer: str | None, path: Path) -> bool:
    """Draw a result's map into a file, and say whether it was drawn.

    The service that holds the outlines logs its own errors, which carry its
    web address. They are kept off the screen here, and the caller says what
    happened in one plain sentence instead.

    Fetching can be slow, so the command says first that it is fetching. That
    goes to standard error, which leaves the report as it is.
    """
    sys.stderr.write(MAP_BEING_FETCHED + "\n")
    sys.stderr.flush()
    quiet = logging.NullHandler()
    outlines_log = logging.getLogger(OUTLINES_LOGGER)
    outlines_log.addHandler(quiet)
    try:
        boundaries = load_map_boundaries(result)
    except requests.RequestException:
        return False
    finally:
        outlines_log.removeHandler(quiet)
    if not boundaries["features"]:
        return False
    svg = render_map(result, layer=layer, boundaries=boundaries)
    path.write_text(svg + "\n", encoding="utf-8")
    return True


def _handle_postcodes_download(args: argparse.Namespace) -> str:
    """Fetch and install the postcode table."""
    path = download_postcode_table(url=args.url, sha256=args.sha256, force=args.force)
    return f"The postcode table is installed at {path}\n{_table_text()}"


def _handle_postcodes_info(args: argparse.Namespace) -> str:
    """Describe the installed postcode table, or say that there is none.

    Having no table is not a mistake: postcodes are then looked up online. So
    the command says so and ends as a command that worked.
    """
    if postcode_table_path() is None:
        return (
            f"{NO_TABLE} {NO_TABLE_IS_FINE}\n"
            f"{WHAT_A_TABLE_IS_FOR} {how_to_get_a_table()}"
        )
    return _table_text()


def _handle_postcodes_build(args: argparse.Namespace) -> str:
    """Build a postcode table from the ONS lookup."""
    summary = build_postcode_table(args.source, args.table, args.edition)
    return (
        f"Wrote {args.table}: {summary['records']:,} postcodes in "
        f"{summary['areas']:,} neighbourhoods, {summary['bytes']:,} bytes.\n"
        f"sha256: {summary['sha256']}"
    )


def _table_text() -> str:
    """Describe the installed postcode table in plain text."""
    info = postcode_table_info()
    lines = [
        f"{info['source']}, {info['edition']}",
        f"{info['records']:,} postcodes, {info['coverage']}",
        *info["attribution"],
    ]
    return "\n".join(lines)


# --- input -----------------------------------------------------------------


def _read_rows(path: Path, sheet: str | None) -> list[dict[str, Any]]:
    """Read a CSV or spreadsheet file into row dictionaries."""
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open(newline="", encoding="utf-8-sig") as handle:
            return list(csv.DictReader(handle))
    if suffix in SPREADSHEET_SUFFIXES:
        content = path.read_bytes()
        return read_spreadsheet_rows(content, sheet or _first_sheet(content))
    msg = f"The file must be a .csv, .xlsx or .ods file, not '{suffix or path.name}'."
    raise AnalysisInputError(msg)


def _first_sheet(content: bytes) -> str:
    """Return the name of the first sheet in a workbook."""
    from python_calamine import CalamineWorkbook

    return CalamineWorkbook.from_filelike(BytesIO(content)).sheet_names[0]


def _split_pair(pair: str, flag: str) -> tuple[str, str]:
    """Split ``name=value`` into its two parts."""
    name, separator, value = pair.partition("=")
    if not separator or not name.strip():
        raise AnalysisInputError(f"{flag} needs NAME=VALUE, for example a=b.")
    return name.strip(), value.strip()


def _parse_value(value: str) -> Any:
    """Read an option value as JSON when it is JSON, and as text otherwise."""
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


# --- output ----------------------------------------------------------------


def _to_json(payload: Any) -> str:
    """Format a payload as indented JSON."""
    return json.dumps(payload, indent=2, ensure_ascii=False)


def _emit(text: str, output: Path | None) -> None:
    """Write text to a file, or to standard output."""
    if output is None:
        sys.stdout.write(text + "\n")
        return
    output.write_text(text + "\n", encoding="utf-8")
    sys.stdout.write(f"Written to {output}\n")


def _source_problem(error: requests.RequestException) -> str:
    """Say what went wrong with a data source, without its web address.

    The text of the error holds the whole address, which can hold what was
    asked for, such as a postcode. Only the name of the site is given.
    """
    response = error.response
    address = getattr(error.request, "url", None) or getattr(response, "url", None)
    site = urlsplit(address).hostname if address else None
    where = f" ({site})" if site else ""
    if response is not None:
        return (
            f"A data source this command needs answered with an error{where}, "
            f"status {response.status_code}. Try again in a minute. If it "
            "keeps happening, the source may not hold what was asked for: "
            f"check any table named in the options. {KEPT_FIGURES}"
        )
    return (
        f"A data source this command needs could not be reached{where}. Check "
        f"the connection and try again. {KEPT_FIGURES}"
    )


def _how_to_set(error: AnalysisInputError) -> list[str]:
    """Say how the option or column an input error is about is typed here.

    A message names an option as a page shows it, such as 'Area you serve'.
    The command line takes its code name, so that is added.
    """
    if error.option is not None:
        return [f"On the command line this is --option {error.option}=VALUE."]
    if error.role is not None:
        return [f"On the command line this is --column {error.role}=COLUMN."]
    return []


def _fail(message: str) -> int:
    """Report a problem on standard error and return the error status."""
    sys.stderr.write(message + "\n")
    return EXIT_INPUT_ERROR


def _describe_text(info: AnalysisInfo) -> str:
    """Describe an analysis in plain text."""
    lines = [f"{info.title} ({info.id}, version {info.version})", info.question, ""]
    lines += [info.summary, "", f"Covers: {info.coverage}", "", "Your data can be:"]
    for mode in info.input_modes:
        lines.append(f"  {mode.name}: {mode.description}")
        lines.append(f"    columns needed: {', '.join(mode.roles)}")
    lines += ["", "Columns:"]
    lines += [f"  {role.name}: {role.description}" for role in info.roles]
    lines += ["", "Options:"]
    for option in info.options:
        lines.append(
            f"  {option.label or option.name} (--option {option.name}=VALUE, "
            f"default {json.dumps(option.default)}): {option.description}"
        )
        lines += [
            f"    {json.dumps(choice.value)}: {choice.label}"
            for choice in option.choices
        ]
    return "\n".join(lines)


def _report_text(info: AnalysisInfo, result: AnalysisResult) -> str:
    """Lay out a result as a plain-text report."""
    lines = [info.title, info.question, "", result.answer, "", "Figures"]
    lines += [
        f"  {figure.label}: {_figure_value(figure.value, _unit(figure), figure.note)}"
        for figure in result.figures
    ]
    for table in result.tables:
        if not table.detail:
            lines += ["", table.title, *_table_lines(table)]
    lines += _section(
        "Check before you use these figures",
        [f"{check.question} {check.why}" for check in result.checks],
    )
    lines += _section("What these figures cannot say", list(result.caveats))
    lines += _section("Warnings", list(result.warnings))
    lines += _section(
        "Choices made for you",
        [
            f"{choice.label}: {_plain_value(choice.value)}. {choice.reason}"
            + (f" Change it with --option {choice.option}=..." if choice.option else "")
            for choice in result.choices
        ],
    )
    lines += _section(
        "Working", [f"{step.title}. {step.detail}" for step in result.working]
    )
    lines += _section(
        "Sources",
        [
            # An edition that names a kept copy ends in a full stop already.
            f"{source.name}, {source.publisher}, {source.edition.rstrip('.')}. "
            f"{source.licence}. {source.url}"
            for source in result.sources
        ],
    )
    privacy = result.privacy
    lines += _section(
        "Privacy",
        [
            *_hidden_counts(privacy),
            *(privacy.sent_to_third_parties or ("Nothing left this machine.",)),
            *privacy.notes,
        ],
    )
    lines += _section(
        "Figures before rounding",
        [
            f"{figure.label}: {_exact(figure.exact)}"
            for figure in result.figures
            if figure.exact is not None
        ],
    )
    if result.code:
        # Not set in from the margin, so that it runs as it is copied.
        lines += ["", "To run it again in Python", *result.code.splitlines()]
    return "\n".join(lines)


def _exact(value: float) -> str:
    """Write a figure as it was before rounding, to six decimal places."""
    return f"{value:,.6f}".rstrip("0").rstrip(".")


def _hidden_counts(privacy: Privacy) -> list[str]:
    """Say which counts were hidden, or nothing when the analysis hides none."""
    if privacy.suppress_below is None:
        return []
    return [
        f"Counts from 1 to {privacy.suppress_below - 1} are hidden. "
        f"{privacy.cells_suppressed} cells or figures were hidden."
    ]


def _section(title: str, items: list[str]) -> list[str]:
    """Return a titled list, or nothing when the list is empty."""
    if not items:
        return []
    return ["", title, *(f"  - {item}" for item in items)]


def _unit(figure: Figure) -> str:
    """The unit to write after a figure, or none when its label says it.

    "Provision for each 1,000 residents: 0.11" needs no "per 1,000" after it.
    """
    said_in_label = figure.unit == "per_1000" and "1,000" in figure.label
    return "" if said_in_label else figure.unit


def _figure_value(value: Any, unit: str, note: str) -> str:
    """Format a figure's value with its unit."""
    if value is None:
        return f"not shown ({note.rstrip('.').lower()})" if note else "not shown"
    return f"{value:,}{UNIT_SUFFIX.get(unit, '')}"


def _plain_value(value: Any) -> str:
    """Format a choice's value for a sentence."""
    if isinstance(value, list | tuple):
        return ", ".join(str(item) for item in value)
    return str(value)


def _table_lines(table: Table) -> list[str]:
    """Lay out a table in aligned columns, without the suppressed flag.

    Each column has its plain heading, and each number its unit.
    """
    columns = [column for column in table.columns if column != "suppressed"]
    cells = [
        [
            _cell(row.get(column), bool(row.get("suppressed")), table.units.get(column))
            for column in columns
        ]
        for row in table.rows
    ]
    headings = [table.headings[column] for column in columns]
    widths = [
        max(len(heading), *(len(row[index]) for row in cells))
        for index, heading in enumerate(headings)
    ]
    return [
        "  "
        + "  ".join(
            text.ljust(width) for text, width in zip(line, widths, strict=True)
        ).rstrip()
        for line in [headings, *cells]
    ]


def _cell(value: Any, suppressed: bool, unit: str | None = None) -> str:
    """Format one table cell, with its unit when it is a number that has one."""
    if value is None:
        return "hidden" if suppressed else "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int | float):
        return f"{value:,}{UNIT_SUFFIX.get(unit or '', '')}"
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
