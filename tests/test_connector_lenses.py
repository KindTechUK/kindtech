"""Tests for the connector's "find a lens" and "run a lens on counts".

A fake lens engine that follows the lens contract stands in for
``kindtech.lenses``, and then the real lenses run on small invented figures.
"""

import json

import connector_fakes as fakes
import pytest
import requests

from kindtech.connector import PrivacyError, find_lens, run_lens_on_counts
from kindtech.lenses import need_reach

COUNTS = [
    {"lsoa_code": "E01000001", "count": 12},
    {"lsoa_code": "E01000002", "count": 30},
]


@pytest.mark.usefixtures("lens_engine")
class TestFindLens:
    def test_lists_every_lens_without_a_query(self) -> None:
        answer = find_lens()

        assert [lens["id"] for lens in answer["lenses"]] == [
            "reach-deprivation",
            "volunteer-travel",
        ]
        assert answer["matched"] == 0
        assert answer["available"] == 2
        assert "note" not in answer

    def test_best_match_comes_first(self) -> None:
        answer = find_lens("How far do volunteers travel to us?")

        assert [lens["id"] for lens in answer["lenses"]] == ["volunteer-travel"]
        assert answer["matched"] == 1

    def test_word_endings_do_not_matter(self) -> None:
        answer = find_lens("deprivation reach")

        assert answer["lenses"][0]["id"] == "reach-deprivation"

    def test_no_match_lists_every_lens_and_says_so(self) -> None:
        answer = find_lens("xylophone")

        assert len(answer["lenses"]) == 2
        assert answer["matched"] == 0
        assert "every lens is listed" in answer["note"]

    def test_lens_descriptions_are_passed_through_unchanged(self) -> None:
        lens = find_lens("deprived")["lenses"][0]

        assert lens["input_modes"][1] == {
            "name": "neighbourhood_counts",
            "description": "Already totalled by neighbourhood",
            "roles": ["lsoa_code", "count"],
            "aggregated": True,
        }


@pytest.mark.usefixtures("lens_engine")
class TestRunLensOnCounts:
    def test_runs_and_leaves_out_detail_rows(self) -> None:
        answer = run_lens_on_counts("reach-deprivation", COUNTS)

        assert answer["status"] == "ok"
        assert answer["result"]["figures"][0]["value"] == 42
        assert answer["result"]["tables"][0]["rows"] == []
        assert "checks" in answer["show_with_figures"]

    def test_options_reach_the_lens(self) -> None:
        answer = run_lens_on_counts(
            "reach-deprivation", COUNTS, options={"suppress_below": 10}
        )

        assert answer["result"]["privacy"]["suppress_below"] == 10

    def test_unknown_lens_lists_the_known_ones(self) -> None:
        answer = run_lens_on_counts("no-such-lens", COUNTS)

        assert answer["status"] == "unknown_lens"
        assert answer["known_lenses"] == ["reach-deprivation", "volunteer-travel"]

    def test_rows_about_people_are_refused_without_repeating_them(self) -> None:
        answer = run_lens_on_counts("reach-deprivation", [{"postcode": "ZZ99 9KC"}])

        assert answer["status"] == "input_problem"
        assert "(lsoa_code, count)" in answer["problems"][0]
        assert "ZZ99" not in json.dumps(answer)

    def test_extra_keys_are_refused(self) -> None:
        rows = [{"lsoa_code": "E01000001", "count": 3, "name": "A person"}]

        answer = run_lens_on_counts("reach-deprivation", rows)

        assert answer["status"] == "input_problem"
        assert "A person" not in json.dumps(answer)

    def test_lens_without_a_counts_mode(self) -> None:
        answer = run_lens_on_counts("volunteer-travel", COUNTS)

        assert answer == {
            "status": "input_problem",
            "problems": ["This lens cannot run on counts yet."],
        }

    @pytest.mark.parametrize("counts", [[], "E01000001", None, ["E01000001"]])
    def test_malformed_counts(self, counts: object) -> None:
        answer = run_lens_on_counts("reach-deprivation", counts)  # type: ignore[arg-type]

        assert answer["status"] == "input_problem"

    def test_problems_from_the_lens_are_passed_on(self) -> None:
        rows = [{"lsoa_code": "E01000001", "count": "many"}]

        answer = run_lens_on_counts("reach-deprivation", rows)

        assert answer == {
            "status": "input_problem",
            "problems": ["Some counts are not whole numbers."],
        }


@pytest.mark.usefixtures("leaky_lens_engine")
def test_result_that_repeats_an_input_value_is_withheld() -> None:
    with pytest.raises(PrivacyError) as raised:
        run_lens_on_counts("reach-deprivation", COUNTS)

    assert "E01000001" not in str(raised.value)
    assert "warnings[0]" in str(raised.value)


@pytest.mark.usefixtures("leaky_lens_engine")
class TestReportedRoles:
    """A lens may list the public places it was given, and nothing else."""

    def test_a_place_in_a_reported_role_may_come_back(self) -> None:
        rows = [{"local_authority": "Lewisham", "count": 12}]

        answer = run_lens_on_counts("reach-by-council", rows)

        assert answer["status"] == "ok"
        assert answer["result"]["warnings"] == ["Lewisham looks unusual"]

    @pytest.mark.parametrize("postcode", ["ZZ99 9KC", "zz999kc"])
    def test_a_postcode_in_a_reported_role_is_still_withheld(
        self, postcode: str
    ) -> None:
        rows = [{"local_authority": postcode, "count": 12}]

        with pytest.raises(PrivacyError) as raised:
            run_lens_on_counts("reach-by-council", rows)

        assert "ZZ99" not in str(raised.value).upper()


def test_a_problem_that_repeats_an_input_value_is_withheld(
    lens_engine: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    def run_lens(lens_id: str, data: list[dict], **_: object) -> None:
        raise fakes.LensInputError([f"{data[0]['lsoa_code']} is not a known area."])

    monkeypatch.setattr("kindtech.connector.lenses.engine.run_lens", run_lens)

    with pytest.raises(PrivacyError) as raised:
        run_lens_on_counts("reach-deprivation", COUNTS)

    assert "E01000001" not in str(raised.value)


@pytest.mark.usefixtures("england")
class TestWithTheRealLens:
    """The connector against ``kindtech.lenses`` and its first lens."""

    def test_finds_the_first_lens(self) -> None:
        answer = find_lens("are we reaching deprived neighbourhoods")

        assert answer["lenses"][0]["id"] == "reach-deprivation"
        modes = {m["name"]: m for m in answer["lenses"][0]["input_modes"]}
        assert modes["neighbourhood_counts"]["aggregated"] is True
        assert modes["postcodes"]["aggregated"] is False

    def test_runs_on_neighbourhood_counts(self) -> None:
        answer = run_lens_on_counts("reach-deprivation", COUNTS)

        result = answer["result"]
        figures = {figure["id"]: figure["value"] for figure in result["figures"]}
        assert answer["status"] == "ok"
        assert result["input_mode"] == "neighbourhood_counts"
        assert figures["people_supplied"] == 42
        # Both neighbourhoods are in the most deprived 20% of the small England.
        assert figures["share_most_deprived_20"] == 100.0
        assert result["privacy"]["sent_to_third_parties"] == []
        assert result["checks"]
        assert result["sources"]

    def test_map_rows_are_left_out(self) -> None:
        result = run_lens_on_counts("reach-deprivation", COUNTS)["result"]

        detail = [table for table in result["tables"] if table["detail"]]
        assert detail
        assert all(table["rows"] == [] for table in detail)
        assert "E01000001" not in json.dumps(result)

    def test_rows_about_people_are_refused(self) -> None:
        answer = run_lens_on_counts("reach-deprivation", [{"postcode": "ZZ99 9KC"}])

        assert answer["status"] == "input_problem"
        assert "ZZ99" not in json.dumps(answer)

    def test_problems_from_the_lens_do_not_repeat_values(self) -> None:
        rows = [{"lsoa_code": "E01000001", "count": "a few dozen"}]

        answer = run_lens_on_counts("reach-deprivation", rows)

        assert answer["status"] == "input_problem"
        assert answer["problems"]
        assert "a few dozen" not in json.dumps(answer)

    def test_unknown_option_is_an_input_problem(self) -> None:
        answer = run_lens_on_counts(
            "reach-deprivation", COUNTS, options={"no_such_option": 1}
        )

        assert answer["status"] == "input_problem"

    def test_unknown_lens(self) -> None:
        answer = run_lens_on_counts("no-such-lens", COUNTS)

        assert answer["status"] == "unknown_lens"
        assert "reach-deprivation" in answer["known_lenses"]


COUNCIL_COUNTS = [
    {"local_authority": "Lewisham", "count": 120},
    {"local_authority": "E09000011", "count": 40},
]


class TestWithTheSecondLens:
    """The connector against the need against reach lens.

    The need figures are invented and kept in the test's data folder, so the
    lens asks Nomis for nothing.
    """

    @pytest.fixture(autouse=True)
    def _need(self) -> None:
        need_reach.keep_need_figures("unemployed", fakes.NEED, "invented for a test.")

    def test_runs_on_local_authority_counts(self) -> None:
        answer = run_lens_on_counts("need-reach", COUNCIL_COUNTS)

        result = answer["result"]
        assert answer["status"] == "ok"
        assert result["input_mode"] == "area_counts"
        assert result["privacy"]["sent_to_third_parties"] == []
        assert result["checks"]

    def test_the_places_passed_in_are_listed_in_the_result(self) -> None:
        answer = run_lens_on_counts(
            "need-reach", COUNCIL_COUNTS, options={"catchment": "England"}
        )

        tables = {table["id"]: table for table in answer["result"]["tables"]}
        listed = {row["geography_name"] for row in tables["priority_areas"]["rows"]}
        assert "Lewisham" in listed
        assert tables["by_local_authority"]["rows"] == []

    def test_rows_about_people_are_refused(self) -> None:
        answer = run_lens_on_counts("need-reach", [{"postcode": "ZZ99 9KC"}])

        assert answer["status"] == "input_problem"
        assert "(local_authority, count)" in answer["problems"][0]
        assert "ZZ99" not in json.dumps(answer)

    def test_a_postcode_given_as_a_place_does_not_come_back(self) -> None:
        rows = [*COUNCIL_COUNTS, {"local_authority": "ZZ99 9KC", "count": 7}]

        answer = run_lens_on_counts("need-reach", rows)

        assert answer["status"] == "ok"
        assert "ZZ99" not in json.dumps(answer)


def test_says_when_a_data_source_cannot_be_reached(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def no_network(*args: object, **kwargs: object) -> None:
        raise requests.ConnectionError("https://example.invalid/?geography=secret")

    monkeypatch.setattr(need_reach, "load_ons", no_network)

    answer = run_lens_on_counts("need-reach", COUNCIL_COUNTS)

    assert answer["status"] == "unavailable"
    assert "could not be reached" in answer["message"]
    assert "secret" not in json.dumps(answer) + caplog.text
