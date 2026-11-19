"""
Unit tests for the command line.

The deprivation index is replaced with a small invented table, and the files
are written to a temporary folder, so the tests are isolated and repeatable.
"""

import json
import logging
import unittest.mock as mock

import pandas as pd
import pytest
import requests

from uk_open_data.cli import EXIT_INPUT_ERROR, EXIT_OK, main

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
    assert "suppress_below (default 5)" in out


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
    assert "Catchment neighbourhoods" not in out  # the map table is left out


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


def test_a_run_that_fails_is_not_recorded(index, counts_file, capsys, caplog):
    args = _run_args(counts_file, "--option", "no_such_option=1")
    with caplog.at_level(logging.INFO, logger="uk_open_data.runs"):
        assert main(args) == EXIT_INPUT_ERROR
    assert caplog.records == []
