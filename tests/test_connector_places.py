"""Tests for the connector's "describe a place".

The deprivation download and postcodes.io are replaced with small stand-ins so
the tests are isolated and repeatable.
"""

import json

import connector_fakes as fakes
import pytest
import requests

from kindtech.connector import describe_place, places
from kindtech.postcodes import offline

pytestmark = pytest.mark.usefixtures("england")


def _figure(answer: dict, figure_id: str) -> object:
    """The value of one figure in an answer."""
    return next(f["value"] for f in answer["figures"] if f["id"] == figure_id)


def test_local_authority_by_name() -> None:
    answer = describe_place("Lewisham")

    assert answer["status"] == "found"
    assert answer["place"] == {
        "kind": "local_authority",
        "code": "E09000023",
        "name": "Lewisham",
        "matched_from": "name",
        "coverage": "England",
    }
    assert _figure(answer, "neighbourhoods") == 4
    assert _figure(answer, "residents") == 7000
    assert _figure(answer, "share_neighbourhoods_most_deprived_10") == 25.0
    assert _figure(answer, "share_neighbourhoods_most_deprived_20") == 50.0
    # 1,500 + 1,700 of 7,000 residents live in deciles 1 and 2.
    assert _figure(answer, "share_residents_most_deprived_20") == 45.7
    # The same 3,200 residents out of England's 16,500.
    assert _figure(answer, "england_share_residents_most_deprived_20") == 19.4


def test_local_authority_tables() -> None:
    answer = describe_place("E09000023")
    by_decile, by_domain = answer["tables"]

    assert answer["place"]["matched_from"] == "local_authority_code"
    assert by_decile["id"] == "by_decile"
    assert [row["neighbourhoods"] for row in by_decile["rows"]] == [
        1, 1, 0, 0, 1, 0, 0, 0, 0, 1,
    ]  # fmt: skip
    assert by_decile["rows"][0]["share_of_residents"] == 21.4
    # Income follows the overall decile, so it is the most widespread domain.
    assert by_domain["rows"][0] == {
        "domain": "Income",
        "neighbourhoods_most_deprived_20": 2,
        "share_of_neighbourhoods": 50.0,
    }
    assert set(by_decile["columns"]) == set(by_decile["rows"][0])


@pytest.mark.parametrize(
    ("asked", "expected"),
    [
        ("lewisham council", "Lewisham"),
        ("London Borough of Lewisham", "Lewisham"),
        ("Bristol", "Bristol, City of"),
        ("Bristol City Council", "Bristol, City of"),
        ("Durham", "County Durham"),
        ("newcastle-under-lyme", "Newcastle-under-Lyme"),
    ],
)
def test_council_names_are_matched_loosely(asked: str, expected: str) -> None:
    assert describe_place(asked)["place"]["name"] == expected


def test_ambiguous_name_asks_the_person_to_choose() -> None:
    answer = describe_place("Newcastle")

    assert answer["status"] == "choose"
    assert [match["name"] for match in answer["matches"]] == [
        "Newcastle upon Tyne",
        "Newcastle-under-Lyme",
    ]
    assert "figures" not in answer


def test_unknown_name_is_not_found_and_not_repeated() -> None:
    answer = describe_place("Atlantis-on-Sea")

    assert answer["status"] == "not_found"
    assert "atlantis" not in json.dumps(answer).lower()


def test_neighbourhood_by_code() -> None:
    answer = describe_place("e01000002")

    assert answer["status"] == "found"
    assert answer["place"]["kind"] == "neighbourhood"
    assert answer["place"]["local_authority"] == {
        "code": "E09000023",
        "name": "Lewisham",
    }
    assert _figure(answer, "imd_decile") == 2
    assert _figure(answer, "imd_rank") == 2
    assert _figure(answer, "residents") == 1700
    assert (
        _figure(answer, "local_authority_share_neighbourhoods_most_deprived_20") == 50.0
    )
    assert answer["tables"][0]["rows"][0] == {
        "domain": "Income",
        "decile": 2,
        "rank": 2,
    }


def test_unknown_neighbourhood_code() -> None:
    assert describe_place("E01999999")["status"] == "not_found"


@pytest.mark.parametrize("code", ["W01000001", "S01006506", "N00000001", "W06000015"])
def test_other_nations_are_not_covered(code: str) -> None:
    assert describe_place(code)["status"] == "not_covered"


@pytest.mark.parametrize(
    "name",
    [
        "Cardiff",
        "cardiff council",
        "City of Cardiff Council",
        "Anglesey",
        "Rhondda Cynon Taf",
        "Vale of Glamorgan",
        "Newport",
    ],
)
def test_a_welsh_council_is_not_covered_and_the_answer_says_why(name: str) -> None:
    answer = describe_place(name)

    assert answer["status"] == "not_covered"
    assert "in Wales" in answer["message"]
    assert "lenses that cover England and Wales" in answer["message"]


@pytest.mark.parametrize("code", ["W06000015", "W01000001"])
def test_a_welsh_code_says_it_is_in_wales(code: str) -> None:
    assert "in Wales" in describe_place(code)["message"]


@pytest.mark.parametrize("code", ["S01006506", "N00000001"])
def test_another_nations_code_does_not_say_wales(code: str) -> None:
    assert "Wales" not in describe_place(code)["message"]


@pytest.mark.parametrize("name", ["Atlantis", "Edinburgh", "the", "council"])
def test_a_name_that_is_no_council_in_england_or_wales_is_not_found(name: str) -> None:
    assert describe_place(name)["status"] == "not_found"


def test_an_english_match_wins_over_a_welsh_name() -> None:
    # "Newcastle" is in two English names and in no Welsh one; "Lewisham" is
    # English only. Neither answer may change.
    assert describe_place("Newcastle")["status"] == "choose"
    assert describe_place("Lewisham")["status"] == "found"


def test_postcode_gives_its_neighbourhood_without_repeating_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked: list[str] = []

    def lookup(postcode: str) -> object:
        asked.append(postcode)
        return fakes.postcode_frame("E01000001")

    monkeypatch.setattr(places, "lookup_postcodes", lookup)

    answer = describe_place(" zz99 9kc ")

    assert asked == [fakes.SECRET_POSTCODE]
    assert answer["status"] == "found"
    assert answer["place"]["code"] == "E01000001"
    assert answer["place"]["matched_from"] == "postcode"
    assert "ZZ99" not in json.dumps(answer).upper()
    assert "postcodes.io" in answer["privacy"]["sent_to_third_parties"][0]
    assert [source["id"] for source in answer["sources"]] == [
        "iod-2025",
        "postcodes-io",
    ]


def test_unknown_postcode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        places, "lookup_postcodes", lambda postcode: fakes.postcode_frame(None)
    )

    answer = describe_place(fakes.SECRET_POSTCODE)

    assert answer["status"] == "not_found"
    assert "ZZ99" not in json.dumps(answer).upper()


def test_welsh_postcode_is_not_covered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        places, "lookup_postcodes", lambda postcode: fakes.postcode_frame("W01000001")
    )

    assert describe_place(fakes.SECRET_POSTCODE)["status"] == "not_covered"


def test_postcode_district_in_one_authority(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        places, "lookup_outcodes", lambda outcode: fakes.outcode_frame("Lewisham")
    )

    answer = describe_place("zz99")

    assert answer["status"] == "found"
    assert answer["place"]["name"] == "Lewisham"
    assert answer["place"]["matched_from"] == "postcode_district"
    assert "not a statistical area" in answer["warnings"][0]
    assert answer["privacy"]["sent_to_third_parties"]


def test_postcode_district_across_authorities(monkeypatch: pytest.MonkeyPatch) -> None:
    # "Bristol, City of" holds a comma, as the joined list from postcodes.io does.
    monkeypatch.setattr(
        places,
        "lookup_outcodes",
        lambda outcode: fakes.outcode_frame("Bristol, City of, County Durham, Cardiff"),
    )

    answer = describe_place("ZZ99")

    assert answer["status"] == "choose"
    assert {match["name"] for match in answer["matches"]} == {
        "Bristol, City of",
        "County Durham",
    }


def test_unknown_postcode_district(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        places, "lookup_outcodes", lambda outcode: fakes.outcode_frame(None)
    )

    assert describe_place("ZZ99")["status"] == "not_found"


def test_unreachable_source_is_reported_plainly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def offline(*args: object, **kwargs: object) -> object:
        raise requests.ConnectionError("no route")

    places.clear_cache()
    monkeypatch.setattr(places, "load_imd", offline)

    answer = describe_place("Lewisham")

    assert answer["status"] == "unavailable"
    assert "no route" not in json.dumps(answer)


def test_empty_place() -> None:
    assert describe_place("   ")["status"] == "not_found"


def test_answers_do_not_share_state() -> None:
    first = describe_place("Lewisham")
    first["caveats"].clear()
    first["sources"][0]["name"] = "changed"

    second = describe_place("Lewisham")

    assert second["caveats"]
    assert second["sources"][0]["name"].startswith("English Indices of Deprivation")


def _no_network(*args: object, **kwargs: object) -> object:
    """Stand in for postcodes.io and fail if it is asked anything."""
    raise AssertionError("postcodes.io was asked while a table is installed")


@pytest.fixture
def table_only(postcode_table: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """A postcode table is installed and postcodes.io must not be asked."""
    monkeypatch.setattr(places, "lookup_postcodes", _no_network)
    monkeypatch.setattr(places, "lookup_outcodes", _no_network)


@pytest.mark.usefixtures("table_only")
class TestWithAPostcodeTable:
    """With a table on this machine, no postcode is sent anywhere."""

    def test_postcode_is_placed_on_this_machine(self) -> None:
        answer = describe_place("zz99 9kc")

        assert answer["status"] == "found"
        assert answer["place"]["code"] == "E01000001"
        assert answer["place"]["matched_from"] == "postcode"
        assert answer["privacy"]["sent_to_third_parties"] == []
        assert "on this machine" in answer["privacy"]["notes"][-1]
        assert [source["id"] for source in answer["sources"]] == [
            "iod-2025",
            "ons-postcode-lookup",
        ]
        assert answer["sources"][1]["edition"] == "May 2026"
        assert "ZZ99" not in json.dumps(answer).upper()

    def test_unknown_postcode(self) -> None:
        answer = describe_place("ZZ99 7VC")

        assert answer["status"] == "not_found"
        assert "ZZ99" not in json.dumps(answer).upper()

    def test_welsh_postcode_is_not_covered(self) -> None:
        assert describe_place("CF10 1VC")["status"] == "not_covered"

    def test_postcode_district_across_authorities(self) -> None:
        answer = describe_place("ZZ99")

        assert answer["status"] == "choose"
        assert [match["code"] for match in answer["matches"]] == [
            "E08000021",
            "E09000023",
        ]
        assert answer["privacy"]["sent_to_third_parties"] == []

    def test_welsh_postcode_district_is_not_covered(self) -> None:
        assert describe_place("CF10")["status"] == "not_covered"

    def test_unknown_postcode_district(self) -> None:
        assert describe_place("AB1")["status"] == "not_found"


def test_damaged_postcode_table_is_reported_plainly(
    empty_data_dir, monkeypatch: pytest.MonkeyPatch
) -> None:
    empty_data_dir.mkdir(parents=True)
    (empty_data_dir / offline.TABLE_FILE_NAME).write_bytes(b"not a table")
    monkeypatch.setattr(places, "lookup_postcodes", _no_network)

    answer = describe_place(fakes.SECRET_POSTCODE)

    assert answer["status"] == "unavailable"
    assert "ZZ99" not in json.dumps(answer).upper()
