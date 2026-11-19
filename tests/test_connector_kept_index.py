"""Tests for "describe a place" reading a copy of the index kept on this machine.

The copy is a small invented England kept in the test's data folder, and any
download fails the test, so these run with no network.
"""

from collections.abc import Iterator

import connector_fakes as fakes
import pytest
import requests

from uk_open_data.connector import describe_place, places
from uk_open_data.imd import imd_path, keep_imd

NOTE = "invented for a test."
REQUIRED = [
    "geography_code",
    "geography_name",
    "lad_code",
    "lad_name",
    "imd_decile",
    "population",
]


@pytest.fixture(autouse=True)
def _no_download(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Fail on any download, and forget the index held in memory."""

    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("The index was downloaded.")

    monkeypatch.setattr(requests, "get", refuse)
    places.clear_cache()
    yield
    places.clear_cache()


def test_reads_the_kept_copy_and_says_so() -> None:
    keep_imd(fakes.england_frame(), NOTE)

    answer = describe_place("Lewisham")

    assert answer["status"] == "found"
    assert [table["id"] for table in answer["tables"]] == ["by_decile", "by_domain"]
    assert answer["warnings"] == []
    assert answer["sources"][0]["id"] == "iod-2025"
    assert answer["sources"][0]["edition"].endswith(
        f"A copy kept on this machine, {NOTE}"
    )


@pytest.mark.parametrize(
    ("place", "tables"), [("Lewisham", ["by_decile"]), ("E01000001", [])]
)
def test_a_copy_without_the_types_of_deprivation_leaves_that_table_out(
    place: str, tables: list[str]
) -> None:
    keep_imd(fakes.england_frame()[REQUIRED], NOTE)

    answer = describe_place(place)

    assert answer["status"] == "found"
    assert [table["id"] for table in answer["tables"]] == tables
    assert answer["warnings"] == [places.NO_DOMAINS]
    assert answer["figures"]


def test_a_copy_that_cannot_be_read_gives_a_plain_answer(
    caplog: pytest.LogCaptureFixture,
) -> None:
    path = keep_imd(fakes.england_frame(), NOTE)
    path.write_text("{not the file it was", encoding="utf-8")

    answer = describe_place("Lewisham")

    assert imd_path() == path
    assert answer["status"] == "unavailable"
    assert "fault on the server" in answer["message"]
    assert "could not be read" in caplog.text
