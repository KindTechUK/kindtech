"""
Unit tests for the command line.

The deprivation index is replaced with a small invented table, and the files
are written to a temporary folder, so the tests are isolated and repeatable.
"""

import json
import unittest.mock as mock

import pandas as pd
import pytest
import requests

from kindtech.cli import EXIT_INPUT_ERROR, EXIT_OK, main

LENS_ID = "reach-deprivation"


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
        "kindtech.lenses.reach_deprivation.load_imd", return_value=_index()
    ):
        yield


def _run_args(path, *extra):
    """Arguments for a run on the counts file."""
    return [
        "lens",
        "run",
        LENS_ID,
        str(path),
        "--column",
        "lsoa_code=Area",
        "--column",
        "count=Clients",
        *extra,
    ]


def test_no_command_prints_help(capsys):
    assert main([]) == EXIT_INPUT_ERROR
    assert "lens" in capsys.readouterr().out


def test_lens_list(capsys):
    assert main(["lens", "list"]) == EXIT_OK
    assert capsys.readouterr().out.startswith(f"{LENS_ID}: ")


def test_lens_list_json(capsys):
    assert main(["lens", "list", "--json"]) == EXIT_OK
    lenses = json.loads(capsys.readouterr().out)
    assert LENS_ID in [lens["id"] for lens in lenses]


def test_lens_describe(capsys):
    assert main(["lens", "describe", LENS_ID]) == EXIT_OK
    out = capsys.readouterr().out
    assert "columns needed: lsoa_code, count" in out
    assert "suppress_below (default 5)" in out


def test_lens_describe_json(capsys):
    assert main(["lens", "describe", LENS_ID, "--json"]) == EXIT_OK
    assert json.loads(capsys.readouterr().out)["id"] == LENS_ID


def test_unknown_lens_fails_with_the_known_ids(capsys):
    assert main(["lens", "describe", "no-such-lens"]) == EXIT_INPUT_ERROR
    assert LENS_ID in capsys.readouterr().err


def test_lens_run_prints_a_report(index, counts_file, capsys):
    assert main(_run_args(counts_file)) == EXIT_OK
    out = capsys.readouterr().out
    assert "People placed in an English neighbourhood: 60" in out
    assert "20% most deprived neighbourhoods in England: 70.0%" in out
    assert "Check before you use these figures" in out
    assert "Nothing left this machine." in out
    assert "hidden" in out  # the count of three
    assert "Catchment neighbourhoods" not in out  # the map table is left out


def test_lens_run_json_with_options(index, counts_file, capsys):
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


def test_lens_run_reads_a_json_list_option(index, counts_file, capsys):
    args = _run_args(counts_file, "--json", "--option", 'catchment=["Lewisham"]')
    assert main(args) == EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    catchment = next(c for c in payload["choices"] if c["id"] == "catchment")
    assert catchment["value"] == ["Lewisham"]


def test_lens_run_writes_to_a_file(index, counts_file, tmp_path, capsys):
    output = tmp_path / "result.json"
    args = _run_args(counts_file, "--json", "--output", str(output))
    assert main(args) == EXIT_OK
    assert json.loads(output.read_text(encoding="utf-8"))["lens_id"] == LENS_ID
    assert "Written to" in capsys.readouterr().out


def test_lens_run_reads_a_spreadsheet(index, tmp_path, capsys):
    rows = [{"Area": "E01000001", "Clients": 30}, {"Area": "E01000002", "Clients": 12}]
    with mock.patch("kindtech.cli.read_spreadsheet_rows", return_value=rows) as read:
        path = tmp_path / "counts.xlsx"
        path.write_bytes(b"not a real workbook")
        args = _run_args(path, "--sheet", "Sheet1", "--json")
        assert main(args) == EXIT_OK
    read.assert_called_once_with(b"not a real workbook", "Sheet1")
    payload = json.loads(capsys.readouterr().out)
    assert payload["figures"][1]["value"] == 42


def test_input_problems_exit_with_status_two(index, counts_file, capsys):
    args = ["lens", "run", LENS_ID, str(counts_file), "--column", "postcode=Home"]
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
    with mock.patch("kindtech.cli.run_lens", side_effect=error):
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
    with mock.patch("kindtech.cli.run_lens", side_effect=error):
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
    with mock.patch("kindtech.cli.run_lens", side_effect=error):
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
    assert main(["lens", "run", LENS_ID, "nowhere.csv"]) == EXIT_INPUT_ERROR
    assert "was not found" in capsys.readouterr().err


def test_other_file_types_are_rejected(tmp_path, capsys):
    path = tmp_path / "clients.pdf"
    path.write_bytes(b"")
    assert main(["lens", "run", LENS_ID, str(path)]) == EXIT_INPUT_ERROR
    assert ".csv, .xlsx or .ods" in capsys.readouterr().err


def test_a_pair_without_equals_is_rejected(index, counts_file, capsys):
    args = ["lens", "run", LENS_ID, str(counts_file), "--column", "postcode"]
    assert main(args) == EXIT_INPUT_ERROR
    assert "NAME=VALUE" in capsys.readouterr().err
