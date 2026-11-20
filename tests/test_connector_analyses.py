"""Tests for the connector's "find an analysis" and "run an analysis on counts".

A fake analysis engine that follows the analysis contract stands in for
``uk_open_data.analyses``, and then the real analyses run on small invented figures.
"""

import json
from types import SimpleNamespace

import connector_fakes as fakes
import pytest
import requests

from uk_open_data.analyses import _need, need_reach, who_we_miss
from uk_open_data.connector import (
    PrivacyError,
    analyses,
    find_analysis,
    run_analysis_on_counts,
)

COUNTS = [
    {"lsoa_code": "E01000001", "count": 12},
    {"lsoa_code": "E01000002", "count": 30},
]


@pytest.mark.usefixtures("analysis_engine")
class TestFindAnalysis:
    def test_lists_every_analysis_without_a_query(self) -> None:
        answer = find_analysis()

        assert [analysis["id"] for analysis in answer["analyses"]] == [
            "reach-deprivation",
            "volunteer-travel",
        ]
        assert answer["matched"] == 0
        assert answer["available"] == 2
        assert "note" not in answer

    def test_best_match_comes_first(self) -> None:
        answer = find_analysis("How far do volunteers travel to us?")

        assert [analysis["id"] for analysis in answer["analyses"]] == [
            "volunteer-travel"
        ]
        assert answer["matched"] == 1

    def test_word_endings_do_not_matter(self) -> None:
        answer = find_analysis("deprivation reach")

        assert answer["analyses"][0]["id"] == "reach-deprivation"

    def test_no_match_lists_every_analysis_and_says_so(self) -> None:
        answer = find_analysis("xylophone")

        assert len(answer["analyses"]) == 2
        assert answer["matched"] == 0
        assert "every analysis is listed" in answer["note"]

    def test_analysis_descriptions_are_passed_through_unchanged(self) -> None:
        analysis = find_analysis("deprived")["analyses"][0]

        assert analysis["input_modes"][1] == {
            "name": "neighbourhood_counts",
            "description": "Already totalled by neighbourhood",
            "roles": ["lsoa_code", "count"],
            "aggregated": True,
        }


@pytest.mark.usefixtures("analysis_engine")
class TestRunAnalysisOnCounts:
    def test_runs_and_leaves_out_detail_rows(self) -> None:
        answer = run_analysis_on_counts("reach-deprivation", COUNTS)

        assert answer["status"] == "ok"
        assert answer["result"]["figures"][0]["value"] == 42
        assert answer["result"]["tables"][0]["rows"] == []
        assert "checks" in answer["show_with_figures"]

    def test_a_result_with_no_answer_sentence_asks_for_none(self) -> None:
        # The stand-in result has no answer, as a result from an older engine.
        answer = run_analysis_on_counts("reach-deprivation", COUNTS)

        assert "open_with" not in answer

    def test_says_which_tables_have_their_rows_left_out(self) -> None:
        answer = run_analysis_on_counts("reach-deprivation", COUNTS)

        left_out = answer["rows_left_out"]
        assert left_out["tables"] == ["by_neighbourhood"]
        assert "not empty" in left_out["note"]
        # The stand-in result has no map, so the note does not speak of drawing one.
        assert "cannot be drawn" not in left_out["note"]

    def test_options_reach_the_analysis(self) -> None:
        answer = run_analysis_on_counts(
            "reach-deprivation", COUNTS, options={"suppress_below": 10}
        )

        assert answer["result"]["privacy"]["suppress_below"] == 10

    def test_unknown_analysis_lists_the_known_ones(self) -> None:
        answer = run_analysis_on_counts("no-such-analysis", COUNTS)

        assert answer["status"] == "unknown_analysis"
        assert answer["known_analyses"] == ["reach-deprivation", "volunteer-travel"]

    def test_rows_about_people_are_refused_without_repeating_them(self) -> None:
        answer = run_analysis_on_counts("reach-deprivation", [{"postcode": "ZZ99 9KC"}])

        assert answer["status"] == "input_problem"
        assert "(lsoa_code, count)" in answer["problems"][0]
        assert "ZZ99" not in json.dumps(answer)

    def test_extra_keys_are_refused(self) -> None:
        rows = [{"lsoa_code": "E01000001", "count": 3, "name": "A person"}]

        answer = run_analysis_on_counts("reach-deprivation", rows)

        assert answer["status"] == "input_problem"
        assert "A person" not in json.dumps(answer)

    def test_analysis_without_a_counts_mode(self) -> None:
        answer = run_analysis_on_counts("volunteer-travel", COUNTS)

        assert answer["status"] == "needs_rows"
        assert "cannot run in a chat" in answer["message"]
        assert "Evidence page or with the command line tool" in answer["message"]

    def test_find_analysis_says_which_analyses_cannot_run_on_totals(self) -> None:
        answer = find_analysis()

        assert answer["needs_rows"]["analyses"] == ["volunteer-travel"]
        assert answer["needs_rows"]["note"] == analyses.NEEDS_ROWS

    def test_find_analysis_says_nothing_of_it_when_every_listed_analysis_can(
        self,
    ) -> None:
        assert "needs_rows" not in find_analysis("deprived neighbourhoods")

    @pytest.mark.parametrize("counts", [[], "E01000001", None, ["E01000001"]])
    def test_malformed_counts(self, counts: object) -> None:
        answer = run_analysis_on_counts("reach-deprivation", counts)  # type: ignore[arg-type]

        assert answer["status"] == "input_problem"

    def test_problems_from_the_analysis_are_passed_on(self) -> None:
        rows = [{"lsoa_code": "E01000001", "count": "many"}]

        answer = run_analysis_on_counts("reach-deprivation", rows)

        assert answer == {
            "status": "input_problem",
            "problems": ["Some counts are not whole numbers."],
            "role": "count",
        }


@pytest.mark.usefixtures("analysis_engine")
class TestCountsGivenAsText:
    """An assistant often sends a count as text, and it is still a count."""

    @pytest.mark.parametrize("count", ["1200", " 1200 ", "1,200"])
    def test_a_count_given_as_text_is_read_as_a_number(self, count: str) -> None:
        rows = [{"lsoa_code": "E01000001", "count": count}, COUNTS[1]]

        answer = run_analysis_on_counts("reach-deprivation", rows)

        assert answer["status"] == "ok"
        assert answer["result"]["figures"][0]["value"] == 1230

    @pytest.mark.parametrize("count", ["12oo", "-1200", "0123", "1,2,3", "12.5", ""])
    def test_other_text_is_left_for_the_analysis_to_refuse(self, count: str) -> None:
        rows = [{"lsoa_code": "E01000001", "count": count}]

        answer = run_analysis_on_counts("reach-deprivation", rows)

        assert answer == {
            "status": "input_problem",
            "problems": ["Some counts are not whole numbers."],
            "role": "count",
        }

    @pytest.mark.parametrize("marker", [{"amount": False}, {}])
    def test_a_role_the_analysis_does_not_mark_as_an_amount_stays_text(
        self, marker: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The example of the count role is a number, and that is not enough.
        roles = [
            {key: value for key, value in role.items() if key != "amount"} | marker
            for role in fakes.REACH["roles"]
        ]
        unmarked = SimpleNamespace(
            id="reach-deprivation", to_dict=lambda: {**fakes.REACH, "roles": roles}
        )
        monkeypatch.setattr(
            "uk_open_data.connector.analyses.engine.describe_analysis",
            lambda analysis_id: unmarked,
        )
        rows = [{"lsoa_code": "E01000001", "count": "1200"}]

        answer = run_analysis_on_counts("reach-deprivation", rows)

        assert answer == {
            "status": "input_problem",
            "problems": ["Some counts are not whole numbers."],
            "role": "count",
        }

    def test_the_rows_passed_in_are_not_changed(self) -> None:
        rows = [{"lsoa_code": "E01000001", "count": "1200"}]

        run_analysis_on_counts("reach-deprivation", rows)

        assert rows == [{"lsoa_code": "E01000001", "count": "1200"}]


@pytest.mark.usefixtures("leaky_analysis_engine")
def test_a_number_given_where_a_name_belongs_is_still_guarded() -> None:
    rows = [{"lsoa_code": "120045", "count": 12}]

    with pytest.raises(PrivacyError) as raised:
        run_analysis_on_counts("reach-deprivation", rows)

    assert "120045" not in str(raised.value)


@pytest.mark.usefixtures("leaky_analysis_engine")
def test_result_that_repeats_an_input_value_is_withheld() -> None:
    with pytest.raises(PrivacyError) as raised:
        run_analysis_on_counts("reach-deprivation", COUNTS)

    assert "E01000001" not in str(raised.value)
    assert "warnings[0]" in str(raised.value)


@pytest.mark.usefixtures("leaky_analysis_engine")
class TestReportedRoles:
    """An analysis may list the public places it was given, and nothing else."""

    def test_a_place_in_a_reported_role_may_come_back(self) -> None:
        rows = [{"local_authority": "Lewisham", "count": 12}]

        answer = run_analysis_on_counts("reach-by-council", rows)

        assert answer["status"] == "ok"
        assert answer["result"]["warnings"] == ["Lewisham looks unusual"]

    @pytest.mark.parametrize("postcode", ["ZZ99 9KC", "zz999kc"])
    def test_a_postcode_in_a_reported_role_is_still_withheld(
        self, postcode: str
    ) -> None:
        rows = [{"local_authority": postcode, "count": 12}]

        with pytest.raises(PrivacyError) as raised:
            run_analysis_on_counts("reach-by-council", rows)

        assert "ZZ99" not in str(raised.value).upper()

    @pytest.mark.parametrize("group", ["White", " white ", "OTHER"])
    def test_a_value_the_role_lists_may_come_back(self, group: str) -> None:
        answer = run_analysis_on_counts(
            "reach-by-group", [{"group": group, "count": 12}]
        )

        assert answer["status"] == "ok"
        assert answer["result"]["warnings"] == [f"{group} looks unusual"]

    @pytest.mark.parametrize(
        "label",
        ["Black Caribbean", "White British", "Zebedee Quillfeather", "ZZ99 9KC"],
    )
    def test_a_value_the_role_does_not_list_is_withheld(self, label: str) -> None:
        rows = [{"group": label, "count": 12}]

        with pytest.raises(PrivacyError) as raised:
            run_analysis_on_counts("reach-by-group", rows)

        assert label not in str(raised.value)


def test_a_problem_that_repeats_an_input_value_is_withheld(
    analysis_engine: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    def run_analysis(analysis_id: str, data: list[dict], **_: object) -> None:
        raise fakes.AnalysisInputError([f"{data[0]['lsoa_code']} is not a known area."])

    monkeypatch.setattr(
        "uk_open_data.connector.analyses.engine.run_analysis", run_analysis
    )

    with pytest.raises(PrivacyError) as raised:
        run_analysis_on_counts("reach-deprivation", COUNTS)

    assert "E01000001" not in str(raised.value)


@pytest.mark.usefixtures("england")
class TestWithTheRealAnalysis:
    """The connector against ``uk_open_data.analyses`` and its first analysis."""

    def test_finds_the_first_analysis(self) -> None:
        answer = find_analysis("are we reaching deprived neighbourhoods")

        assert answer["analyses"][0]["id"] == "reach-deprivation"
        modes = {m["name"]: m for m in answer["analyses"][0]["input_modes"]}
        assert modes["neighbourhood_counts"]["aggregated"] is True
        assert modes["postcodes"]["aggregated"] is False

    def test_runs_on_neighbourhood_counts(self) -> None:
        answer = run_analysis_on_counts("reach-deprivation", COUNTS)

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

    def test_the_code_and_the_figures_before_rounding_come_through(self) -> None:
        answer = run_analysis_on_counts("reach-deprivation", COUNTS)

        result = answer["result"]
        exact = {figure["id"]: figure["exact"] for figure in result["figures"]}
        assert answer["status"] == "ok"
        assert 'run_analysis(\n    "reach-deprivation"' in result["code"]
        # 12 of 42 people: shown as 28.6, kept as it was worked out.
        assert exact["share_most_deprived_10"] == pytest.approx(100 * 12 / 42)
        assert exact["people_supplied"] is None
        # The code names roles and leaves the person's column names blank.
        for row in COUNTS:
            assert row["lsoa_code"] not in result["code"]

    def test_the_answer_sentence_comes_through_to_open_the_reply(self) -> None:
        answer = run_analysis_on_counts("reach-deprivation", COUNTS)

        result = answer["result"]
        assert result["answer"].startswith("Of your people in the area you serve")
        assert "share_most_deprived_20" in result["key_figures"]
        assert "result.answer, in its exact words" in answer["open_with"]
        assert "result.key_figures" in answer["open_with"]

    def test_map_rows_are_left_out(self) -> None:
        result = run_analysis_on_counts("reach-deprivation", COUNTS)["result"]

        detail = [table for table in result["tables"] if table["detail"]]
        assert detail
        assert all(table["rows"] == [] for table in detail)
        assert "E01000001" not in json.dumps(result)

    def test_rows_about_people_are_refused(self) -> None:
        answer = run_analysis_on_counts("reach-deprivation", [{"postcode": "ZZ99 9KC"}])

        assert answer["status"] == "input_problem"
        assert "ZZ99" not in json.dumps(answer)

    def test_problems_from_the_analysis_do_not_repeat_values(self) -> None:
        rows = [{"lsoa_code": "E01000001", "count": "a few dozen"}]

        answer = run_analysis_on_counts("reach-deprivation", rows)

        assert answer["status"] == "input_problem"
        assert answer["problems"]
        assert "a few dozen" not in json.dumps(answer)

    def test_unknown_option_is_an_input_problem(self) -> None:
        answer = run_analysis_on_counts(
            "reach-deprivation", COUNTS, options={"no_such_option": 1}
        )

        assert answer["status"] == "input_problem"

    def test_unknown_analysis(self) -> None:
        answer = run_analysis_on_counts("no-such-analysis", COUNTS)

        assert answer["status"] == "unknown_analysis"
        assert "reach-deprivation" in answer["known_analyses"]


# Three people in one neighbourhood: the analysis hides that count and one more.
SMALL_COUNTS = [
    {"lsoa_code": "E01000001", "count": 3},
    {"lsoa_code": "E01000002", "count": 30},
    {"lsoa_code": "E01000003", "count": 40},
]


@pytest.mark.usefixtures("england")
class TestCountsThatWouldBeHidden:
    """The connector says so before it shows a result that hides counts."""

    def test_the_answer_is_held_back_and_says_what_would_be_hidden(self) -> None:
        answer = run_analysis_on_counts("reach-deprivation", SMALL_COUNTS)

        assert set(answer) == {"status", "message", "would_hide", "choices"}
        assert answer["status"] == "would_hide_counts"
        # One headline share and two rows of the table by decile.
        assert answer["would_hide"] == {"figures_and_rows": 3, "counts_below": 5}
        assert "from 1 to 4" in answer["message"]
        assert "hides a second" in answer["message"]

    def test_the_person_is_offered_both_ways_on(self) -> None:
        combine, run = run_analysis_on_counts("reach-deprivation", SMALL_COUNTS)[
            "choices"
        ]

        assert "under 5" in combine
        assert "neighbouring area" in combine
        assert "hidden_counts set to 'accept'" in run

    def test_it_repeats_nothing_from_the_rows(self) -> None:
        answer = json.dumps(run_analysis_on_counts("reach-deprivation", SMALL_COUNTS))

        for row in SMALL_COUNTS:
            assert row["lsoa_code"] not in answer
        assert "73" not in answer

    def test_accepting_returns_the_result_with_those_counts_hidden(self) -> None:
        answer = run_analysis_on_counts(
            "reach-deprivation", SMALL_COUNTS, hidden_counts="accept"
        )

        figures = answer["result"]["figures"]
        assert answer["status"] == "ok"
        assert [f["id"] for f in figures if f["suppressed"]] == [
            "share_most_deprived_10"
        ]
        # A hidden figure has no value before rounding either.
        assert [f["exact"] for f in figures if f["suppressed"]] == [None]

    def test_combining_the_small_count_leaves_nothing_to_ask_about(self) -> None:
        combined = [
            {"lsoa_code": "E01000002", "count": 33},
            {"lsoa_code": "E01000003", "count": 40},
        ]

        answer = run_analysis_on_counts("reach-deprivation", combined)

        assert answer["status"] == "ok"
        assert not any(f["suppressed"] for f in answer["result"]["figures"])

    def test_an_analysis_that_hides_nothing_never_asks(self) -> None:
        need_reach.keep_need_figures("residents", fakes.NEED, "invented for a test.")

        answer = run_analysis_on_counts(
            "provision-gap", [{"local_authority": "Lewisham", "volume": 2}]
        )

        assert answer["status"] == "ok"


COUNCIL_COUNTS = [
    {"local_authority": "Lewisham", "count": 120},
    {"local_authority": "E09000011", "count": 40},
]


class TestWithTheSecondAnalysis:
    """The connector against the need against reach analysis.

    The need figures are invented and kept in the test's data folder, so the
    analysis asks Nomis for nothing.
    """

    @pytest.fixture(autouse=True)
    def _need(self) -> None:
        need_reach.keep_need_figures("unemployed", fakes.NEED, "invented for a test.")

    def test_runs_on_local_authority_counts(self) -> None:
        answer = run_analysis_on_counts("need-reach", COUNCIL_COUNTS)

        result = answer["result"]
        assert answer["status"] == "ok"
        assert result["input_mode"] == "area_counts"
        assert result["privacy"]["sent_to_third_parties"] == []
        assert result["checks"]

    def test_says_the_map_cannot_be_drawn_without_the_rows_left_out(self) -> None:
        answer = run_analysis_on_counts("need-reach", COUNCIL_COUNTS)

        left_out = answer["rows_left_out"]
        assert left_out["tables"] == ["by_local_authority"]
        assert answer["result"]["map"]["table"] == "by_local_authority"
        assert "cannot be drawn from this answer" in left_out["note"]

    def test_the_places_passed_in_are_listed_in_the_result(self) -> None:
        answer = run_analysis_on_counts(
            "need-reach", COUNCIL_COUNTS, options={"catchment": "England"}
        )

        tables = {table["id"]: table for table in answer["result"]["tables"]}
        listed = {row["geography_name"] for row in tables["priority_areas"]["rows"]}
        assert "Lewisham" in listed
        assert tables["by_local_authority"]["rows"] == []

    def test_a_count_given_as_text_gives_the_same_answer(self) -> None:
        # 9,000 is also Lewisham's need figure, so as text the count used to
        # be found in the result and the whole answer withheld.
        as_number = [{"local_authority": "Lewisham", "count": 9000}]
        as_text = [{"local_authority": "Lewisham", "count": "9000"}]

        answer = run_analysis_on_counts("need-reach", as_text)

        assert answer["status"] == "ok"
        assert answer == run_analysis_on_counts("need-reach", as_number)

    def test_rows_about_people_are_refused(self) -> None:
        answer = run_analysis_on_counts("need-reach", [{"postcode": "ZZ99 9KC"}])

        assert answer["status"] == "input_problem"
        assert "(local_authority, count)" in answer["problems"][0]
        assert "ZZ99" not in json.dumps(answer)

    def test_a_postcode_given_as_a_place_does_not_come_back(self) -> None:
        rows = [*COUNCIL_COUNTS, {"local_authority": "ZZ99 9KC", "count": 7}]

        answer = run_analysis_on_counts("need-reach", rows)

        assert answer["status"] == "ok"
        assert "ZZ99" not in json.dumps(answer)


GROUP_COUNTS = [
    {"group": "White British", "count": 220},
    {"group": "Black Caribbean", "count": 40},
    {"group": "Asian", "count": 30},
]
CATCHMENT = {"catchment": ["Lewisham"]}


class TestWithTheThirdAnalysis:
    """The connector against the who we are missing analysis.

    The census figures are invented and kept in the test's data folder, so the
    analysis asks Nomis for nothing.
    """

    @pytest.fixture(autouse=True)
    def _residents(self) -> None:
        who_we_miss.keep_residents(
            "ethnic_group", fakes.RESIDENTS, "invented for a test."
        )

    def test_is_found_by_its_question(self) -> None:
        answer = find_analysis("which ethnic groups are we missing?")

        assert answer["analyses"][0]["id"] == "who-we-miss"

    def test_says_which_option_holds_the_persons_own_labels(self) -> None:
        answer = find_analysis("which ethnic groups are we missing?")

        options = {o["name"]: o for o in answer["analyses"][0]["options"]}
        assert options["groups"]["private"] is True
        assert options["catchment"]["private"] is False

    def test_runs_on_group_counts(self) -> None:
        answer = run_analysis_on_counts("who-we-miss", GROUP_COUNTS, options=CATCHMENT)

        result = answer["result"]
        rows = {row["group"]: row for row in result["tables"][0]["rows"]}
        assert answer["status"] == "ok"
        assert result["input_mode"] == "group_counts"
        assert result["privacy"]["sent_to_third_parties"] == []
        # 40 of 290 people against a quarter of residents.
        assert rows["Black"]["people"] == 40
        assert rows["Black"]["under_represented"] is True

    def test_says_nothing_of_rows_left_out_when_none_are(self) -> None:
        answer = run_analysis_on_counts("who-we-miss", GROUP_COUNTS, options=CATCHMENT)

        assert answer["result"]["tables"][0]["rows"]
        assert "rows_left_out" not in answer

    def test_names_census_groups_and_not_the_labels_passed_in(self) -> None:
        answer = run_analysis_on_counts("who-we-miss", GROUP_COUNTS, options=CATCHMENT)

        reply = json.dumps(answer)
        assert "White" in reply
        assert "White British" not in reply
        assert "Black Caribbean" not in reply

    def test_says_when_the_catchment_is_missing(self) -> None:
        answer = run_analysis_on_counts("who-we-miss", GROUP_COUNTS)

        assert answer["status"] == "input_problem"
        assert "'Area you serve'" in answer["problems"][0]
        # The sentence gives the label a person reads; this is the name to pass.
        assert answer["option"] == "catchment"
        assert "role" not in answer

    def test_rows_about_people_are_refused(self) -> None:
        rows = [{"group": "White", "postcode": "ZZ99 9KC"}]

        answer = run_analysis_on_counts("who-we-miss", rows, options=CATCHMENT)

        assert answer["status"] == "input_problem"
        assert "(group, count)" in answer["problems"][0]
        assert "ZZ99" not in json.dumps(answer)

    def test_a_label_that_is_not_a_group_does_not_come_back(self) -> None:
        rows = [
            *GROUP_COUNTS,
            {"group": "Zebedee Quillfeather", "count": 6},
            {"group": "ZZ99 9KC", "count": 9},
        ]

        answer = run_analysis_on_counts("who-we-miss", rows, options=CATCHMENT)

        reply = json.dumps(answer)
        assert answer["status"] == "ok"
        assert "Quillfeather" not in reply
        assert "ZZ99" not in reply

    def test_the_code_to_run_it_again_holds_no_label_of_the_persons_own(self) -> None:
        rows = [*GROUP_COUNTS, {"group": "Zebedee Quillfeather", "count": 6}]
        own_labels = {**CATCHMENT, "groups": {"Zebedee Quillfeather": "Other"}}

        answer = run_analysis_on_counts("who-we-miss", rows, options=own_labels)

        code = answer["result"]["code"]
        assert answer["status"] == "ok"
        assert 'run_analysis(\n    "who-we-miss"' in code
        assert '"groups": {}' in code
        assert "Lewisham" in code
        assert "Quillfeather" not in json.dumps(answer)


VOLUMES = [
    {"local_authority": "Lewisham", "volume": 1200},
    {"local_authority": "E09000011", "volume": 2.5},
]


class TestWithTheFourthAnalysis:
    """The connector against the provision gap analysis.

    The need figures are invented and kept in the test's data folder, so the
    analysis asks Nomis for nothing.
    """

    @pytest.fixture(autouse=True)
    def _need(self) -> None:
        need_reach.keep_need_figures("residents", fakes.NEED, "invented for a test.")

    def test_is_found_by_its_question(self) -> None:
        answer = find_analysis("where is provision thin against need?")

        assert answer["analyses"][0]["id"] == "provision-gap"

    def test_runs_on_volumes_by_local_authority(self) -> None:
        answer = run_analysis_on_counts("provision-gap", VOLUMES)

        result = answer["result"]
        figures = {figure["id"]: figure["value"] for figure in result["figures"]}
        assert answer["status"] == "ok"
        assert result["input_mode"] == "area_volumes"
        assert result["privacy"]["sent_to_third_parties"] == []
        assert figures["volume_supplied"] == 1202.5
        assert figures["areas_without_provision"] == 14

    def test_lists_the_places_to_look_at_and_leaves_out_the_detail(self) -> None:
        answer = run_analysis_on_counts("provision-gap", VOLUMES)

        tables = {table["id"]: table for table in answer["result"]["tables"]}
        first = tables["priority_areas"]["rows"][0]
        assert first["geography_name"] == "Birmingham"
        assert first["volume"] == 0
        assert tables["by_local_authority"]["rows"] == []

    @pytest.mark.parametrize("volume", ["1200", "1,200", "1200.0"])
    def test_a_volume_given_as_text_gives_the_same_answer(self, volume: str) -> None:
        as_text = [{"local_authority": "Lewisham", "volume": volume}, VOLUMES[1]]

        answer = run_analysis_on_counts("provision-gap", as_text)

        assert answer == run_analysis_on_counts("provision-gap", VOLUMES)

    def test_a_volume_that_is_not_a_number_is_counted_and_not_repeated(self) -> None:
        rows = [*VOLUMES, {"local_authority": "Lewisham", "volume": "a lot of hours"}]

        answer = run_analysis_on_counts("provision-gap", rows)

        assert answer["status"] == "input_problem"
        assert answer["problems"][0].startswith("1 row had provision that")
        assert "a lot" not in json.dumps(answer)

    @pytest.mark.parametrize(
        "rows",
        [
            [{"postcode": "ZZ99 9KC", "volume": 30}],
            [{"postcode": "ZZ99 9KC"}],
        ],
    )
    def test_one_row_per_site_is_refused(self, rows: list[dict]) -> None:
        answer = run_analysis_on_counts("provision-gap", rows)

        assert answer["status"] == "input_problem"
        assert "(local_authority, volume)" in answer["problems"][0]
        assert "per site" in answer["problems"][0]
        assert "ZZ99" not in json.dumps(answer)

    def test_a_postcode_given_as_a_place_does_not_come_back(self) -> None:
        rows = [*VOLUMES, {"local_authority": "ZZ99 9KC", "volume": 7}]

        answer = run_analysis_on_counts("provision-gap", rows)

        assert answer["status"] == "ok"
        assert "ZZ99" not in json.dumps(answer)

    def test_an_option_out_of_range_is_an_input_problem(self) -> None:
        answer = run_analysis_on_counts("provision-gap", VOLUMES, options={"top": 99})

        assert answer["status"] == "input_problem"
        assert "'Places listed'" in answer["problems"][0]


SITES = [{"latitude": 51.4613, "longitude": -0.0117}]


@pytest.mark.parametrize("rows", [SITES, COUNTS, [{"postcode": "ZZ99 9KC"}], []])
def test_the_fifth_analysis_says_plainly_that_it_cannot_run_in_a_chat(
    rows: list[dict],
) -> None:
    answer = run_analysis_on_counts("access-distance", rows)

    assert answer == {"status": "needs_rows", "message": analyses.NEEDS_ROWS}


def test_find_analysis_names_the_fifth_analysis_as_one_that_needs_rows() -> None:
    answer = find_analysis()

    assert answer["needs_rows"]["analyses"] == ["access-distance"]


@pytest.mark.parametrize(
    ("module", "analysis_id", "counts", "options"),
    [
        # The need figures are fetched in the shared need module.
        (_need, "need-reach", COUNCIL_COUNTS, None),
        (who_we_miss, "who-we-miss", GROUP_COUNTS, CATCHMENT),
        (_need, "provision-gap", VOLUMES, None),
    ],
)
def test_says_when_a_data_source_cannot_be_reached(
    module: object,
    analysis_id: str,
    counts: list[dict],
    options: dict | None,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def no_network(*args: object, **kwargs: object) -> None:
        raise requests.ConnectionError("https://example.invalid/?geography=secret")

    monkeypatch.setattr(module, "load_ons", no_network)

    answer = run_analysis_on_counts(analysis_id, counts, options=options)

    assert answer["status"] == "unavailable"
    assert "could not be reached" in answer["message"]
    assert "secret" not in json.dumps(answer) + caplog.text
