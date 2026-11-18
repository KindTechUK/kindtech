"""Command line for the package.

    uk-open-data lens list
    uk-open-data lens describe reach-deprivation
    uk-open-data lens run reach-deprivation clients.csv \\
        --column postcode="Client postcode"

The same command is also installed as ``kindtech``.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections.abc import Sequence
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import requests

from kindtech._frames import read_spreadsheet_rows
from kindtech.lenses import (
    LensInfo,
    LensInputError,
    LensResult,
    Privacy,
    Table,
    describe_lens,
    list_lenses,
    run_lens,
)
from kindtech.lenses.maps import render_map
from kindtech.postcodes import (
    PostcodeTableError,
    build_postcode_table,
    download_postcode_table,
    postcode_table_info,
)

EXIT_OK = 0
EXIT_INPUT_ERROR = 2
SPREADSHEET_SUFFIXES = (".xlsx", ".ods")


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line and return its exit status."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "handler"):
        parser.print_help()
        return EXIT_INPUT_ERROR
    try:
        text = args.handler(args)
    except LensInputError as error:
        return _fail("\n".join(error.problems))
    except PostcodeTableError as error:
        return _fail(str(error))
    except KeyError as error:
        return _fail(str(error.args[0]))
    except FileNotFoundError as error:
        return _fail(f"The file '{error.filename}' was not found.")
    except requests.RequestException as error:
        return _fail(_unreachable(error))
    except (OSError, ValueError) as error:
        return _fail(str(error))
    _emit(text, getattr(args, "output", None))
    return EXIT_OK


def _build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for every command."""
    parser = argparse.ArgumentParser(
        prog="uk-open-data",
        description="UK open data for charities: run a lens on your own data.",
    )
    commands = parser.add_subparsers(title="commands")
    lens = commands.add_parser("lens", help="List, describe and run lenses.")
    lens_commands = lens.add_subparsers(title="lens commands")

    listing = lens_commands.add_parser("list", help="List the lenses.")
    listing.add_argument("--json", action="store_true", help="Print JSON.")
    listing.set_defaults(handler=_handle_list)

    describe = lens_commands.add_parser("describe", help="Describe one lens.")
    describe.add_argument("lens_id", help="The id of the lens.")
    describe.add_argument("--json", action="store_true", help="Print JSON.")
    describe.set_defaults(handler=_handle_describe)

    run = lens_commands.add_parser("run", help="Run a lens on a file.")
    run.add_argument("lens_id", help="The id of the lens.")
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


def _handle_list(args: argparse.Namespace) -> str:
    """List every lens."""
    lenses = list_lenses()
    if args.json:
        return _to_json([lens.to_dict() for lens in lenses])
    return "\n".join(f"{lens.id}: {lens.question}" for lens in lenses)


def _handle_describe(args: argparse.Namespace) -> str:
    """Describe one lens."""
    info = describe_lens(args.lens_id)
    if args.json:
        return _to_json(info.to_dict())
    return _describe_text(info)


def _handle_run(args: argparse.Namespace) -> str:
    """Run a lens on a file."""
    info = describe_lens(args.lens_id)
    rows = _read_rows(args.file, args.sheet)
    columns = dict(_split_pair(pair, "--column") for pair in args.column)
    options = {
        name: _parse_value(value)
        for name, value in (_split_pair(pair, "--option") for pair in args.option)
    }
    result = run_lens(args.lens_id, rows, columns=columns, options=options)
    if args.map is not None:
        svg = render_map(result, layer=args.map_layer)
        args.map.write_text(svg + "\n", encoding="utf-8")
    if args.json:
        return _to_json(result.to_dict(include_detail=not args.summary))
    return _report_text(info, result)


def _handle_postcodes_download(args: argparse.Namespace) -> str:
    """Fetch and install the postcode table."""
    path = download_postcode_table(url=args.url, sha256=args.sha256, force=args.force)
    return f"The postcode table is installed at {path}\n{_table_text()}"


def _handle_postcodes_info(args: argparse.Namespace) -> str:
    """Describe the installed postcode table."""
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
    raise LensInputError(msg)


def _first_sheet(content: bytes) -> str:
    """Return the name of the first sheet in a workbook."""
    from python_calamine import CalamineWorkbook

    return CalamineWorkbook.from_filelike(BytesIO(content)).sheet_names[0]


def _split_pair(pair: str, flag: str) -> tuple[str, str]:
    """Split ``name=value`` into its two parts."""
    name, separator, value = pair.partition("=")
    if not separator or not name.strip():
        raise LensInputError(f"{flag} needs NAME=VALUE, for example a=b.")
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


def _unreachable(error: requests.RequestException) -> str:
    """Say that a data source could not be reached, without its web address.

    The text of the error holds the whole address, which can hold what was
    asked for, such as a postcode. Only the name of the site is given.
    """
    address = getattr(error.request, "url", None)
    site = urlsplit(address).hostname if address else None
    where = f" ({site})" if site else ""
    return (
        f"A data source this command needs could not be reached{where}. Check "
        "the connection and try again. A lens can run without the network "
        "when the public figures it uses are kept on this machine: see the "
        "page for the lens in the documentation."
    )


def _fail(message: str) -> int:
    """Report a problem on standard error and return the error status."""
    sys.stderr.write(message + "\n")
    return EXIT_INPUT_ERROR


def _describe_text(info: LensInfo) -> str:
    """Describe a lens in plain text."""
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
            f"  {option.name} (default {json.dumps(option.default)}): "
            f"{option.description}"
        )
        lines += [
            f"    {json.dumps(choice.value)}: {choice.label}"
            for choice in option.choices
        ]
    return "\n".join(lines)


def _report_text(info: LensInfo, result: LensResult) -> str:
    """Lay out a result as a plain-text report."""
    lines = [info.title, info.question, "", "Figures"]
    lines += [
        f"  {figure.label}: {_figure_value(figure.value, figure.unit, figure.note)}"
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
            f"{source.name}, {source.publisher}, {source.edition}. "
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
    return "\n".join(lines)


def _hidden_counts(privacy: Privacy) -> list[str]:
    """Say which counts were hidden, or nothing when the lens hides none."""
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


def _figure_value(value: Any, unit: str, note: str) -> str:
    """Format a figure's value with its unit."""
    if value is None:
        return f"not shown ({note.rstrip('.').lower()})" if note else "not shown"
    suffix = {"percent": "%", "per_1000": " per 1,000"}.get(unit, "")
    return f"{value:,}{suffix}"


def _plain_value(value: Any) -> str:
    """Format a choice's value for a sentence."""
    if isinstance(value, list | tuple):
        return ", ".join(str(item) for item in value)
    return str(value)


def _table_lines(table: Table) -> list[str]:
    """Lay out a table in aligned columns, without the suppressed flag."""
    columns = [column for column in table.columns if column != "suppressed"]
    cells = [
        [_cell(row.get(column), bool(row.get("suppressed"))) for column in columns]
        for row in table.rows
    ]
    widths = [
        max(len(column), *(len(row[index]) for row in cells))
        for index, column in enumerate(columns)
    ]
    return [
        "  "
        + "  ".join(text.ljust(width) for text, width in zip(line, widths, strict=True))
        for line in [columns, *cells]
    ]


def _cell(value: Any, suppressed: bool) -> str:
    """Format one table cell."""
    if value is None:
        return "hidden" if suppressed else "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int | float):
        return f"{value:,}"
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
