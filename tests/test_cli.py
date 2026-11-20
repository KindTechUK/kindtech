"""
Unit tests for the command line.

The deprivation index is replaced with a small invented table, and the files
are written to a temporary folder, so the tests are isolated and repeatable.
"""

import ast
import json
import logging
import unittest.mock as mock

import pandas as pd
import pytest
import requests

from uk_open_data.cli import (
    EXIT_INPUT_ERROR,
    EXIT_MAP_NOT_DRAWN,
    EXIT_OK,
    MAP_BEING_FETCHED,
    MAP_NOT_DRAWN,
    main,
)

ANALYSIS_ID = "reach-deprivation"


def _index() -> pd.DataFrame:
    """An invented index: one authority, one area of 1,000 per decile."""
    rows = [
        {
            "geography_code": f"E010{decile:05d}",
            "geography_name": f"Lewisham {decile:03d}A",
            "lad_code": "E09000023",
            "lad_name": "Lewisham",
            "imd_decile": decile,
            "population": 1000,
        }
        for decile in range(1, 11)
    ]
    return pd.DataFrame(rows)


@pytest.fixture
def counts_file(tmp_path):
    """A CSV of counts by neighbourhood, with the user's own column names."""
    path = tmp_path / "counts.csv"
    path.write_text(
        "Area,Clients\nE01000001,30\nE01000002,12\nE01000004,3\nE01000009,15\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def index():
    """Replace the deprivation index with the invented one."""
    with mock.patch(
        "uk_open_data.analyses.reach_deprivation.load_imd", return_value=_index()
    ):
        yield


def _run_args(path, *extra):
    """Arguments for a run on the counts file."""
    return [
        "analysis",
        "run",
        ANALYSIS_ID,
        str(path),
        "--column",
        "lsoa_code=Area",
        "--column",
        "count=Clients",
        *extra,
    ]


def test_no_command_prints_help(capsys):
    assert main([]) == EXIT_INPUT_ERROR
    assert "analysis" in capsys.readouterr().out


def test_analysis_list(capsys):
    assert main(["analysis", "list"]) == EXIT_OK
    assert capsys.readouterr().out.startswith(f"{ANALYSIS_ID}: ")


def test_analysis_list_json(capsys):
    assert main(["analysis", "list", "--json"]) == EXIT_OK
    analyses = json.loads(capsys.readouterr().out)
    assert ANALYSIS_ID in [analysis["id"] for analysis in analyses]


def test_analysis_describe(capsys):
    assert main(["analysis", "describe", ANALYSIS_ID]) == EXIT_OK
    out = capsys.readouterr().out
    assert "columns needed: lsoa_code, count" in out
    assert "Smallest count shown (--option suppress_below=VALUE, default 5)" in out


def test_analysis_describe_json(capsys):
    assert main(["analysis", "describe", ANALYSIS_ID, "--json"]) == EXIT_OK
    assert json.loads(capsys.readouterr().out)["id"] == ANALYSIS_ID


def test_unknown_analysis_fails_with_the_known_ids(capsys):
    assert main(["analysis", "describe", "no-such-analysis"]) == EXIT_INPUT_ERROR
    assert ANALYSIS_ID in capsys.readouterr().err


def test_analysis_run_prints_a_report(index, counts_file, capsys):
    assert main(_run_args(counts_file)) == EXIT_OK
    out = capsys.readouterr().out
    assert "People placed in an English neighbourhood: 60" in out
    assert "20% most deprived neighbourhoods in England: 70.0%" in out
    assert "Check before you use these figures" in out
    assert "Nothing left this machine." in out
    assert "hidden" in out  # the count of three
    assert "Neighbourhoods in the area you serve" not in out  # the map's table


def test_source_line_for_a_kept_copy_has_one_full_stop(index, counts_file, capsys):
    # The note on a kept copy ends in a full stop, and the line adds its own.
    note = "fetched from gov.uk on 2026-11-19."
    with mock.patch(
        "uk_open_data.analyses.reach_deprivation.kept_imd_note", return_value=note
    ):
        assert main(_run_args(counts_file)) == EXIT_OK
    out = capsys.readouterr().out
    assert "fetched from gov.uk on 2026-11-19. Open Government Licence" in out
    assert ".." not in out.replace("...", "")


def test_report_tables_have_plain_headings_and_units(index, counts_file, capsys):
    assert main(_run_args(counts_file)) == EXIT_OK
    lines = capsys.readouterr().out.splitlines()
    heading = next(line for line in lines if line.startswith("  Deprivation decile"))
    assert heading.split("  ")[1:] == [
        "Deprivation decile",
        "Your people",
        "Share of your people",
        "Residents",
        "Share of residents",
        "Your people per 1,000 residents",
    ]
    first = lines[lines.index(heading) + 1].split()
    assert first == ["1", "30", "50.0%", "1,000", "10.0%", "30.0"]
    assert not any("imd_decile" in line or "lad_name" in line for line in lines)
    assert all(line == line.rstrip() for line in lines)


def test_a_figure_does_not_say_its_unit_twice(index, counts_file, capsys):
    # "People reached per 1,000 residents ...: 30.0", not "30.0 per 1,000".
    assert main(_run_args(counts_file)) == EXIT_OK
    lines = capsys.readouterr().out.splitlines()
    rates = [line for line in lines if line.startswith("  People reached per 1,000")]
    assert rates
    assert not [line for line in rates if line.endswith("per 1,000")]
    # A figure whose label does not say its unit still has it.
    assert any(line.endswith("%") for line in lines)


def test_the_report_ends_with_how_to_check_it_and_run_it_again(
    index, counts_file, capsys
):
    assert main(_run_args(counts_file)) == EXIT_OK
    lines = capsys.readouterr().out.splitlines()
    exact = lines[lines.index("Figures before rounding") + 1]
    assert exact.startswith("  - Share of your people in the area you serve")
    assert exact.endswith(": 50")
    # The two parts are the last two, after the sources and the privacy notes.
    assert lines.index("Privacy") < lines.index("Figures before rounding")
    code = lines[lines.index("To run it again in Python") + 1 :]
    # The code starts at the margin, so it runs as it is copied.
    assert code[0].startswith("# Version ")
    assert f'    "{ANALYSIS_ID}",' in code
    assert code[-3:] == [
        "print(result.answer)",
        "for figure in result.figures:",
        "    print(figure.label, figure.value)",
    ]
    ast.parse("\n".join(code))
    assert all(line == line.rstrip() for line in lines)


def test_the_report_opens_with_the_answer(index, counts_file, capsys):
    assert main(_run_args(counts_file)) == EXIT_OK
    lines = capsys.readouterr().out.splitlines()
    # The title, the question, then the answer, before any figure.
    assert lines[3].startswith("Of your people in the area you serve, 70.0% live")
    assert lines.index("Figures") == 5


def test_analysis_run_json_with_options(index, counts_file, capsys):
    args = _run_args(
        counts_file,
        "--json",
        "--summary",
        "--option",
        "suppress_below=3",
        "--option",
        "catchment=Lewisham",
    )
    assert main(args) == EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["privacy"]["suppress_below"] == 3
    assert payload["privacy"]["cells_suppressed"] == 0
    tables = {table["id"]: table for table in payload["tables"]}
    assert tables["by_neighbourhood"]["rows"] == []
    assert tables["by_decile"]["rows"][3]["people"] == 3


def test_analysis_run_reads_a_json_list_option(index, counts_file, capsys):
    args = _run_args(counts_file, "--json", "--option", 'catchment=["Lewisham"]')
    assert main(args) == EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    catchment = next(c for c in payload["choices"] if c["id"] == "catchment")
    assert catchment["value"] == ["Lewisham"]


def test_analysis_run_writes_to_a_file(index, counts_file, tmp_path, capsys):
    output = tmp_path / "result.json"
    args = _run_args(counts_file, "--json", "--output", str(output))
    assert main(args) == EXIT_OK
    assert json.loads(output.read_text(encoding="utf-8"))["analysis_id"] == ANALYSIS_ID
    assert "Written to" in capsys.readouterr().out


def test_analysis_run_reads_a_spreadsheet(index, tmp_path, capsys):
    rows = [{"Area": "E01000001", "Clients": 30}, {"Area": "E01000002", "Clients": 12}]
    with mock.patch(
        "uk_open_data.cli.read_spreadsheet_rows", return_value=rows
    ) as read:
        path = tmp_path / "counts.xlsx"
        path.write_bytes(b"not a real workbook")
        args = _run_args(path, "--sheet", "Sheet1", "--json")
        assert main(args) == EXIT_OK
    read.assert_called_once_with(b"not a real workbook", "Sheet1")
    payload = json.loads(capsys.readouterr().out)
    assert payload["figures"][1]["value"] == 42


def test_input_problems_exit_with_status_two(index, counts_file, capsys):
    args = [
        "analysis",
        "run",
        ANALYSIS_ID,
        str(counts_file),
        "--column",
        "postcode=Home",
    ]
    assert main(args) == EXIT_INPUT_ERROR
    err = capsys.readouterr().err
    assert "The column 'Home' given for 'postcode' is not in the data." in err


def test_an_unreachable_source_is_reported_without_its_address(counts_file, capsys):
    # A real postcode never ends in C, so this one cannot exist.
    address = "https://api.postcodes.io/postcodes/SE13%207VC?secret=1"
    error = requests.exceptions.ProxyError(
        f"HTTPSConnectionPool: Max retries exceeded with url: {address}",
        request=requests.Request("GET", address).prepare(),
    )
    with mock.patch("uk_open_data.cli.run_analysis", side_effect=error):
        assert main(_run_args(counts_file)) == EXIT_INPUT_ERROR
    err = capsys.readouterr().err
    assert err.startswith(
        "A data source this command needs could not be reached (api.postcodes.io)."
    )
    assert "Check the connection and try again." in err
    for part in ("https", "SE13", "7VC", "secret", "Max retries"):
        assert part not in err


def test_an_unreachable_source_without_an_address_is_still_reported(
    counts_file, capsys
):
    error = requests.ConnectionError("no route to https://example.invalid/?q=1")
    with mock.patch("uk_open_data.cli.run_analysis", side_effect=error):
        assert main(_run_args(counts_file)) == EXIT_INPUT_ERROR
    err = capsys.readouterr().err
    assert err.startswith("A data source this command needs could not be reached. ")
    assert "example.invalid" not in err


def test_a_source_that_answers_with_an_error_is_not_called_unreachable(
    counts_file, capsys
):
    address = "https://www.nomisweb.co.uk/api/v01/dataset/NM_1_1.data.csv?secret=1"
    response = requests.Response()
    response.status_code = 503
    response.url = address
    response.request = requests.Request("GET", address).prepare()
    error = requests.HTTPError(
        f"503 Server Error: Service Unavailable for url: {address}", response=response
    )
    with mock.patch("uk_open_data.cli.run_analysis", side_effect=error):
        assert main(_run_args(counts_file)) == EXIT_INPUT_ERROR
    err = capsys.readouterr().err
    assert err.startswith(
        "A data source this command needs answered with an error "
        "(www.nomisweb.co.uk), status 503."
    )
    assert "could not be reached" not in err
    assert "Check the connection" not in err
    for part in ("https", "NM_1_1", "secret", "Server Error"):
        assert part not in err


def test_missing_file_is_reported(capsys):
    assert main(["analysis", "run", ANALYSIS_ID, "nowhere.csv"]) == EXIT_INPUT_ERROR
    assert "was not found" in capsys.readouterr().err


def test_other_file_types_are_rejected(tmp_path, capsys):
    path = tmp_path / "clients.pdf"
    path.write_bytes(b"")
    assert main(["analysis", "run", ANALYSIS_ID, str(path)]) == EXIT_INPUT_ERROR
    assert ".csv, .xlsx or .ods" in capsys.readouterr().err


def test_a_pair_without_equals_is_rejected(index, counts_file, capsys):
    args = ["analysis", "run", ANALYSIS_ID, str(counts_file), "--column", "postcode"]
    assert main(args) == EXIT_INPUT_ERROR
    assert "NAME=VALUE" in capsys.readouterr().err


def test_a_run_that_answers_is_recorded_once(index, counts_file, capsys, caplog):
    with caplog.at_level(logging.INFO, logger="uk_open_data.runs"):
        assert main(_run_args(counts_file)) == EXIT_OK
    assert [record.getMessage() for record in caplog.records] == [
        "run analysis=reach-deprivation mode=neighbourhood_counts door=cli"
    ]


def test_an_option_error_says_what_to_type(index, counts_file, capsys):
    assert main(_run_args(counts_file, "--option", "suppress_below=1")) == 2
    err = capsys.readouterr().err
    assert "'Smallest count shown' cannot be lower than 3" in err
    assert err.endswith("On the command line this is --option suppress_below=VALUE.\n")


def test_a_column_error_says_what_to_type(index, counts_file, capsys):
    args = ["analysis", "run", ANALYSIS_ID, str(counts_file)]
    assert main([*args, "--column", "postcode=Nowhere"]) == EXIT_INPUT_ERROR
    err = capsys.readouterr().err
    assert err.endswith("On the command line this is --column postcode=COLUMN.\n")


def test_a_run_that_fails_is_not_recorded(index, counts_file, capsys, caplog):
    args = _run_args(counts_file, "--option", "no_such_option=1")
    with caplog.at_level(logging.INFO, logger="uk_open_data.runs"):
        assert main(args) == EXIT_INPUT_ERROR
    assert caplog.records == []


def _no_outlines(*args, **kwargs):
    """Stand in for the boundary service when it cannot be reached.

    The real one logs its error, which holds its web address, and gives back
    no outlines.
    """
    log = logging.getLogger("uk_open_data.geo.api")
    assert logging.getLogger("uk_open_data.geo").handlers, "the log is not kept quiet"
    log.error("Error querying ArcGIS service: https://services1.arcgis.com/x")
    return {"type": "FeatureCollection", "features": []}


def test_map_that_cannot_be_fetched_leaves_the_report(
    index, counts_file, tmp_path, capsys, caplog
):
    picture = tmp_path / "map.svg"
    with (
        mock.patch("uk_open_data.analyses.maps.load_geodata", _no_outlines),
        caplog.at_level(logging.INFO, logger="uk_open_data.runs"),
    ):
        status = main(_run_args(counts_file, "--map", str(picture)))
    shown = capsys.readouterr()
    # A status of its own: the report is whole, so a script can keep it.
    assert status == EXIT_MAP_NOT_DRAWN
    assert EXIT_MAP_NOT_DRAWN not in (EXIT_OK, EXIT_INPUT_ERROR)
    assert "most deprived" in shown.out
    assert shown.err == f"{MAP_BEING_FETCHED}\n{MAP_NOT_DRAWN}\n"
    assert not picture.exists()
    assert logging.getLogger("uk_open_data.geo").handlers == []
    runs = [r for r in caplog.records if r.name == "uk_open_data.runs"]
    assert len(runs) == 1


def test_map_error_from_the_service_is_not_shown(index, counts_file, tmp_path, capsys):
    error = requests.ConnectionError(
        "HTTPSConnectionPool(host='services1.arcgis.com'): Max retries exceeded "
        "with url: /x/query?where=LSOA21CD IN ('E01000001')"
    )
    with mock.patch("uk_open_data.cli.load_map_boundaries", side_effect=error):
        status = main(
            _run_args(counts_file, "--json", "--map", str(tmp_path / "map.svg"))
        )
    shown = capsys.readouterr()
    assert status == EXIT_MAP_NOT_DRAWN
    assert json.loads(shown.out)["analysis_id"] == ANALYSIS_ID
    assert shown.err == f"{MAP_BEING_FETCHED}\n{MAP_NOT_DRAWN}\n"
    assert "arcgis" not in shown.err
    assert "E01000001" not in shown.err


def test_the_command_says_first_that_the_map_is_being_fetched(
    index, counts_file, tmp_path, capsys
):
    # At times the outlines take a minute or two to come. The
    # line is on standard error, so the report on standard output is as it was.
    asked: list[str] = []

    def outlines(result):
        asked.append(capsys.readouterr().err)
        return {"type": "FeatureCollection", "features": []}

    with mock.patch("uk_open_data.cli.load_map_boundaries", outlines):
        main(_run_args(counts_file, "--map", str(tmp_path / "map.svg")))
    assert asked == [MAP_BEING_FETCHED + "\n"]
    shown = capsys.readouterr()
    assert "Fetching the outlines" not in shown.out
    # A run with no map says nothing of the kind.
    assert main(_run_args(counts_file)) == EXIT_OK
    assert capsys.readouterr().err == ""


def test_report_goes_to_its_file_when_the_map_is_not_drawn(
    index, counts_file, tmp_path, capsys
):
    report = tmp_path / "report.txt"
    with mock.patch("uk_open_data.analyses.maps.load_geodata", _no_outlines):
        status = main(
            _run_args(
                counts_file,
                "--map",
                str(tmp_path / "map.svg"),
                "--output",
                str(report),
            )
        )
    assert status == EXIT_MAP_NOT_DRAWN
    assert "most deprived" in report.read_text(encoding="utf-8")
    assert MAP_NOT_DRAWN in capsys.readouterr().err


def test_connector_command_passes_its_options_on(capsys):
    with mock.patch("uk_open_data.connector.command.main") as start:
        status = main(["connector", "--transport", "streamable-http", "--port", "9"])
    assert status == EXIT_OK
    start.assert_called_once_with(
        ["--transport", "streamable-http", "--port", "9"],
        prog="uk-open-data connector",
    )
    assert capsys.readouterr().out == ""


def test_connector_command_help_names_the_command_typed(capsys):
    with pytest.raises(SystemExit):
        main(["connector", "--help"])
    assert capsys.readouterr().out.startswith("usage: uk-open-data connector")


def test_connector_command_starts_the_server_over_stdio():
    with mock.patch("uk_open_data.connector.build_server") as build:
        assert main(["connector"]) == EXIT_OK
    build.return_value.run.assert_called_once_with("stdio")


def test_connector_command_says_which_extra_is_missing(capsys):
    missing = ImportError("The connector server needs the 'connector' extra.")
    with mock.patch("uk_open_data.connector.build_server", side_effect=missing):
        assert main(["connector"]) == EXIT_INPUT_ERROR
    shown = capsys.readouterr()
    assert shown.err == "The connector server needs the 'connector' extra.\n"
    assert shown.out == ""


def test_help_lists_the_connector_command(capsys):
    with pytest.raises(SystemExit):
        main(["--help"])
    assert "connector" in capsys.readouterr().out
