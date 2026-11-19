"""
Unit tests for the postcode table kept on this machine.

Tables are built from a tiny invented lookup in a temporary folder. Nothing is
downloaded: the one test of fetching replaces the web request.
"""

import gzip
import hashlib
import unittest.mock as mock
import zipfile

import pandas as pd
import pytest
import requests

from uk_open_data.analyses import AnalysisInputError, run_analysis
from uk_open_data.cli import EXIT_OK, main
from uk_open_data.postcodes import (
    PostcodeTableError,
    build_postcode_table,
    district_to_local_authorities,
    download_postcode_table,
    install_postcode_table,
    postcode_table_info,
    postcode_table_path,
    postcode_to_lsoa,
    postcodes_to_local_authority,
    postcodes_to_lsoa,
)

# Invented rows in the shape of the ONS lookup. Real postcodes never end in
# C, I, K, M, O or V, so none of these can exist.
SOURCE_ROWS = [
    ("SE137VC", "E01000001", "E09000023"),
    ("SE137VK", "E01000001", "E09000023"),
    ("SE136CM", "E01000002", "E09000023"),
    ("SE1 2VC", "E01000003", "E09000028"),
    ("SE1 9OK", "E01000004", "E09000022"),
    ("M1  1VC", "E01000005", "E08000003"),
    ("CF101VC", "W01000001", "W06000015"),
    ("EH1 1VC", "S01000001", "S12000036"),
    ("BT1 1VC", "95AA01S1", "N09000003"),
]


def _source_text() -> str:
    """The invented lookup as CSV text, with the columns the ONS file has."""
    header = "pcd7,pcd8,pcds,dointr,doterm,usertype,oa21cd,lsoa21cd,msoa21cd,ladcd"
    lines = [
        f"{pcd7},x,x,202001,,0,E00000001,{lsoa},E02000001,{lad}"
        for pcd7, lsoa, lad in SOURCE_ROWS
    ]
    return "\n".join([header, *lines]) + "\n"


@pytest.fixture
def packed(tmp_path):
    """A gzipped table built from the invented lookup."""
    source = tmp_path / "lookup.csv"
    source.write_text(_source_text(), encoding="utf-8")
    output = tmp_path / "postcodes.ktpc.gz"
    build_postcode_table(source, output, "May 2026")
    return output


@pytest.fixture
def installed(packed):
    """Install the invented table in the test data folder."""
    return install_postcode_table(packed)


def test_build_keeps_england_and_wales_only(tmp_path):
    source = tmp_path / "lookup.csv"
    source.write_text(_source_text(), encoding="utf-8")
    summary = build_postcode_table(source, tmp_path / "out.gz", "May 2026")
    assert summary["records"] == 7  # not the Scottish or Northern Irish row
    assert summary["areas"] == 6
    packed_bytes = (tmp_path / "out.gz").read_bytes()
    assert summary["sha256"] == hashlib.sha256(packed_bytes).hexdigest()
    assert summary["bytes"] == len(packed_bytes)


def test_build_is_repeatable(tmp_path):
    source = tmp_path / "lookup.csv"
    source.write_text(_source_text(), encoding="utf-8")
    first = build_postcode_table(source, tmp_path / "a.gz", "May 2026")
    second = build_postcode_table(source, tmp_path / "b.gz", "May 2026")
    assert first["sha256"] == second["sha256"]


def test_build_reads_the_zip_the_lookup_comes_in(tmp_path):
    archive = tmp_path / "lookup.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("PCD_OA21_LSOA21_MSOA21_LAD_UK_LU.csv", _source_text().upper())
    summary = build_postcode_table(archive, tmp_path / "out.gz", "May 2026")
    assert summary["records"] == 7


def test_build_rejects_a_file_without_the_columns(tmp_path):
    source = tmp_path / "other.csv"
    source.write_text("postcode,area\nSE13 7VC,E01000001\n", encoding="utf-8")
    with pytest.raises(PostcodeTableError, match="pcd7, lsoa21cd, ladcd"):
        build_postcode_table(source, tmp_path / "out.gz", "May 2026")


def test_build_rejects_a_source_with_nothing_to_keep(tmp_path):
    source = tmp_path / "lookup.csv"
    source.write_text("pcd7,lsoa21cd,ladcd\nEH1 1VC,S01000001,S12000036\n", "utf-8")
    with pytest.raises(PostcodeTableError, match="no postcodes in England or Wales"):
        build_postcode_table(source, tmp_path / "out.gz", "May 2026")


def test_nothing_is_installed_to_begin_with():
    assert postcode_table_path() is None
    # No table is published yet, so the message says how to make one.
    with pytest.raises(PostcodeTableError, match="postcodes build"):
        postcode_to_lsoa("SE13 7VC")


def test_a_published_table_is_what_the_message_points_to():
    published = {"url": "https://example.org/t.gz", "sha256": "0", "edition": "x"}
    with (
        mock.patch("uk_open_data.postcodes.offline.PUBLISHED_TABLE", published),
        pytest.raises(PostcodeTableError, match="postcodes download"),
    ):
        postcode_to_lsoa("SE13 7VC")


@pytest.mark.parametrize(
    ("postcode", "expected"),
    [
        ("SE13 7VC", "E01000001"),
        ("se137vk", "E01000001"),
        ("  SE13  6CM ", "E01000002"),
        ("SE1 2VC", "E01000003"),
        ("M1 1VC", "E01000005"),
        ("CF10 1VC", "W01000001"),
        ("EH1 1VC", None),  # Scotland is not in the table
        ("BT1 1VC", None),  # nor is Northern Ireland
        ("SE13 7VO", None),  # the right shape, but not in the table
        ("not a postcode", None),
        ("", None),
    ],
)
def test_postcode_to_lsoa(installed, postcode, expected):
    assert postcode_to_lsoa(postcode) == expected


def test_postcodes_to_lsoa_keeps_the_order_given(installed):
    assert postcodes_to_lsoa(["M1 1VC", "nope", "SE13 7VC"]) == [
        "E01000005",
        None,
        "E01000001",
    ]


def test_postcodes_to_local_authority_keeps_the_order_given(installed):
    assert postcodes_to_local_authority(["cf10 1vc", "EH1 1VC", "SE13 7VC"]) == [
        "W06000015",
        None,
        "E09000023",
    ]


def test_district_to_local_authorities(installed):
    assert district_to_local_authorities("SE13") == ["E09000023"]
    assert district_to_local_authorities("se1") == ["E09000022", "E09000028"]
    assert district_to_local_authorities("SE2") == []
    assert district_to_local_authorities("not a district") == []


def test_table_info_carries_the_edition_and_the_credits(installed):
    info = postcode_table_info()
    assert info["edition"] == "May 2026"
    assert info["records"] == 7
    assert info["coverage"] == "England and Wales"
    assert "areas" not in info
    assert info["attribution"][0].startswith("Source: Office for National Statistics")
    assert any("Royal Mail data" in line for line in info["attribution"])
    assert any("OS data" in line for line in info["attribution"])


def test_install_rejects_other_files(tmp_path):
    plain = tmp_path / "notes.txt"
    plain.write_text("hello", encoding="utf-8")
    with pytest.raises(PostcodeTableError, match="not a gzipped postcode table"):
        install_postcode_table(plain)
    other = tmp_path / "other.gz"
    other.write_bytes(gzip.compress(b"hello"))
    with pytest.raises(PostcodeTableError, match="not a postcode table"):
        install_postcode_table(other)
    assert postcode_table_path() is None


def _response(content: bytes) -> mock.MagicMock:
    """A stand-in for a successful web response."""
    response = mock.MagicMock()
    response.content = content
    response.raise_for_status = mock.MagicMock()
    return response


def test_download_checks_the_sha256_before_installing(packed):
    content = packed.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    url = "https://example.org/postcodes.ktpc.gz"
    with mock.patch("requests.get", return_value=_response(content)) as get:
        with pytest.raises(PostcodeTableError, match="does not match"):
            download_postcode_table(url=url, sha256="0" * 64)
        assert postcode_table_path() is None
        path = download_postcode_table(url=url, sha256=digest.upper())
        assert path == postcode_table_path()
        assert postcode_to_lsoa("SE13 7VC") == "E01000001"
        # Already installed, so nothing is fetched again unless forced.
        download_postcode_table(url=url, sha256=digest)
        assert get.call_count == 2
        download_postcode_table(url=url, sha256=digest, force=True)
        assert get.call_count == 3
    assert get.call_args.kwargs["timeout"] > 0


def test_download_needs_https_a_sha256_and_a_published_table():
    with pytest.raises(PostcodeTableError, match="No postcode table has been"):
        download_postcode_table()
    with pytest.raises(PostcodeTableError, match="https"):
        download_postcode_table(url="http://example.org/t.gz", sha256="0" * 64)
    with pytest.raises(PostcodeTableError, match="sha256 is needed"):
        download_postcode_table(url="https://example.org/t.gz")


def test_download_failure_is_reported():
    error = requests.ConnectionError("no network")
    with (
        mock.patch("requests.get", side_effect=error),
        pytest.raises(PostcodeTableError, match="could not be fetched"),
    ):
        download_postcode_table(url="https://example.org/t.gz", sha256="0" * 64)


# --- the analysis ---------------------------------------------------------------


def _index() -> pd.DataFrame:
    """An invented index covering the neighbourhoods in the invented table."""
    rows = [
        {
            "geography_code": f"E0100000{number}",
            "geography_name": f"Lewisham 00{number}A",
            "lad_code": "E09000023",
            "lad_name": "Lewisham",
            "imd_decile": number,
            "population": 1000,
        }
        for number in range(1, 6)
    ]
    return pd.DataFrame(rows)


ROWS = [{"postcode": "SE13 7VC"}] * 6 + [{"postcode": "se136cm"}] * 5


def _run(options=None):
    """Run the analysis with the index replaced and the online lookup watched."""
    with (
        mock.patch(
            "uk_open_data.analyses.reach_deprivation.load_imd", return_value=_index()
        ),
        mock.patch("uk_open_data.analyses._steps.postcodes_to_geography") as online,
    ):
        online.return_value = pd.DataFrame(
            {"geography_code": ["E01000002", "E01000001"]}
        )
        return run_analysis("reach-deprivation", ROWS, options=options), online


def test_analysis_uses_the_table_when_one_is_installed(installed):
    result, online = _run()
    online.assert_not_called()
    assert result.privacy.sent_to_third_parties == ()
    assert result.figure("people_located").value == 11
    assert [source.id for source in result.sources] == [
        "ons-postcode-lookup",
        "iod-2025",
    ]
    lookup = result.sources[0]
    assert lookup.edition == "May 2026"
    assert any("Royal Mail" in line for line in lookup.attribution)
    choice = result.choices[0]
    assert choice.id == "postcode_lookup"
    assert choice.value.startswith("On this machine")
    assert "on this machine" in result.working[1].detail


def test_analysis_goes_online_when_no_table_is_installed():
    result, online = _run()
    online.assert_called_once()
    assert "postcodes.io" in result.privacy.sent_to_third_parties[0]
    assert result.choices[0].value == "postcodes.io, an online service"
    assert "postcodes download" in result.choices[0].reason


def test_analysis_can_be_told_to_go_online(installed):
    result, online = _run({"postcode_lookup": "online"})
    online.assert_called_once()
    reason = result.choices[0].reason
    assert reason.startswith("You chose the online service.")
    assert "No postcode table is installed" not in reason


def test_analysis_told_to_go_online_without_a_table_says_none_is_installed():
    result, _ = _run({"postcode_lookup": "online"})
    assert result.choices[0].reason.startswith("No postcode table is installed")


def test_analysis_told_to_stay_offline_fails_without_a_table():
    with pytest.raises(AnalysisInputError, match="No postcode table is installed"):
        _run({"postcode_lookup": "offline"})


def test_analysis_rejects_an_unknown_lookup():
    with pytest.raises(AnalysisInputError, match="auto, offline, online"):
        _run({"postcode_lookup": "magic"})


def test_not_found_warning_names_the_table_coverage(installed):
    rows = [*ROWS, {"postcode": "EH1 1VC"}]
    with mock.patch(
        "uk_open_data.analyses.reach_deprivation.load_imd", return_value=_index()
    ):
        result = run_analysis("reach-deprivation", rows)
    assert any("outside England and Wales" in w for w in result.warnings)


# --- the command line -------------------------------------------------------


def test_command_line_builds_installs_and_describes_a_table(tmp_path, capsys):
    source = tmp_path / "lookup.csv"
    source.write_text(_source_text(), encoding="utf-8")
    table = tmp_path / "postcodes.ktpc.gz"
    args = ["postcodes", "build", str(source), str(table), "--edition", "May 2026"]
    assert main(args) == EXIT_OK
    out = capsys.readouterr().out
    assert "7 postcodes in 6 neighbourhoods" in out
    digest = out.strip().splitlines()[-1].removeprefix("sha256: ")

    # Having no table is not a mistake, so the command says so and ends well.
    assert main(["postcodes", "info"]) == EXIT_OK
    said = capsys.readouterr()
    assert said.err == ""
    # What a person running an analysis needs comes first, and how to make a
    # table, which is for a developer, comes after it.
    assert said.out.startswith(
        "No postcode table is installed on this machine. That is fine: an "
        "analysis then looks postcodes up with postcodes.io"
    )
    assert said.out.index("postcodes.io") < said.out.index("postcodes build")
    # No table is published yet, so the command must not send people to fetch one.
    assert "postcodes download" not in said.out
    assert "uk-open-data postcodes build" in said.out
    assert "looks postcodes up with postcodes.io" in said.out

    url = "https://example.org/postcodes.ktpc.gz"
    with mock.patch("requests.get", return_value=_response(table.read_bytes())):
        assert main(["postcodes", "download", "--url", url, "--sha256", digest]) == 0
    assert "May 2026" in capsys.readouterr().out
    assert main(["postcodes", "info"]) == EXIT_OK
    assert "Contains Royal Mail data" in capsys.readouterr().out
