"""
Unit tests for the need against reach analysis.

The need figures and the postcode lookup are replaced with small invented
tables, so the tests are isolated and repeatable.
"""

import json
import re
import unittest.mock as mock
import xml.etree.ElementTree as ET

import pandas as pd
import pytest
from working_checks import check_working, worked_out

from uk_open_data.analyses import (
    AnalysisInputError,
    describe_analysis,
    load_map_boundaries,
    render_map,
    run_analysis,
)
from uk_open_data.analyses._need import (
    FEW_PLACES,
    ONE_PLACE,
    equal_parts,
    few_places,
    high_need_cut,
)
from uk_open_data.analyses.need_reach import (
    NEED_BANDS,
    NO_REACH,
    REACH_BANDS,
    clear_need_cache,
    download_need_figures,
    keep_need_figures,
    need_figures_path,
)
from uk_open_data.cli import EXIT_OK, main
from uk_open_data.postcodes import build_postcode_table, install_postcode_table

ANALYSIS_ID = "need-reach"
EVERYWHERE = "England and Wales"
COLUMNS = {"local_authority": "Area", "count": "Clients"}

# Invented need figures for real local authority codes. There are sixteen, so
# the top quarter is the last four, and those are high need.
NEED = (
    ("E06000002", "Middlesbrough", 100),
    ("E06000003", "Redcar and Cleveland", 200),
    ("E06000004", "Stockton-on-Tees", 300),
    ("E06000005", "Darlington", 400),
    ("E06000006", "Halton", 500),
    ("E06000007", "Warrington", 600),
    ("E06000008", "Blackburn with Darwen", 700),
    ("E06000009", "Blackpool", 800),
    ("E06000053", "Isles of Scilly", 20),
    ("E07000223", "Adur", 1000),
    ("E06000001", "Hartlepool", 3000),
    ("E09000011", "Greenwich", 8000),
    ("E09000023", "Lewisham", 9000),
    ("W06000015", "Cardiff", 10000),
    ("E08000003", "Manchester", 20000),
    ("E08000025", "Birmingham", 40000),
)
HIGH_NEED = {"Lewisham", "Cardiff", "Manchester", "Birmingham"}
RESIDENTS_TABLE = "NM_2028_1"
# Invented residents: fifty for each person in need, but for the place with
# most need, which is so large that its rate is the lowest, and the place with
# least, which is so small that its rate is the highest.
RESIDENTS = {name: need * 50 for _, name, need in NEED} | {
    "Birmingham": 40000 * 200,
    "Isles of Scilly": 20 * 10,
}


class _Nomis:
    """Stands in for Nomis and records what it was asked."""

    def __init__(self) -> None:
        self.asked: list[tuple[str, dict]] = []
        # Residents by place name, given when the table of residents is asked
        # for. A place with none here has as many residents as people in need.
        self.residents: dict[str, int] = {}

    def load(self, dataset: str, **query) -> pd.DataFrame:
        """Return each authority's need split over four rows, as Nomis would."""
        self.asked.append((dataset, query))
        people = self.residents if dataset == RESIDENTS_TABLE else {}
        rows = [
            {
                "geography_code": code,
                "geography_name": name,
                "obs_value": people.get(name, need) / 4,
            }
            for code, name, need in NEED
            for _ in range(4)
        ]
        rows.append(
            {"geography_code": "S12000036", "geography_name": "x", "obs_value": 5}
        )
        return pd.DataFrame(rows)


@pytest.fixture
def nomis():
    """Replace the need figures with the invented ones."""
    fake = _Nomis()
    with mock.patch("uk_open_data.analyses._need.load_ons", side_effect=fake.load):
        yield fake


def _counts(**people: int) -> list[dict]:
    """Rows of counts by local authority name, with the user's column names."""
    return [
        {"Area": name.replace("_", " "), "Clients": n} for name, n in people.items()
    ]


def _run(rows, options=None, columns=COLUMNS):
    return run_analysis(ANALYSIS_ID, rows, columns=columns, options=options)


def _run_wide(rows, options=None, columns=COLUMNS):
    """Run with every local authority compared, as when the area is named so."""
    return _run(rows, {"catchment": EVERYWHERE, **(options or {})}, columns)


def _names(table) -> list[str]:
    return [row["geography_name"] for row in table.rows]


# --- the analysis is listed ----------------------------------------------------


def test_analysis_is_described():
    info = describe_analysis(ANALYSIS_ID)
    assert info.question == "Where is need high and our presence low?"
    assert [mode.name for mode in info.input_modes] == ["postcodes", "area_counts"]
    assert info.input_modes[1].aggregated
    assert {option.name for option in info.options} == {
        "suppress_below",
        "postcode_lookup",
        "need",
        "catchment",
        "catchment_min_share",
        "top",
    }
    assert info.coverage == "England and Wales"
    # Local authorities are public places the result names. Nothing else may
    # come back from the input.
    reported = {role.name: role.reported for role in info.roles}
    assert reported == {"postcode": False, "local_authority": True, "count": False}


# --- counts by local authority ---------------------------------------------


def test_figures_from_counts(nomis):
    result = _run_wide(_counts(Lewisham=60, Greenwich=30, Adur=10))
    assert result.input_mode == "area_counts"
    assert result.figure("people_supplied").value == 100
    assert result.figure("people_located").value == 100
    assert result.figure("people_in_catchment").value == 100
    assert result.figure("areas_compared").value == 16
    assert result.figure("people_in_need").value == 94620
    assert result.figure("reach_per_100_in_need").value == 0.11
    assert result.figure("high_need_areas").value == 4
    assert result.figure("high_need_areas_without_people").value == 3
    assert result.figure("share_of_people_in_high_need_areas").value == 60.0
    assert result.figure("share_of_need_in_high_need_areas").value == 83.5


def test_need_is_added_up_for_england_and_wales_only(nomis):
    result = _run_wide(_counts(Lewisham=60))
    table = result.table("by_local_authority")
    assert len(table.rows) == len(NEED)
    assert {row["geography_code"][0] for row in table.rows} == {"E", "W"}
    lewisham = next(r for r in table.rows if r["geography_name"] == "Lewisham")
    assert lewisham["people_in_need"] == 9000
    assert lewisham["people_per_100_in_need"] == 0.67
    assert lewisham["high_need"] is True


def test_the_default_need_is_unemployment_from_the_census(nomis):
    result = _run(_counts(Lewisham=60))
    dataset, query = nomis.asked[0]
    assert dataset == "NM_2124_1"
    assert query["geography_type"] == "LAD"
    assert query["time"] == "latest"
    assert query["c2021_eastat_7"] == 2
    assert query["c_sex"] == [1, 2]
    assert query["c2021_age_7"] == [2, 3, 4, 5]
    source = result.sources[0]
    assert source.id == "nomis-nm_2124_1"
    assert "RM024" in source.name
    assert source.edition.startswith("Census 2021")
    assert any("21 March 2021" in caveat for caveat in result.caveats)


def test_need_figures_are_fetched_once_and_kept(nomis):
    # The first run fetches the need and the residents the map sets it against.
    _run(_counts(Lewisham=60))
    _run(_counts(Greenwich=30), options={"catchment": "England"})
    assert [dataset for dataset, _ in nomis.asked] == ["NM_2124_1", RESIDENTS_TABLE]
    _run(_counts(Lewisham=60), options={"need": "unemployed_women"})
    assert len(nomis.asked) == 3
    clear_need_cache()
    _run(_counts(Lewisham=60))
    assert len(nomis.asked) == 5


# --- the answer ------------------------------------------------------------


def test_answer_says_where_need_is_high_and_reach_is_low(nomis):
    result = _run_wide(_counts(Lewisham=60, Greenwich=30, Adur=10))
    assert result.answer == (
        "83.5% of the people in need live in the 4 local authorities with high "
        "need, and 60.0% of your people do. The places to look at first, with "
        "high need and your lowest reach, are Birmingham, Manchester and Cardiff."
    )
    assert result.key_figures == (
        "share_of_people_in_high_need_areas",
        "share_of_need_in_high_need_areas",
        "high_need_areas_without_people",
    )
    assert {figure.id for figure in result.figures} >= set(result.key_figures)
    assert result.to_dict()["answer"] == result.answer


def test_answer_says_when_the_area_was_worked_out(nomis):
    # A door may show the sentence and no warning, so the sentence says it.
    result = _run(_counts(Greenwich=30, Lewisham=60, Adur=10, Cardiff=3))
    assert result.answer.startswith(
        "In the 3 local authorities where most of your people live, "
    )
    named = _run(
        _counts(Greenwich=30, Lewisham=60, Adur=10),
        options={"catchment": ["Lewisham", "Greenwich", "Adur"]},
    )
    assert not named.answer.startswith("In the 3 local authorities")


def test_answer_says_how_many_people_are_not_counted_when_they_are_many(nomis):
    # A mistyped place holds 70 of 322 people: over a fifth are left out.
    rows = _counts(Lewisham=240, Grenwich=70, Adur=12)
    result = _run(rows, options={"catchment": ["Lewisham", "Adur"]})
    assert result.answer.endswith(
        " 70 of the 322 people in your data could not be placed in the area "
        "you serve and are not counted."
    )
    assert "Grenwich" not in json.dumps(result.to_dict())
    few = _run(
        _counts(Lewisham=240, Grenwich=7, Adur=12),
        options={"catchment": ["Lewisham", "Adur"]},
    )
    assert "are not counted" not in few.answer


def test_answer_tells_a_mistyped_place_from_one_outside_the_area(nomis):
    # A mistyped place is the person's to put right. People who live outside
    # the area are not a mistake. The sentence says how many of each.
    rows = _counts(Lewisham=240, Grenwich=70, Adur=12)
    result = _run(rows, options={"catchment": ["Lewisham"]})
    assert result.answer.endswith(
        " 82 of the 322 people in your data are not counted: 70 could not be "
        "placed in a local authority, and 12 live outside the area you serve."
    )


def test_the_list_says_what_it_is_in_order_of_and_no_more(nomis):
    # A place on a short list can have more reach than the area, so the
    # title does not call the list "the places to look at first".
    result = _run_wide(_counts(Lewisham=60, Greenwich=30, Adur=10))
    table = result.table("priority_areas")
    assert table.title == "Places with high need, your lowest reach first"
    assert table.headings["people_in_need"] == "People in need"


def test_labels_do_not_call_every_resident_a_need(nomis):
    result = _run_wide(
        _counts(Lewisham=60, Greenwich=30, Adur=10), options={"need": "residents"}
    )
    labels = {figure.id: figure.label for figure in result.figures}
    assert labels["people_in_need"] == (
        "People in the area you serve (Residents of every age)"
    )
    assert labels["high_need_areas"] == "Local authorities with the most residents"
    assert labels["share_of_need_in_high_need_areas"] == (
        "Share of residents who live in the local authorities with the most residents"
    )
    assert labels["high_need_areas_without_people"] == (
        "The local authorities with the most residents where you reached nobody"
    )
    table = result.table("priority_areas")
    assert table.title == "Places with the most residents, your lowest reach first"
    assert table.headings["people_in_need"] == "Residents"
    assert table.headings["people_per_100_in_need"] == "Your people per 100 residents"
    read = [*labels.values(), table.title, *table.headings.values()]
    assert not [text for text in read if "need" in text.lower()]
    choice = next(c for c in result.choices if c.id == "high_need")
    assert choice.label == "What counts as the most residents"
    assert choice.value == "In the top quarter of the area you serve, by residents"


def test_the_map_says_why_it_shades_by_count(nomis):
    by_count = _run_wide(
        _counts(Lewisham=60, Greenwich=30, Adur=10), options={"need": "residents"}
    )
    choice = next(c for c in by_count.choices if c.id == "map_need")
    assert choice.reason == (
        "The need is every resident, so there is no rate to work out."
    )


def test_answer_names_the_first_places_of_the_list_and_no_others(nomis):
    result = _run_wide(_counts(Lewisham=60, Greenwich=30, Adur=10), options={"top": 1})
    assert result.answer.endswith(
        "The place to look at first, with high need and your lowest reach, is "
        "Birmingham."
    )


def test_answer_does_not_give_away_a_hidden_share(nomis):
    # Birmingham is the only high-need place with people, so the share of
    # people in high-need places would be its count.
    result = _run_wide(_counts(Birmingham=3, Greenwich=30, Adur=20))
    # The rate across the area is not hidden, so it carries the answer.
    assert result.answer.startswith(
        "83.5% of the people in need live in the 4 local authorities with high "
        "need, and the share of your people who do is hidden to protect a small "
        "count. Across the area you reached 0.06 people per 100 in need."
    )
    # A hidden figure gives way to one that can be shown.
    assert result.key_figures == (
        "share_of_need_in_high_need_areas",
        "high_need_areas_without_people",
        "reach_per_100_in_need",
    )


def test_answer_does_not_name_a_place_with_a_hidden_count(nomis):
    result = _run_wide(_counts(Birmingham=3, Greenwich=30, Adur=20))
    assert "Birmingham" in _names(result.table("priority_areas"))
    assert "Birmingham" not in result.answer


def test_answer_does_not_name_a_place_reached_more_than_the_area(nomis):
    # Lewisham is the one high-need place of the three, and it is reached
    # more than the area as a whole, so it is no place to look at first.
    result = _run(_counts(Lewisham=240, Greenwich=80, Adur=5))
    assert _names(result.table("priority_areas")) == ["Lewisham"]
    assert "look at first" not in result.answer
    assert result.answer.endswith("of your people do.")


def test_answer_does_not_call_every_resident_a_need(nomis):
    result = _run_wide(
        _counts(Lewisham=60, Greenwich=30, Adur=10), options={"need": "residents"}
    )
    assert result.answer == (
        "83.5% of residents live in the 4 local authorities with the most "
        "residents, and 60.0% of your people do. The places to look at first, "
        "with the most residents and your lowest reach, are Birmingham, "
        "Manchester and Cardiff."
    )


# --- what counts as high need ----------------------------------------------


@pytest.mark.parametrize(
    ("need", "cut"),
    [
        ([7], 7),  # one place is the top quarter of one
        ([1, 2, 3], 3),  # at least one place, however few there are
        ([1, 2, 3, 4], 4),
        ([1, 2, 3, 4, 5], 4),  # a quarter of five is rounded up to two places
        (list(range(1, 17)), 13),  # four places of sixteen
        ([5, 5, 5, 5], 5),  # places that tie with the cut are all high need
    ],
)
def test_high_need_is_the_top_quarter_of_the_places_compared(need, cut):
    assert high_need_cut(need) == cut


def test_a_quarter_of_the_places_are_high_need_and_the_result_says_so(nomis):
    result = _run_wide(_counts(Lewisham=60, Greenwich=30, Adur=10))
    table = result.table("by_local_authority")
    assert {r["geography_name"] for r in table.rows if r["high_need"]} == HIGH_NEED
    assert result.figure("high_need_areas").value == len(NEED) // 4
    choice = next(c for c in result.choices if c.id == "high_need")
    assert choice.value == "In the top quarter of the area you serve, by people in need"
    step = next(s for s in result.working if s.title == "Set reach against need")
    assert "in the top quarter of the area (at or above 9,000)" in step.detail


# --- need figures kept on this machine -------------------------------------

INVENTED = [(code, name, need * 2) for code, name, need in NEED]


def test_kept_need_figures_are_used_and_nothing_is_fetched(nomis):
    assert need_figures_path() is None
    path = keep_need_figures("unemployed", INVENTED, "invented for a demonstration.")
    assert need_figures_path() == path
    result = _run_wide(_counts(Lewisham=60))
    assert nomis.asked == []
    assert result.figure("people_in_need").value == 189240
    source = result.sources[0]
    assert source.id == "nomis-nm_2124_1"
    assert source.edition.endswith(
        "A copy kept on this machine, invented for a demonstration."
    )
    assert "nothing was fetched" in result.working[0].detail


def test_each_need_keeps_its_own_figures(nomis):
    keep_need_figures("unemployed_women", INVENTED, "invented.")
    assert need_figures_path("unemployed_women") is not None
    assert need_figures_path("unemployed") is None
    _run(_counts(Lewisham=60))
    assert len(nomis.asked) == 2  # the need, and the residents for the map
    _run(_counts(Lewisham=60), options={"need": "unemployed_women"})
    assert len(nomis.asked) == 2


def test_download_fetches_and_keeps_the_figures(nomis):
    path = download_need_figures("unemployed_men")
    assert path == need_figures_path("unemployed_men")
    assert nomis.asked[0][1]["c_sex"] == [2]
    result = _run_wide(_counts(Lewisham=60), options={"need": "unemployed_men"})
    assert len(nomis.asked) == 1
    assert result.figure("people_in_need").value == 94620
    assert "fetched from Nomis on" in result.sources[0].edition


def test_only_built_in_needs_can_be_kept():
    with pytest.raises(ValueError, match="No need called 'poverty'"):
        keep_need_figures("poverty", INVENTED, "invented.")
    with pytest.raises(ValueError, match="No need called 'poverty'"):
        download_need_figures("poverty")
    assert need_figures_path("poverty") is None


def test_a_kept_file_that_cannot_be_read_is_an_input_error(nomis):
    path = keep_need_figures("unemployed", INVENTED, "invented.")
    path.write_text('{"format": "something else"}', encoding="utf-8")
    with pytest.raises(
        AnalysisInputError, match="kept on this machine could not be read"
    ):
        _run(_counts(Lewisham=60))
    assert nomis.asked == []


def test_built_in_needs_can_be_picked_from_a_list():
    need = {o.name: o for o in describe_analysis(ANALYSIS_ID).options}["need"]
    assert [(choice.value, choice.label) for choice in need.choices] == [
        (
            "unemployed",
            "Unemployed people aged 16 to 64, not counting full-time students",
        ),
        (
            "unemployed_women",
            "Unemployed women aged 16 to 64, not counting full-time students",
        ),
        (
            "unemployed_men",
            "Unemployed men aged 16 to 64, not counting full-time students",
        ),
        ("residents", "Residents of every age"),
    ]


def test_need_can_be_everyone_who_lives_there(nomis):
    result = _run(_counts(Lewisham=60), options={"need": "residents"})
    dataset, query = nomis.asked[0]
    assert dataset == "NM_2028_1"
    assert query["c_sex"] == 0
    assert query["measures"] == 20100
    assert result.figure("people_in_need").label.endswith("(Residents of every age)")
    assert result.sources[0].id == "nomis-nm_2028_1"
    assert any("Not all of them need" in caveat for caveat in result.caveats)
    path = keep_need_figures("residents", INVENTED, "invented.")
    assert need_figures_path("residents") == path


def test_need_can_be_women_only(nomis):
    result = _run(_counts(Lewisham=60), options={"need": "unemployed_women"})
    assert nomis.asked[0][1]["c_sex"] == [1]
    choice = next(c for c in result.choices if c.id == "need")
    assert choice.value == (
        "Unemployed women aged 16 to 64, not counting full-time students"
    )
    assert choice.option == "need"


@pytest.mark.parametrize("need", ["unemployed", "unemployed_women", "unemployed_men"])
def test_built_in_needs_say_that_full_time_students_are_not_counted(nomis, need):
    result = _run(_counts(Lewisham=60), options={"need": need})
    # Status 2 is unemployed people who are not full-time students.
    assert nomis.asked[0][1]["c2021_eastat_7"] == 2
    said = "not counting full-time students"
    assert said in next(c for c in result.choices if c.id == "need").value
    assert said in result.figure("people_in_need").label
    assert said in next(c for c in result.checks if c.id == "need_fits").question
    assert any("Full-time students" in caveat for caveat in result.caveats)


def test_need_can_be_another_nomis_table(nomis):
    need = {
        "dataset": "NM_2056_1",
        "label": "Disabled people",
        "filters": {"c2021_disability_5": [1, 2], "time": 2021},
    }
    result = _run(_counts(Lewisham=60), options={"need": need})
    dataset, query = nomis.asked[0]
    assert dataset == "NM_2056_1"
    assert query["c2021_disability_5"] == [1, 2]
    assert query["time"] == 2021
    assert query["measures"] == 20100
    assert "Disabled people" in result.figure("people_in_need").label
    assert result.sources[0].id == "nomis-nm_2056_1"
    assert not any("21 March 2021" in caveat for caveat in result.caveats)
    assert any("latest that Nomis holds" in caveat for caveat in result.caveats)


def test_need_figures_are_asked_for_as_counts_alone(nomis):
    # Some Nomis tables hold a percentage beside each count. Adding those up
    # with the counts would make the need too big.
    _run(_counts(Lewisham=60))
    assert nomis.asked[0][1]["measures"] == 20100


def test_filters_of_a_table_can_name_another_measure(nomis):
    need = {"dataset": "NM_1_1", "label": "Claimants", "filters": {"measures": 20201}}
    _run(_counts(Lewisham=60), options={"need": need})
    assert nomis.asked[0][1]["measures"] == 20201


@pytest.mark.parametrize(
    "need",
    [
        "poverty",
        7,
        {"label": "No dataset"},
        {"dataset": "NM_2056_1"},
        {"dataset": "NM_2056_1", "label": "x", "filters": {"geography": "TYPE499"}},
        {"dataset": "NM_2056_1", "label": "x", "extra": 1},
    ],
)
def test_bad_need_is_rejected(nomis, need):
    with pytest.raises(
        AnalysisInputError, match="People you are trying to reach"
    ) as caught:
        _run(_counts(Lewisham=60), options={"need": need})
    assert caught.value.option == "need"
    assert nomis.asked == []


def test_a_table_nomis_does_not_have_is_an_input_error():
    with (
        mock.patch(
            "uk_open_data.analyses._need.load_ons",
            side_effect=ValueError("NOMIS dataset 'NM_0_0' does not exist."),
        ),
        pytest.raises(AnalysisInputError, match="could not be loaded"),
    ):
        _run(
            _counts(Lewisham=60),
            options={"need": {"dataset": "NM_0_0", "label": "Nothing"}},
        )


def test_filters_that_are_not_plain_values_are_an_input_error(nomis):
    need = {"dataset": "NM_2056_1", "label": "x", "filters": {"c_sex": {1, 2}}}
    with pytest.raises(AnalysisInputError, match="could not be loaded"):
        _run(_counts(Lewisham=60), options={"need": need})


def test_need_without_local_authorities_is_an_input_error():
    empty = pd.DataFrame(
        {"geography_code": ["S12000036"], "geography_name": ["x"], "obs_value": [5]}
    )
    with (
        mock.patch("uk_open_data.analyses._need.load_ons", return_value=empty),
        pytest.raises(AnalysisInputError, match="no local authority"),
    ):
        _run(_counts(Lewisham=60))


def test_places_can_be_names_or_codes_in_any_case(nomis):
    rows = [
        {"Area": "lewisham ", "Clients": 20},
        {"Area": "E09000023", "Clients": "1,000"},
        {"Area": "e09000011", "Clients": 30.0},
    ]
    result = _run_wide(rows)
    table = result.table("by_local_authority")
    people = {row["geography_name"]: row["people"] for row in table.rows}
    assert people["Lewisham"] == 1020
    assert people["Greenwich"] == 30


def test_rows_that_cannot_be_placed_are_counted_not_named(nomis):
    rows = [
        *_counts(Lewisham=60),
        {"Area": "Atlantis", "Clients": 9},
        {"Area": "", "Clients": 4},
        {"Area": None, "Clients": 4},
    ]
    result = _run(rows)
    assert result.figure("people_supplied").value == 69
    assert result.figure("people_located").value == 60
    assert "2 rows had no local authority." in result.warnings
    flag = (
        "1 row named a local authority that the need figures do not list: "
        "row 2, counting from the first row of data. Write each council's name"
    )
    assert any(w.startswith(flag) for w in result.warnings)
    assert any(w.startswith("9 people were placed outside") for w in result.warnings)
    assert "Atlantis" not in json.dumps(result.to_dict())


def test_bad_counts_are_an_input_error(nomis):
    rows = [*_counts(Lewisham=60), {"Area": "Adur", "Clients": "a few"}]
    with pytest.raises(AnalysisInputError) as raised:
        _run(rows)
    assert str(raised.value) == (
        "1 row had a count that is not a whole number of zero or more: row 2, "
        "counting from the first row of data. Correct them and run the "
        "analysis again."
    )
    assert raised.value.role == "count"


def test_many_rows_that_name_no_place_are_counted_after_the_first_five(nomis):
    rows = [
        *_counts(Lewisham=60),
        *({"Area": f"Nowhere {n}", "Clients": 1} for n in range(8)),
    ]
    result = _run(rows)
    flag = (
        "8 rows named a local authority that the need figures do not list: "
        "rows 2, 3, 4, 5, 6 and 3 more, counting from the first row of data."
    )
    assert any(w.startswith(flag) for w in result.warnings)
    assert "Nowhere" not in json.dumps(result.to_dict())


def test_too_few_people_is_an_input_error(nomis):
    with pytest.raises(AnalysisInputError, match="Fewer than 5 people"):
        _run(_counts(Lewisham=4))


def test_a_place_that_is_not_listed_is_the_reason_given_not_too_few_people(nomis):
    # 200 people in a place whose name is mistyped are not "fewer than 5".
    with pytest.raises(AnalysisInputError) as raised:
        _run(_counts(Lewsham=200, Lewisham=3))
    message = str(raised.value)
    assert message.startswith(
        "200 people are in a place the need figures do not list, or outside "
        "England and Wales, so too few are left to give figures."
    )
    assert "for example Lewisham, or give its code, for example E09000023" in message
    assert "Nomis" not in message
    assert "Fewer than" not in message
    assert "Lewsham" not in message  # the place as typed is not repeated


# --- the list of places ----------------------------------------------------


def test_priority_areas_are_high_need_with_the_lowest_reach(nomis):
    result = _run_wide(_counts(Lewisham=90, Cardiff=10, Manchester=40, Greenwich=50))
    table = result.table("priority_areas")
    assert table.detail is False
    # Birmingham has nobody. Then reach per 100: Cardiff 0.1, Manchester 0.2,
    # Lewisham 1.0. Greenwich is not high need.
    assert _names(table) == ["Birmingham", "Cardiff", "Manchester", "Lewisham"]
    assert [row["rank"] for row in table.rows] == [1, 2, 3, 4]
    assert table.rows[0]["people"] == 0
    assert table.rows[1]["people_per_100_in_need"] == 0.1
    assert set(_names(table)) == HIGH_NEED


def test_places_with_nobody_are_listed_by_need(nomis):
    result = _run_wide(_counts(Greenwich=50))
    table = result.table("priority_areas")
    assert _names(table) == ["Birmingham", "Manchester", "Cardiff", "Lewisham"]


def test_top_sets_the_length_of_the_list(nomis):
    result = _run_wide(_counts(Greenwich=50), options={"top": 2})
    assert _names(result.table("priority_areas")) == ["Birmingham", "Manchester"]
    choice = next(c for c in result.choices if c.id == "top")
    assert choice.value == 2


@pytest.mark.parametrize("top", [0, 51, 2.5, "ten", True])
def test_bad_top_is_rejected(nomis, top):
    with pytest.raises(AnalysisInputError, match="Places listed") as caught:
        _run(_counts(Greenwich=50), options={"top": top})
    assert caught.value.option == "top"


# --- small counts ----------------------------------------------------------


def test_small_counts_are_hidden_in_both_tables(nomis):
    result = _run_wide(_counts(Lewisham=60, Birmingham=3, Cardiff=4, Greenwich=30))
    for table_id in ("priority_areas", "by_local_authority"):
        rows = {r["geography_name"]: r for r in result.table(table_id).rows}
        for name in ("Birmingham", "Cardiff"):
            assert rows[name]["people"] is None
            assert rows[name]["people_per_100_in_need"] is None
            assert rows[name]["suppressed"] is True
        assert rows["Lewisham"]["people"] == 60
    assert result.privacy.cells_suppressed == 2
    assert result.privacy.row_level_output is False


def test_a_hidden_count_is_ranked_as_the_most_it_could_be(nomis):
    # Birmingham's 3 is ranked as 4 in 40,000 and Cardiff's 4 as 4 in 10,000.
    # Manchester's 6 in 20,000 falls between them.
    result = _run_wide(_counts(Lewisham=60, Birmingham=3, Cardiff=4, Manchester=6))
    assert _names(result.table("priority_areas")) == [
        "Birmingham",
        "Manchester",
        "Cardiff",
        "Lewisham",
    ]


def test_one_small_count_has_the_smallest_other_count_hidden_with_it(nomis):
    # The total is shown, so Birmingham's 3 could be worked out if it were the
    # only count hidden. Adur's 8 is the smallest other count.
    result = _run_wide(_counts(Lewisham=60, Birmingham=3, Cardiff=20, Adur=8))
    rows = {r["geography_name"]: r for r in result.table("by_local_authority").rows}
    assert rows["Birmingham"]["suppressed"] is True
    assert rows["Adur"]["suppressed"] is True
    assert rows["Cardiff"]["people"] == 20
    assert rows["Lewisham"]["people"] == 60
    # Birmingham is then the only hidden count among the high-need places.
    assert result.figure("share_of_people_in_high_need_areas").suppressed is True
    assert result.privacy.cells_suppressed == 3


def test_a_count_hidden_to_protect_another_is_flagged_in_the_list(nomis):
    result = _run_wide(_counts(Lewisham=60, Birmingham=3, Cardiff=20))
    table = result.table("priority_areas")
    rows = {r["geography_name"]: r for r in table.rows}
    assert rows["Cardiff"]["suppressed"] is True
    assert _names(table) == ["Manchester", "Birmingham", "Cardiff", "Lewisham"]
    assert any("hidden only to protect another" in w for w in result.warnings)


def test_share_is_hidden_when_it_would_give_a_count_away(nomis):
    # Birmingham is the only high-need place with people, so the share of
    # people in high-need places would be its count.
    result = _run(_counts(Birmingham=3, Greenwich=30, Adur=20))
    share = result.figure("share_of_people_in_high_need_areas")
    assert share.value is None
    assert share.suppressed is True
    rows = {r["geography_name"]: r for r in result.table("by_local_authority").rows}
    assert rows["Birmingham"]["suppressed"] is True
    assert result.privacy.cells_suppressed == 3


@pytest.mark.parametrize(
    "people",
    [
        {"Birmingham": 3, "Greenwich": 30, "Adur": 20},
        {"Birmingham": 40, "Manchester": 3, "Greenwich": 30, "Adur": 20},
        {"Birmingham": 4000, "Manchester": 2500, "Greenwich": 3, "Adur": 900},
        {"Birmingham": 3, "Manchester": 2, "Greenwich": 30, "Adur": 20},
    ],
)
def test_an_exact_share_gives_no_hidden_count_away(nomis, people):
    # The share of people in high-need places, before rounding, times the
    # people in the area, is the exact number of people in those places.
    result = _run_wide(_counts(**people))
    rows = result.table("by_local_authority").rows
    hidden = {position for position, row in enumerate(rows) if row["suppressed"]}
    assert hidden
    sums = [set(range(len(rows)))]  # the people in the area are a figure
    if result.figure("share_of_people_in_high_need_areas").exact is not None:
        sums.append({i for i, row in enumerate(rows) if row["high_need"]})
    assert worked_out(hidden, sums) == []
    check_working(result)


def test_suppress_below_can_be_raised_but_not_dropped(nomis):
    result = _run(
        _counts(Lewisham=60, Cardiff=8, Manchester=9),
        options={"suppress_below": 10},
    )
    rows = {r["geography_name"]: r for r in result.table("by_local_authority").rows}
    assert rows["Cardiff"]["people"] is None
    assert rows["Manchester"]["people"] is None
    with pytest.raises(AnalysisInputError, match="Smallest count shown") as caught:
        _run(_counts(Lewisham=60), options={"suppress_below": 2})
    assert caught.value.option == "suppress_below"


# --- the area compared -----------------------------------------------------


def test_catchment_can_name_local_authorities(nomis):
    result = _run(
        _counts(Lewisham=60, Greenwich=30, Birmingham=10),
        options={"catchment": ["Lewisham", "E09000011", "adur"]},
    )
    assert result.figure("areas_compared").value == 3
    assert result.figure("people_located").value == 100
    assert result.figure("people_in_catchment").value == 90
    assert any(w.startswith("10 people live outside") for w in result.warnings)
    assert any(w.startswith("Only 3 local authorities") for w in result.warnings)
    # The top quarter of three places is one place, the one with most need.
    assert _names(result.table("priority_areas")) == ["Lewisham"]
    choice = next(c for c in result.choices if c.id == "catchment")
    assert choice.value == "Adur, Greenwich, Lewisham"
    check = next(c for c in result.checks if c.id == "catchment")
    assert "Adur, Greenwich, Lewisham" in check.question


def test_catchment_can_be_a_country(nomis):
    wales = _run(_counts(Cardiff=10), options={"catchment": "Wales"})
    assert _names(wales.table("by_local_authority")) == ["Cardiff"]
    england = _run(_counts(Lewisham=10), options={"catchment": "england"})
    assert england.figure("areas_compared").value == 15
    both = _run(_counts(Lewisham=10), options={"catchment": "England and Wales"})
    assert both.figure("areas_compared").value == 16


@pytest.mark.parametrize("catchment", [["Lewisham", "Narnia"], 7, [], [""]])
def test_bad_catchment_is_rejected(nomis, catchment):
    with pytest.raises(AnalysisInputError, match="Area you serve") as caught:
        _run(_counts(Lewisham=60), options={"catchment": catchment})
    assert caught.value.option == "catchment"


def test_catchment_with_too_few_people_is_an_input_error(nomis):
    with pytest.raises(AnalysisInputError, match="live in the area you serve"):
        _run(_counts(Lewisham=60, Adur=2), options={"catchment": "Adur"})


GUESSED = "The area you serve was worked out from where your people live"


def test_the_area_is_worked_out_from_where_most_people_live(nomis):
    # Cardiff holds 3 of 103 people, under 5%, so it is left out of the area.
    result = _run(_counts(Greenwich=30, Lewisham=60, Adur=10, Cardiff=3))
    assert result.figure("areas_compared").value == 3
    assert result.figure("people_in_catchment").value == 100
    assert _names(result.table("by_local_authority")) == [
        "Adur",
        "Greenwich",
        "Lewisham",
    ]
    choice = next(c for c in result.choices if c.id == "catchment")
    assert choice.value == "Lewisham, Greenwich, Adur"  # most people first
    assert choice.reason == (
        "Each of these local authorities holds at least 5% of the people located."
    )
    assert any(w.startswith(GUESSED) for w in result.warnings)
    assert any(w.startswith("3 people live outside") for w in result.warnings)


def test_the_share_that_joins_a_place_to_the_area_can_be_changed(nomis):
    result = _run(
        _counts(Lewisham=60, Greenwich=30, Adur=10),
        options={"catchment_min_share": 0.5},
    )
    assert _names(result.table("by_local_authority")) == ["Lewisham"]


def test_every_place_is_compared_when_none_holds_enough_people(nomis):
    result = _run(
        _counts(Lewisham=60, Greenwich=40), options={"catchment_min_share": 0.7}
    )
    assert result.figure("areas_compared").value == 16
    choice = next(c for c in result.choices if c.id == "catchment")
    assert choice.value == EVERYWHERE
    assert choice.reason == (
        "No local authority holds as much as 70% of the people located, so "
        "every local authority in England and Wales is compared."
    )
    assert not any(w.startswith(GUESSED) for w in result.warnings)


def test_one_place_alone_is_not_called_a_gap(nomis):
    # A charity whose people nearly all live in one place gets that place as
    # its area. The answer must not present it as a place to look at first.
    result = _run(_counts(Lewisham=120, Greenwich=4))
    assert result.figure("areas_compared").value == 1
    assert result.answer == (
        "Only one local authority is compared, so the analysis cannot say "
        "where need is high and your reach is low. Across it you reached "
        "1.33 people per 100 in need."
    )
    assert any(
        w.startswith("Only one local authority is compared") for w in result.warnings
    )
    # With one place every share is 100%, so the rate and counts come first.
    assert result.key_figures == (
        "reach_per_100_in_need",
        "people_in_catchment",
        "people_in_need",
    )


def test_a_named_area_is_not_called_worked_out(nomis):
    result = _run(_counts(Lewisham=60), options={"catchment": ["Lewisham", "Adur"]})
    assert not any(w.startswith(GUESSED) for w in result.warnings)


@pytest.mark.parametrize("share", ["a lot", 0, 1.5, True, None])
def test_bad_share_is_rejected(nomis, share):
    with pytest.raises(
        AnalysisInputError, match="Share that makes a place part of your area"
    ) as caught:
        _run(_counts(Lewisham=60), options={"catchment_min_share": share})
    assert caught.value.option == "catchment_min_share"


def test_a_wide_comparison_is_flagged_when_people_are_in_few_places():
    many = pd.DataFrame(
        {
            "geography_code": [f"E0600{n:04d}" for n in range(30)],
            "geography_name": [f"Place {n}" for n in range(30)],
            "obs_value": [100 + n for n in range(30)],
        }
    )
    rows = [{"Area": "Place 1", "Clients": 40}, {"Area": "Place 2", "Clients": 20}]
    with mock.patch("uk_open_data.analyses._need.load_ons", return_value=many):
        # No place holds every person, so the whole country is compared.
        wide = _run(rows, options={"catchment_min_share": 1})
        named = _run(rows, options={"catchment": "England"})
    flag = (
        "No area was given, so all 30 local authorities in England and Wales "
        "are looked at, and your people live in 2 of them."
    )
    assert any(w.startswith(flag) for w in wide.warnings)
    assert not any(w.startswith(flag) for w in named.warnings)


# --- postcodes -------------------------------------------------------------

# Real postcodes never end in C, I, K, M, O or V, so none of these can exist.
PLACES = {
    "SE13 7VC": "E09000023",
    "SE13 6CM": "E09000023",
    "SE10 9OK": "E09000011",
    "CF10 1VC": "W06000015",
    "EH1 1VC": "S12000036",
}
PEOPLE = (
    ["SE13 7VC"] * 20
    + ["se136cm"] * 10
    + ["SE10 9OK"] * 12
    + ["CF10 1VC"] * 3
    + ["EH1 1VC"] * 2
    + ["SE13 7VO", "not a postcode", ""]
)
POSTCODE_ROWS = [{"Home postcode": postcode} for postcode in PEOPLE]
POSTCODE_COLUMN = {"postcode": "Home postcode"}


def _fake_lookup(sent: list):
    def lookup(postcodes: list[str], level: str) -> pd.DataFrame:
        sent.append((level, list(postcodes)))
        return pd.DataFrame(
            {
                "postcode": postcodes,
                "geography_code": [PLACES.get(postcode) for postcode in postcodes],
                "geography_name": [None] * len(postcodes),
            }
        )

    return lookup


def test_postcodes_are_placed_in_local_authorities_online(nomis):
    sent: list = []
    with mock.patch(
        "uk_open_data.analyses._steps.postcodes_to_geography",
        side_effect=_fake_lookup(sent),
    ):
        result = _run(POSTCODE_ROWS, columns=POSTCODE_COLUMN)
    assert result.input_mode == "postcodes"
    level, postcodes = sent[0]
    assert level == "LAD"
    assert postcodes == sorted(set(postcodes))
    assert result.figure("people_supplied").value == 50
    assert result.figure("people_located").value == 45
    rows = {r["geography_name"]: r for r in result.table("by_local_authority").rows}
    assert rows["Lewisham"]["people"] == 30
    # Cardiff's 3 is hidden, and Greenwich's 12 with it so it cannot be worked out.
    assert rows["Cardiff"]["suppressed"] is True
    assert rows["Greenwich"]["suppressed"] is True
    assert any(w.startswith("2 people were placed outside") for w in result.warnings)
    assert "local authorities" in result.privacy.sent_to_third_parties[0]
    source = next(s for s in result.sources if s.id == "postcodes-io")
    assert source.used_for == "Finding the local authority each postcode is in."
    assert result.checks[0].id == "one_row_one_person"


def test_postcodes_stay_on_this_machine_when_a_table_is_installed(nomis, tmp_path):
    header = "pcd7,lsoa21cd,ladcd"
    lines = [
        f"{postcode.replace(' ', '').ljust(7)[:4].strip().ljust(4)}"
        f"{postcode[-3:]},E0100000{n},{lad}"
        for n, (postcode, lad) in enumerate(PLACES.items())
    ]
    source = tmp_path / "lookup.csv"
    source.write_text("\n".join([header, *lines]) + "\n", encoding="utf-8")
    packed = tmp_path / "postcodes.ktpc.gz"
    build_postcode_table(source, packed, "May 2026")
    install_postcode_table(packed)
    with mock.patch("uk_open_data.analyses._steps.postcodes_to_geography") as online:
        result = _run(POSTCODE_ROWS, columns=POSTCODE_COLUMN)
    online.assert_not_called()
    assert result.privacy.sent_to_third_parties == ()
    assert result.figure("people_located").value == 45
    source = next(s for s in result.sources if s.id == "ons-postcode-lookup")
    assert source.used_for == "Finding the local authority each postcode is in."


def test_no_postcode_reaches_the_result(nomis):
    with mock.patch(
        "uk_open_data.analyses._steps.postcodes_to_geography",
        side_effect=_fake_lookup([]),
    ):
        result = _run(POSTCODE_ROWS, columns=POSTCODE_COLUMN)
    text = json.dumps(result.to_dict()).upper().replace(" ", "")
    for postcode in PEOPLE:
        compact = postcode.upper().replace(" ", "")
        assert not compact or compact not in text


# --- the map ---------------------------------------------------------------


def test_map_is_described_by_local_authority(nomis):
    nomis.residents = RESIDENTS
    result = _run_wide(
        _counts(Lewisham=60, Greenwich=30, Adur=10, Cardiff=3, Manchester=4)
    )
    spec = result.map
    assert (spec.geography_type, spec.geography_year) == ("LAD", 2023)
    assert spec.table == "by_local_authority"
    assert [layer.id for layer in spec.layers] == ["need", "reach"]
    assert spec.layers[0].categories == NEED_BANDS
    assert spec.layers[1].categories == REACH_BANDS
    table = result.table(spec.table)
    assert table.detail is True
    rows = {r["geography_name"]: r for r in table.rows}
    assert {r["need_band"] for r in table.rows} <= set(NEED_BANDS)
    # Need is shaded by its rate, so the place with most people in need is
    # not the darkest for its size alone.
    assert spec.layers[0].label == "People in need for each 1,000 residents"
    assert "not darker for its size alone" in spec.layers[0].note
    assert rows["Birmingham"]["people_in_need_per_1000_residents"] == 5.0
    assert rows["Birmingham"]["need_band"] == "Lowest fifth"
    assert rows["Isles of Scilly"]["people_in_need_per_1000_residents"] == 100.0
    assert rows["Isles of Scilly"]["need_band"] == "Highest fifth"
    assert rows["Lewisham"]["people_in_need_per_1000_residents"] == 20.0
    # The list of places still goes by the count.
    assert rows["Birmingham"]["high_need"] is True
    choice = next(c for c in result.choices if c.id == "map_need")
    assert choice.value == spec.layers[0].label
    assert any(s.title == "Loaded the residents" for s in result.working)
    assert len(result.sources) == 2
    # Nobody, a hidden count and a hidden count look the same on the map.
    for name in ("Birmingham", "Cardiff", "Manchester"):
        assert rows[name]["reach_band"] == NO_REACH
    # Reach per 100: Greenwich 0.38, Lewisham 0.67, Adur 1.0.
    assert rows["Greenwich"]["reach_band"] == "Lower reach"
    assert rows["Lewisham"]["reach_band"] == "Middle reach"
    assert rows["Adur"]["reach_band"] == "Higher reach"


def _square(number: int, code: str) -> dict:
    """An invented square boundary for one local authority."""
    west = -3.0 + 0.5 * (number % 4)
    south = 51.0 + 0.5 * (number // 4)
    ring = [
        [west, south],
        [west + 0.5, south],
        [west + 0.5, south + 0.5],
        [west, south + 0.5],
        [west, south],
    ]
    return {
        "type": "Feature",
        "properties": {"LAD23CD": code},
        "geometry": {"type": "Polygon", "coordinates": [ring]},
    }


@pytest.mark.parametrize(
    ("values", "parts", "expected"),
    [
        # Two shown counts: the higher is "Higher", not "Middle".
        ([0.4, 0.9], 3, [0, 2]),
        ([7.0, 3.0, 5.0], 5, [4, 0, 2]),
        ([1.0, 2.0, 3.0, 4.0], 5, [0, 1, 3, 4]),
        # One place alone is not the lowest of anything.
        ([6.0], 5, [2]),
        ([6.0], 3, [1]),
        # As many places as groups, or more: equal groups, as before.
        ([1.0, 2.0, 3.0], 3, [0, 1, 2]),
        ([5.0, 1.0, 4.0, 2.0, 3.0, 6.0], 3, [2, 0, 1, 0, 1, 2]),
        ([], 5, []),
    ],
)
def test_few_places_are_spread_from_the_lowest_group_to_the_highest(
    values, parts, expected
):
    part = equal_parts(values, parts)
    assert [part[i] for i in range(len(values))] == expected


def test_the_higher_of_two_shown_places_is_in_the_top_group(nomis):
    # The key of the reach layer runs from "Lower" to "Higher". With two
    # places shown, the higher was "Middle reach" and nothing was "Higher".
    result = _run(_counts(Lewisham=60, Greenwich=30))
    rows = {r["geography_name"]: r for r in result.table("by_local_authority").rows}
    shown = {name: row["reach_band"] for name, row in rows.items() if row["people"]}
    assert sorted(shown.values()) == ["Higher reach", "Lower reach"]
    assert result.map.layers[1].note.endswith(FEW_PLACES)


@pytest.mark.parametrize(
    ("places", "parts", "said"),
    [
        (0, 3, ""),
        (1, 3, ONE_PLACE),
        (1, 5, ONE_PLACE),
        (2, 3, FEW_PLACES),
        (4, 5, FEW_PLACES),
        # A place for every group, or more: nothing to explain.
        (3, 3, ""),
        (5, 5, ""),
        (296, 5, ""),
    ],
)
def test_few_places_are_spoken_of_only_when_they_are_few(places, parts, said):
    assert few_places(places, parts) == said


def test_a_map_of_many_places_says_nothing_of_few(nomis):
    # The words about few places were on every map, and puzzled a reader of
    # a map with a place for every group.
    result = _run_wide(_counts(Lewisham=60, Greenwich=30, Cardiff=45))
    assert len(result.table("by_local_authority").rows) >= 5
    for layer in result.map.layers:
        assert "fewer places" not in layer.note
        assert "One place" not in layer.note


def test_a_map_says_so_when_few_places_are_grouped(nomis):
    two = _run(_counts(Lewisham=60, Greenwich=30))
    assert len(two.table("by_local_authority").rows) == 2
    assert two.map.layers[0].note.endswith(FEW_PLACES)
    assert two.map.layers[1].note.endswith(FEW_PLACES)
    # Many places compared, one of them reached: the need layer has a place
    # for every group and the reach layer has one place alone.
    one = _run_wide(_counts(Lewisham=60))
    assert "fewer places" not in one.map.layers[0].note
    assert one.map.layers[1].note.endswith(ONE_PLACE)


def test_map_shades_need_by_count_when_the_need_is_every_resident(nomis):
    nomis.residents = RESIDENTS
    result = _run_wide(_counts(Lewisham=60), options={"need": "residents"})
    assert len(nomis.asked) == 1  # residents are the need, and are not asked twice
    assert result.map.layers[0].label == "Residents"
    assert result.map.layers[0].note == (
        "Local authorities in five equal groups by residents."
    )
    assert result.map.layers[1].label == "People reached per 100 residents"
    assert result.map.title == "Residents and reach, by local authority"
    rows = {r["geography_name"]: r for r in result.table("by_local_authority").rows}
    assert rows["Birmingham"]["people_in_need_per_1000_residents"] is None
    assert rows["Birmingham"]["need_band"] == "Highest fifth"
    choice = next(c for c in result.choices if c.id == "map_need")
    assert choice.label == "How the map shades residents"
    assert choice.value == "Residents"
    assert [chart.title for chart in result.charts] == [
        "Residents in the places listed",
        "People reached per 100 residents in the places listed",
    ]
    assert not any("high need" in caveat for caveat in result.caveats)
    check = next(c for c in result.checks if c.id == "need_fits")
    assert check.question == (
        "Are these the people you are trying to reach: Residents of every age?"
    )
    assert "Change 'People you are trying to reach'" in check.why
    # The working and the source do not call every resident a need either.
    titles = [step.title for step in result.working]
    assert "Set reach against residents" in titles
    assert "Listed the places with the most residents and low reach" in titles
    said = [step.detail for step in result.working]
    said += [source.used_for for source in result.sources]
    assert not [text for text in said if "in need" in text or "high need" in text]
    assert result.sources[0].used_for == (
        "People you are trying to reach: Residents of every age."
    )


def test_the_setting_for_need_has_one_name(nomis):
    # A message says "Change 'People you are trying to reach'", so the list
    # of choices under it uses the same name.
    result = _run_wide(_counts(Lewisham=60, Greenwich=30, Adur=10))
    option = {o.name: o for o in describe_analysis(ANALYSIS_ID).options}["need"]
    choice = next(c for c in result.choices if c.id == "need")
    assert choice.label == option.label == "People you are trying to reach"


def test_kept_need_figures_keep_the_map_off_the_network_too(nomis):
    # With the need kept and no residents kept, nothing is fetched and the map
    # goes by the count. With both kept, it goes by the rate.
    keep_need_figures("unemployed", NEED, "invented for a test.")
    by_count = _run_wide(_counts(Lewisham=60))
    assert by_count.map.layers[0].label == "People in need"
    choice = next(c for c in by_count.choices if c.id == "map_need")
    assert "no copy of the residents is kept" in choice.reason
    residents = [(code, name, RESIDENTS[name]) for code, name, _ in NEED]
    keep_need_figures("residents", residents, "invented for a test.")
    by_rate = _run_wide(_counts(Lewisham=60))
    assert by_rate.map.layers[0].label == "People in need for each 1,000 residents"
    assert any("A copy kept on this machine" in s.edition for s in by_rate.sources[1:])
    assert nomis.asked == []


def test_map_can_be_drawn(nomis):
    result = _run(_counts(Lewisham=60, Greenwich=30, Adur=10))
    boundaries = {
        "type": "FeatureCollection",
        "features": [_square(n, code) for n, (code, _, _) in enumerate(NEED)],
    }
    for layer in ("need", "reach"):
        svg = render_map(result, layer=layer, boundaries=boundaries)
        root = ET.fromstring(svg)
        titles = [
            title.text for title in root.iter("{http://www.w3.org/2000/svg}title")
        ]
        assert any(text.startswith("Lewisham: ") for text in titles[1:])
        # Three places are few enough to name, and the title says what the
        # colour shows.
        texts = {
            text.text: text.get("class")
            for text in root.iter("{http://www.w3.org/2000/svg}text")
        }
        assert {texts[name] for name in ("Lewisham", "Greenwich", "Adur")} == {"name"}
        label = next(item.label for item in result.map.layers if item.id == layer)
        assert f"{label}, by local authority" in texts


def test_map_of_a_few_authorities_is_fetched_in_fine_detail(nomis):
    result = _run(_counts(Lewisham=60, Greenwich=30, Adur=10))
    shaded = {row["geography_code"] for row in result.table("by_local_authority").rows}
    squares = {code: _square(n, code) for n, (code, _, _) in enumerate(NEED)}
    asked = []

    def service(geography_type, **wanted):
        asked.append(wanted)
        codes = wanted.get("LAD23CD", list(squares))
        return {"type": "FeatureCollection", "features": [squares[c] for c in codes]}

    with mock.patch("uk_open_data.analyses.maps.load_geodata", service):
        boundaries = load_map_boundaries(result)
    own, everywhere, *near = asked
    # The shaded places come from the full outlines that stop at the shore,
    # with detail finer than twenty metres left out, and so do the places
    # the picture shows beside them.
    assert (own["boundary_type"], own["simplify_m"]) == ("BFC", 20)
    assert set(own["LAD23CD"]) == shaded
    assert everywhere["boundary_type"] == "BSC"
    assert "simplify_m" not in everywhere and "LAD23CD" not in everywhere
    assert {(n["boundary_type"], n["simplify_m"]) for n in near} == {("BFC", 20)}
    # They are asked for ten at a time.
    assert max(len(n["LAD23CD"]) for n in near) <= 10
    # A shaded place is never also one of the places around, and a map of
    # local authorities has no place that holds the others.
    around = {f["properties"]["LAD23CD"] for f in boundaries["surroundings"]}
    assert around and not around & shaded
    # Those the picture does not show keep their 200 metre outlines.
    fine = {code for n in near for code in n["LAD23CD"]}
    assert fine and fine < around
    assert boundaries["focus"] == []
    svg = render_map(result, boundaries=boundaries)
    # "Near" reaches further than the picture, so not all of them are drawn.
    assert 0 < svg.count('class="land"') <= len(around)


def _named(svg: str) -> dict[str, tuple[float, float]]:
    """Where each shaded place is named on a picture."""
    texts = ET.fromstring(svg).iter("{http://www.w3.org/2000/svg}text")
    return {
        text.text: (float(text.get("x")), float(text.get("y")))
        for text in texts
        if text.get("class") == "name"
    }


def test_a_name_sits_beside_a_place_too_small_to_hold_it(nomis):
    # Places far apart are drawn small. A name on top of a small place would
    # hide the colour that says how much need it has. "Small" is a place the
    # name would cover more than half of.
    result = _run(_counts(Lewisham=60, Greenwich=30, Adur=10))
    rows = result.table("by_local_authority").rows
    codes = {row["geography_name"]: row["geography_code"] for row in rows}
    features = [_square(n, code) for n, code in enumerate(codes.values())]
    for feature in features:
        if feature["properties"]["LAD23CD"] == codes["Adur"]:
            west, south = feature["geometry"]["coordinates"][0][0]
            feature["geometry"]["coordinates"][0] = [
                [west, south],
                [west + 0.01, south],
                [west + 0.01, south + 0.01],
                [west, south + 0.01],
                [west, south],
            ]
    boundaries = {"type": "FeatureCollection", "features": features}
    svg = render_map(result, boundaries=boundaries)
    named = _named(svg)
    root = ET.fromstring(svg)
    paths = root.iter("{http://www.w3.org/2000/svg}path")
    titles = {
        path.find("{http://www.w3.org/2000/svg}title").text.split(":")[0]: path
        for path in paths
        if "area" in (path.get("class") or "").split()
    }

    def box(name: str) -> tuple[float, float]:
        numbers = [float(n) for n in re.findall(r"-?\d+\.\d", titles[name].get("d"))]
        return min(numbers[::2]), max(numbers[::2])

    left, right = box("Adur")
    # The name starts to the right of the place, clear of it.
    assert named["Adur"][0] - len("Adur") * 6.2 * 1.1 / 2 >= right
    # A place with room keeps its name in the middle.
    left, right = box("Lewisham")
    assert left < named["Lewisham"][0] < right


# --- the whole result ------------------------------------------------------


def test_result_explains_itself(nomis):
    result = _run(_counts(Lewisham=60, Greenwich=30, Adur=10))
    options = check_working(result)
    assert options["need"] == "unemployed"
    again = _run(_counts(Lewisham=60, Greenwich=30, Adur=10), options=options)
    assert again.answer == result.answer
    # A share hidden to protect a small count has no exact value either.
    hidden = _run(_counts(Lewisham=60, Greenwich=3, Adur=10, Cardiff=30))
    check_working(hidden)
    assert [f.exact for f in hidden.figures if f.suppressed] in ([], [None])
    # Every column has a plain heading to show in place of its id.
    assert not [
        column
        for table in result.tables
        for column in table.columns
        if table.headings[column] == column
    ]
    assert result.analysis_id == ANALYSIS_ID
    assert [step.title for step in result.working] == [
        "Loaded the need figures",
        "Loaded the residents",
        "Read the local authority counts",
        "Joined people to the need figures",
        "Set the area you serve",
        "Set reach against need",
        "Listed the places with high need and low reach",
        "Hid small counts",
    ]
    # A reader must not take every hidden count for a small one.
    assert any("not always small" in note for note in result.privacy.notes)
    assert [check.id for check in result.checks] == [
        "counts_are_people",
        "home_location",
        "period",
        "need_fits",
        "catchment",
    ]
    option_names = {option.name for option in describe_analysis(ANALYSIS_ID).options}
    for choice in result.choices:
        assert choice.option is None or choice.option in option_names
    summary = result.to_dict(include_detail=False)
    json.dumps(summary)
    detail = next(t for t in summary["tables"] if t["id"] == "by_local_authority")
    assert detail["rows"] == []


def test_command_line_runs_the_analysis(nomis, tmp_path, capsys):
    path = tmp_path / "counts.csv"
    path.write_text("Area,Clients\nLewisham,60\nGreenwich,30\n", encoding="utf-8")
    code = main(
        [
            "analysis",
            "run",
            ANALYSIS_ID,
            str(path),
            "--column",
            "local_authority=Area",
            "--column",
            "count=Clients",
            "--option",
            "need=unemployed_women",
            "--option",
            'catchment=["Lewisham", "Greenwich", "Adur"]',
            "--json",
        ]
    )
    assert code == EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["analysis_id"] == ANALYSIS_ID
    assert nomis.asked[0][1]["c_sex"] == [1]
