"""
Unit tests for the who we are missing analysis.

The census figures and the postcode lookup are replaced with small invented
tables, so the tests are isolated and repeatable.
"""

import json
import unittest.mock as mock

import pandas as pd
import pytest
from working_checks import check_working

from uk_open_data.analyses import (
    AnalysisInputError,
    describe_analysis,
    render_map,
    run_analysis,
    who_we_miss,
)
from uk_open_data.analyses.who_we_miss import (
    clear_residents_cache,
    download_residents,
    keep_residents,
    residents_path,
)
from uk_open_data.cli import EXIT_INPUT_ERROR, EXIT_OK, main
from uk_open_data.connector.privacy import find_row_values
from uk_open_data.postcodes import build_postcode_table, install_postcode_table

ANALYSIS_ID = "who-we-miss"
COLUMNS = {"group": "Ethnicity", "count": "Clients"}
GROUPS = ("Asian", "Black", "Mixed", "White", "Other")

# The names the census gives the five high-level ethnic groups.
CENSUS_NAMES = (
    "Asian, Asian British or Asian Welsh",
    "Black, Black British, Black Welsh, Caribbean or African",
    "Mixed or Multiple ethnic groups",
    "White",
    "Other ethnic group",
)
# Invented residents for real local authority codes, in the order of GROUPS.
# Lewisham has 300,000 and so has Greenwich.
RESIDENTS = (
    ("E09000023", "Lewisham", (30000, 75000, 24000, 156000, 15000)),
    ("E09000011", "Greenwich", (45000, 60000, 18000, 165000, 12000)),
    ("W06000015", "Cardiff", (35000, 14000, 14000, 280000, 7000)),
)
# Invented residents by sex: female, male.
RESIDENTS_BY_SEX = (
    ("E09000023", "Lewisham", (156000, 144000)),
    ("E09000011", "Greenwich", (150000, 150000)),
)


class _Nomis:
    """Stands in for Nomis and records what it was asked."""

    def __init__(self) -> None:
        self.asked: list[tuple[str, dict]] = []
        self.own_rows = True
        self.leave_out: str | None = None

    def load(self, dataset: str, **query) -> pd.DataFrame:
        """Return residents by group for each authority, as Nomis would."""
        self.asked.append((dataset, query))
        if dataset == "NM_2028_1":
            return self._frame("c_sex_name", self._sex_rows())
        return self._frame("c2021_eth_20_name", self._ethnic_group_rows())

    def _ethnic_group_rows(self) -> list[tuple[str, str, str, float]]:
        rows = []
        for code, name, residents in RESIDENTS:
            rows.append((code, name, "Total: All usual residents", sum(residents)))
            for census_name, people in zip(CENSUS_NAMES, residents, strict=True):
                if census_name == self.leave_out:
                    continue
                if self.own_rows:
                    rows.append((code, name, census_name, people))
                # Two detailed rows that add up to the group.
                rows.append((code, name, f"{census_name}: First", people - 100))
                rows.append((code, name, f"{census_name}: Second", 100))
        rows.append(("S12000036", "City of Edinburgh", "White", 400000))
        return rows

    def _sex_rows(self) -> list[tuple[str, str, str, float]]:
        rows = []
        for code, name, (female, male) in RESIDENTS_BY_SEX:
            rows.append((code, name, "All persons", female + male))
            rows.append((code, name, "Female", female))
            rows.append((code, name, "Male", male))
        return rows

    @staticmethod
    def _frame(name_column: str, rows: list[tuple]) -> pd.DataFrame:
        columns = ["geography_code", "geography_name", name_column, "obs_value"]
        return pd.DataFrame(rows, columns=columns)


@pytest.fixture
def nomis():
    """Replace the census figures with the invented ones."""
    fake = _Nomis()
    with mock.patch(
        "uk_open_data.analyses.who_we_miss.load_ons", side_effect=fake.load
    ):
        yield fake


def _counts(**people: int) -> list[dict]:
    """Rows of counts by label, with the user's column names."""
    return [
        {"Ethnicity": label.replace("_", " "), "Clients": n}
        for label, n in people.items()
    ]


def _run(rows, options=None, columns=COLUMNS):
    options = {"catchment": "Lewisham"} if options is None else options
    return run_analysis(ANALYSIS_ID, rows, columns=columns, options=options)


def _rows(result) -> dict[str, dict]:
    return {row["group"]: row for row in result.table("by_group").rows}


# A charity whose clients are less often Black, and never from the Other
# group, than the residents of Lewisham.
CLIENTS = _counts(
    White_British=120,
    Black_Caribbean=20,
    Black_African=10,
    Indian=20,
    White_and_Black_Caribbean=30,
)


# --- the analysis is listed ----------------------------------------------------


def test_analysis_is_described():
    info = describe_analysis(ANALYSIS_ID)
    assert info.question == (
        "Who do we reach less than their share of the people who live here?"
    )
    assert [mode.name for mode in info.input_modes] == [
        "postcodes",
        "group_counts",
        "people",
    ]
    assert [mode.aggregated for mode in info.input_modes] == [False, True, False]
    assert {option.name for option in info.options} == {
        "suppress_below",
        "postcode_lookup",
        "characteristic",
        "groups",
        "catchment",
        "catchment_min_share",
        "under_represented_below",
    }
    assert info.coverage == "England and Wales"
    reported = {role.name: role.reported for role in info.roles}
    assert reported == {"group": True, "postcode": False, "count": False}


def test_characteristics_can_be_picked_from_a_list(capsys):
    option = {o.name: o for o in describe_analysis(ANALYSIS_ID).options}[
        "characteristic"
    ]
    assert [(choice.value, choice.label) for choice in option.choices] == [
        ("ethnic_group", "Ethnic group"),
        ("sex", "Sex"),
    ]
    assert main(["analysis", "describe", ANALYSIS_ID]) == EXIT_OK
    assert '    "sex": Sex' in capsys.readouterr().out


def test_only_the_census_group_names_are_public_in_the_group_column():
    info = describe_analysis(ANALYSIS_ID)
    group = info.roles[0]
    # A label can be the same as one of these, and the result names them.
    # Every other label is a person's own words and must never come back.
    assert group.reported_values == (*GROUPS, "Female", "Male")
    assert info.to_dict()["roles"][0]["reported_values"] == [
        *GROUPS,
        "Female",
        "Male",
    ]
    assert all(role.reported_values == () for role in info.roles[1:])


# --- counts by group -------------------------------------------------------


def test_shares_of_people_are_set_against_shares_of_residents(nomis):
    result = _run(CLIENTS)
    assert result.input_mode == "group_counts"
    assert result.figure("people_supplied").value == 200
    assert result.figure("people_in_catchment").value == 200
    assert result.figure("people_matched").value == 200
    assert result.figure("people_not_matched").value == 0
    assert result.figure("residents").value == 300000
    rows = _rows(result)
    assert list(rows) == list(GROUPS)
    assert [row["people"] for row in rows.values()] == [20, 30, 30, 120, 0]
    assert rows["Black"] == {
        "group": "Black",
        "people": 30,
        "share_of_people": 15.0,
        "residents": 75000,
        "share_of_residents": 25.0,
        "representation": 0.6,
        "under_represented": True,
        "suppressed": False,
    }
    assert rows["White"]["representation"] == 1.15
    assert rows["White"]["under_represented"] is False


def test_a_group_nobody_came_from_is_shown_and_counted_as_missed(nomis):
    result = _run(CLIENTS)
    other = _rows(result)["Other"]
    assert other["people"] == 0
    assert other["suppressed"] is False
    assert other["representation"] == 0.0
    assert other["under_represented"] is True
    # Black at 0.6 and Other at 0. Asian is at 1.0 and Mixed above it.
    assert result.figure("groups_under_represented").value == 2


def test_the_line_for_under_represented_can_be_moved(nomis):
    strict = _run(CLIENTS, options={"catchment": "Lewisham"})
    loose = _run(
        CLIENTS, options={"catchment": "Lewisham", "under_represented_below": 0.5}
    )
    assert _rows(strict)["Black"]["under_represented"] is True
    assert _rows(loose)["Black"]["under_represented"] is False
    choice = next(c for c in loose.choices if c.id == "under_represented_below")
    assert choice.value == 0.5
    assert choice.option == "under_represented_below"


def test_the_code_to_run_it_again_leaves_out_the_persons_own_labels(nomis):
    # The setting that matches a person's labels to census groups holds
    # their own words, so the code leaves it to be filled in.
    rows = [*CLIENTS, {"Ethnicity": "Code 7", "Clients": 9}]
    groups = {"Code 7": "Other"}
    result = _run(rows, options={"catchment": "Lewisham", "groups": groups})
    options = check_working(result)
    assert options["groups"] == {}
    assert options["catchment"] == "Lewisham"
    assert '"groups": {},  # fill in' in result.code
    assert find_row_values(result.to_dict(), ["Code 7"]) == []
    # Left alone, the setting is not written at all.
    assert "groups" not in check_working(_run(CLIENTS))


def test_the_shares_the_answer_quotes_are_figures_with_exact_values(nomis):
    # The answer turns on two small percentages. Each is a figure, so each
    # has its value before rounding to be checked against.
    result = _run(CLIENTS)
    first = next(
        row
        for row in result.table("by_group").rows
        if f", {row['group']}," in result.answer
    )
    ours = result.figure("share_of_people_first_group")
    theirs = result.figure("share_of_residents_first_group")
    assert ours.label.endswith(f", {first['group']}")
    assert (ours.value, theirs.value) == (
        first["share_of_people"],
        first["share_of_residents"],
    )
    assert f"{ours.value}%, against {theirs.value}%" in result.answer
    matched = result.figure("people_matched").value
    assert ours.exact == pytest.approx(100 * first["people"] / matched)
    assert round(theirs.exact, 1) == theirs.value
    check_working(result)


def test_no_share_is_a_figure_when_the_answer_quotes_none(nomis):
    # Nobody in the data is in the one group reached less than its share,
    # so the answer gives no percentages and there is nothing to check.
    result = _run(_counts(White_British=100, Black_Caribbean=45, Indian=20, Mixed=15))
    assert "%" not in result.answer
    ids = {figure.id for figure in result.figures}
    assert "share_of_people_first_group" not in ids


def test_result_says_what_it_did_and_can_be_written_as_json(nomis):
    result = _run(CLIENTS)
    assert result.map is None
    # Every column has a plain heading to show in place of its id.
    assert not [
        column
        for table in result.tables
        for column in table.columns
        if table.headings[column] == column
    ]
    assert [choice.id for choice in result.choices] == [
        "characteristic",
        "groups",
        "catchment",
        "under_represented_below",
        "suppress_below",
    ]
    assert all(choice.option for choice in result.choices)
    assert [check.id for check in result.checks] == [
        "counts_are_people",
        "labels_matched",
        "self_described",
        "catchment",
        "period",
    ]
    assert "Lewisham" in result.checks[3].question
    assert len(result.caveats) == 4
    assert [source.id for source in result.sources] == ["nomis-nm_2041_1"]
    assert all(source.licence and source.url for source in result.sources)
    assert result.working[-1].title == "Hid small counts"
    # A reader must not take every hidden count for a small one.
    assert any("not always small" in note for note in result.privacy.notes)
    assert result.privacy.row_level_output is False
    assert result.privacy.sent_to_third_parties == ()
    json.dumps(result.to_dict())


def test_chart_can_be_drawn_from_the_table(nomis):
    result = _run(CLIENTS)
    (chart,) = result.charts
    table = result.table(chart.table)
    assert table.detail is False
    assert chart.category_column in table.columns
    assert [series.column for series in chart.series] == [
        "share_of_people",
        "share_of_residents",
    ]
    assert {series.unit for series in chart.series} == {"percent"}


def test_there_is_no_map_to_draw(nomis):
    with pytest.raises(ValueError, match="no map"):
        render_map(_run(CLIENTS))


# --- the answer ------------------------------------------------------------

AGAINST = "Set against the people who live in the area you serve, you reach "


def _group(name: str, representation: float | None, cut: float = 0.8) -> dict:
    """One row of the table by group; no representation means a hidden count.

    Each group is 20% of the people who live there, and nobody is recorded in
    a group whose representation is nought.
    """
    hidden = representation is None
    return {
        "group": name,
        "people": None if hidden else round(representation * 100),
        "share_of_people": None if hidden else round(representation * 20, 1),
        "share_of_residents": 20.0,
        "representation": representation,
        "under_represented": None if hidden else representation < cut,
        "suppressed": hidden,
    }


def test_answer_names_the_groups_reached_less_than_their_share(nomis):
    result = _run(CLIENTS)
    assert result.answer == (
        AGAINST + "2 of the 5 groups less than their share: Black and Other. "
        "The first, Black, is 30 of your people, 15.0%, against 25.0% of the "
        "people who live there. Nobody in your data is recorded as Other."
    )
    assert result.key_figures == (
        "groups_under_represented",
        "people_matched",
        "people_not_matched",
    )
    assert {figure.id for figure in result.figures} >= set(result.key_figures)
    assert result.to_dict()["answer"] == result.answer


def test_answer_says_how_many_groups_are_not_judged(nomis):
    rows = _counts(White_British=1200, Black_African=300, Indian=3, Arab=4)
    assert _run(rows).answer == (
        AGAINST + "one group less than its share: Mixed. Nobody in your data "
        "is recorded in that group. 2 more groups have a hidden count and are "
        "not judged."
    )


def test_answer_names_the_least_reached_first_and_counts_the_rest():
    ratios = {"A": 0.5, "B": 0.1, "C": 0.7, "D": 0.3, "E": 2}
    rows = [_group(name, ratio) for name, ratio in ratios.items()]
    assert who_we_miss._answer(rows) == (
        AGAINST + "4 of the 5 groups less than their share: B, D, A and 1 more. "
        "The first, B, is 10 of your people, 2.0%, against 20.0% of the people "
        "who live there."
    )


def test_answer_gives_both_shares_of_a_single_group():
    rows = [_group("A", 0.5), _group("B", 1.2)]
    assert who_we_miss._answer(rows) == (
        AGAINST + "one group less than its share: A. It is 50 of your people, "
        "10.0%, against 20.0% of the people who live there."
    )


def test_answer_names_groups_with_nobody_last_and_says_so():
    # A group with nobody may be one the charity does not record.
    rows = [_group("A", 0), _group("B", 0.5), _group("C", 0), _group("D", 1)]
    assert who_we_miss._answer(rows) == (
        AGAINST + "3 of the 4 groups less than their share: B, A and C. The "
        "first, B, is 50 of your people, 10.0%, against 20.0% of the people who "
        "live there. Nobody in your data is recorded as A or C."
    )


def test_answer_when_no_group_is_reached_less_than_its_share():
    rows = [_group("A", 0.9), _group("B", 1.2), _group("C", None)]
    assert who_we_miss._answer(rows) == (
        AGAINST + "none of the 2 groups less than its share. One more group has "
        "a hidden count and is not judged."
    )


def test_answer_when_every_count_is_hidden():
    rows = [_group("A", None), _group("B", None)]
    assert who_we_miss._answer(rows) == (
        "No group can be set against the people who live in the area you "
        "serve: every count is hidden."
    )


# --- the census figures ----------------------------------------------------


def test_census_figures_are_asked_for_by_local_authority(nomis):
    _run(CLIENTS)
    dataset, query = nomis.asked[0]
    assert dataset == "NM_2041_1"
    assert query["geography_type"] == "LAD"
    assert query["time"] == "latest"
    assert query["measures"] == 20100
    assert "c2021_eth_20_name" in query["select"]


def test_census_figures_are_fetched_once(nomis):
    _run(CLIENTS)
    _run(CLIENTS)
    assert len(nomis.asked) == 1
    clear_residents_cache()
    _run(CLIENTS)
    assert len(nomis.asked) == 2


def test_a_group_is_counted_once_when_nomis_also_lists_its_parts(nomis):
    result = _run(CLIENTS)
    assert [row["residents"] for row in _rows(result).values()] == [
        30000,
        75000,
        24000,
        156000,
        15000,
    ]


def test_parts_are_added_up_when_nomis_has_no_row_for_the_group(nomis):
    nomis.own_rows = False
    result = _run(CLIENTS)
    assert _rows(result)["Black"]["residents"] == 75000
    assert result.figure("residents").value == 300000


def test_a_table_without_every_group_is_an_input_error(nomis):
    nomis.leave_out = "Other ethnic group"
    with pytest.raises(AnalysisInputError, match="does not name every group"):
        _run(CLIENTS)


def test_a_table_without_counts_is_an_input_error():
    empty = pd.DataFrame({"geography_code": ["E09000023"]})
    with (
        mock.patch("uk_open_data.analyses.who_we_miss.load_ons", return_value=empty),
        pytest.raises(AnalysisInputError, match="could not be loaded"),
    ):
        _run(CLIENTS)


def test_scotland_is_not_in_the_census_figures(nomis):
    with pytest.raises(AnalysisInputError, match="City of Edinburgh"):
        _run(CLIENTS, options={"catchment": "City of Edinburgh"})


# --- matching labels to groups ---------------------------------------------


@pytest.mark.parametrize(
    ("label", "group"),
    [
        ("White British", "White"),
        ("white - irish", "White"),
        ("Gypsy or Irish Traveller", "White"),
        ("Any other White background", "White"),
        ("Black or Black British: African", "Black"),
        ("Caribbean", "Black"),
        ("Asian or Asian British - Pakistani", "Asian"),
        ("Chinese", "Asian"),
        ("Any other Asian background", "Asian"),
        ("White and Black Caribbean", "Mixed"),
        ("Mixed: White and Asian", "Mixed"),
        ("Any other mixed background", "Mixed"),
        ("Arab", "Other"),
        ("Any other ethnic group", "Other"),
        ("  ASIAN  ", "Asian"),
    ],
)
def test_labels_are_matched_by_their_wording(nomis, label, group):
    rows = [*CLIENTS, {"Ethnicity": label, "Clients": 1000}]
    with_label, without = _run(rows), _run(CLIENTS)
    gained = {
        key: row["people"] - _rows(without)[key]["people"]
        for key, row in _rows(with_label).items()
    }
    assert gained == {key: 1000 if key == group else 0 for key in GROUPS}


@pytest.mark.parametrize(
    "label", ["Not stated", "Prefer not to say", "Unknown", "Refused", "Code 7", "-"]
)
def test_labels_that_name_no_group_are_left_out(nomis, label):
    rows = [*CLIENTS, {"Ethnicity": label, "Clients": 40}]
    result = _run(rows)
    assert result.figure("people_supplied").value == 240
    assert result.figure("people_matched").value == 200
    assert result.figure("people_not_matched").value == 40
    assert _rows(result)["White"]["share_of_people"] == 60.0
    assert any(w.startswith("40 people have no label") for w in result.warnings)


def test_rows_with_no_label_are_counted_as_not_matched(nomis):
    rows = [
        *CLIENTS,
        {"Ethnicity": None, "Clients": 7},
        {"Ethnicity": " ", "Clients": 3},
    ]
    result = _run(rows)
    assert result.figure("people_not_matched").value == 10
    step = next(s for s in result.working if s.title.startswith("Matched your labels"))
    assert "10 were not, 10 of them with no label" in step.detail
    assert (step.rows_in, step.rows_out) == (210, 200)


def test_groups_option_says_which_group_a_label_belongs_to(nomis):
    rows = [*CLIENTS, {"Ethnicity": "Code 7", "Clients": 50}]
    result = _run(
        rows, options={"catchment": "Lewisham", "groups": {" code 7": "other"}}
    )
    assert _rows(result)["Other"]["people"] == 50
    assert result.figure("people_not_matched").value == 0
    step = next(s for s in result.working if s.title.startswith("Matched your labels"))
    assert "1 were set in 'How your labels match census groups'" in step.detail


def test_groups_option_wins_over_the_wording(nomis):
    result = _run(
        CLIENTS, options={"catchment": "Lewisham", "groups": {"Indian": "Other"}}
    )
    rows = _rows(result)
    assert rows["Asian"]["people"] == 0
    assert rows["Other"]["people"] == 20


@pytest.mark.parametrize(
    "groups", [["Indian"], "Indian", {"Indian": 3}, {"Indian": "South Asian"}]
)
def test_bad_groups_option_is_rejected_without_repeating_a_label(nomis, groups):
    with pytest.raises(
        AnalysisInputError, match="'How your labels match census groups'"
    ) as raised:
        _run(CLIENTS, options={"catchment": "Lewisham", "groups": groups})
    assert "Indian" not in str(raised.value)
    assert raised.value.option == "groups"
    assert "South Asian" not in str(raised.value)


def test_no_label_from_the_data_reaches_the_result(nomis):
    rows = [*CLIENTS, {"Ethnicity": "Jedi Knight", "Clients": 6}]
    text = json.dumps(_run(rows).to_dict()).casefold()
    for label in ("jedi", "indian", "white british", "caribbean", "african"):
        assert label not in text


# Labels a charity is likely to hold: the detailed census categories, common
# short forms, and the ways of saying "not known".
ETHNIC_GROUP_LABELS = (
    "English, Welsh, Scottish, Northern Irish or British",
    "Irish",
    "Gypsy or Irish Traveller",
    "Roma",
    "Any other White background",
    "White and Black Caribbean",
    "White and Black African",
    "White and Asian",
    "Any other Mixed or Multiple ethnic background",
    "Indian",
    "Pakistani",
    "Bangladeshi",
    "Chinese",
    "Any other Asian background",
    "African",
    "Caribbean",
    "Any other Black, Black British, or Caribbean background",
    "Arab",
    "Any other ethnic group",
    "Asian, Asian British or Asian Welsh",
    "Black, Black British, Black Welsh, Caribbean or African",
    "Mixed or Multiple ethnic groups",
    "Other ethnic group",
    "White British",
    "Black British",
    "Asian British",
    "Mixed race",
    "Dual heritage",
    "British",
    "Welsh",
    "Somali",
    "Polish",
    "BAME",
    "Not stated",
    "Not known",
    "Not recorded",
    "Unknown",
    "Prefer not to say",
    "Refused",
    "Missing",
    "None",
    "White",
    "black",
    "ASIAN",
    "Mixed",
    "Other",
)
SEX_LABELS = (
    "Female",
    "male",
    "Woman",
    "Women",
    "Girl",
    "Trans woman",
    "Trans man",
    "Non-binary",
    "Intersex",
    "Prefer to self-describe",
    "Other gender",
    "Prefer not to say",
    "Not stated",
    "Unknown",
)


@pytest.mark.parametrize(
    ("characteristic", "labels"),
    [("ethnic_group", ETHNIC_GROUP_LABELS), ("sex", SEX_LABELS)],
)
def test_a_check_for_repeated_labels_finds_none(nomis, characteristic, labels):
    # What the connector does: leave out the values the role lists as public,
    # and look for every other label anywhere in the result.
    public = {
        value.casefold()
        for value in describe_analysis(ANALYSIS_ID).roles[0].reported_values
    }
    guarded = [label for label in labels if label.casefold() not in public]
    assert len(guarded) == len(labels) - (5 if characteristic == "ethnic_group" else 2)
    rows = [{"Ethnicity": label, "Clients": 7 + n} for n, label in enumerate(labels)]
    result = _run(
        rows, options={"catchment": "Lewisham", "characteristic": characteristic}
    )
    assert result.figure("people_not_matched").value > 0
    assert find_row_values(result.to_dict(), guarded) == []


# --- sex -------------------------------------------------------------------


def test_people_can_be_grouped_by_sex(nomis):
    rows = _counts(Female=30, F=10, Woman=20, Male=120, M=20, Non_binary=5)
    result = _run(rows, options={"catchment": "Lewisham", "characteristic": "sex"})
    assert nomis.asked[0][0] == "NM_2028_1"
    table = _rows(result)
    assert list(table) == ["Female", "Male"]
    assert table["Female"]["people"] == 60
    assert table["Female"]["share_of_people"] == 30.0
    assert table["Female"]["share_of_residents"] == 52.0
    assert table["Female"]["representation"] == 0.58
    assert table["Female"]["under_represented"] is True
    assert table["Male"]["under_represented"] is False
    assert result.figure("people_not_matched").value == 5
    assert [source.id for source in result.sources] == ["nomis-nm_2028_1"]
    choice = next(c for c in result.choices if c.id == "characteristic")
    assert choice.value == "Sex"


def test_a_label_that_names_both_sexes_is_not_matched(nomis):
    rows = _counts(Female=50, Male=50, Male_to_female=9)
    result = _run(rows, options={"catchment": "Lewisham", "characteristic": "sex"})
    assert result.figure("people_not_matched").value == 9


@pytest.mark.parametrize("characteristic", ["age", "", None, 3])
def test_unknown_characteristic_is_rejected(nomis, characteristic):
    with pytest.raises(AnalysisInputError, match="'What people are grouped by'"):
        _run(
            CLIENTS, options={"catchment": "Lewisham", "characteristic": characteristic}
        )


# --- small counts ----------------------------------------------------------


def test_a_small_count_is_hidden_with_a_second_so_it_cannot_be_worked_out(nomis):
    rows = _counts(White_British=120, Black_African=30, Indian=20, Arab=3)
    result = _run(rows)
    table = _rows(result)
    assert table["Other"]["suppressed"] is True
    # The smallest count that is shown would give it away, so it goes too.
    assert table["Asian"]["suppressed"] is True
    for key in ("Other", "Asian"):
        assert table[key]["people"] is None
        assert table[key]["share_of_people"] is None
        assert table[key]["representation"] is None
        assert table[key]["under_represented"] is None
        # The census figures are public and stay.
        assert table[key]["residents"] > 0
        assert table[key]["share_of_residents"] > 0
    assert table["Mixed"]["people"] == 0
    assert table["White"]["people"] == 120
    assert result.privacy.cells_suppressed == 2
    under = result.figure("groups_under_represented")
    # Black at 0.69 and Mixed at 0. The hidden groups are not judged.
    assert under.value == 2
    assert under.note == "2 groups have a hidden count and are not judged."


def test_hidden_counts_are_nowhere_in_the_result(nomis):
    rows = _counts(White_British=1200, Black_African=300, Indian=3, Arab=4)
    payload = _run(rows).to_dict()
    table = {row["group"]: row for row in payload["tables"][0]["rows"]}
    assert table["Asian"]["people"] is None
    assert table["Other"]["people"] is None
    shown = {figure["id"]: figure["value"] for figure in payload["figures"]}
    assert shown["people_matched"] == 1507
    # 1507 less the two counts shown leaves 7 between two hidden groups.
    assert table["White"]["people"] + table["Black"]["people"] == 1500


def test_the_threshold_can_be_raised(nomis):
    rows = _counts(White_British=120, Black_African=30, Indian=8, Arab=9)
    usual = _run(rows)
    careful = _run(rows, options={"catchment": "Lewisham", "suppress_below": 10})
    assert usual.privacy.cells_suppressed == 0
    assert careful.privacy.cells_suppressed == 2
    assert _rows(careful)["Asian"]["people"] is None


def test_both_sexes_are_hidden_when_one_count_is_small(nomis):
    rows = _counts(Female=3, Male=60)
    result = _run(rows, options={"catchment": "Lewisham", "characteristic": "sex"})
    assert [row["suppressed"] for row in _rows(result).values()] == [True, True]
    assert result.figure("groups_under_represented").value == 0


def test_too_few_people_is_an_input_error(nomis):
    with pytest.raises(AnalysisInputError, match="Fewer than 5 people"):
        _run(_counts(White_British=4, Not_stated=3))


def test_labels_that_match_nothing_are_the_reason_given_not_too_few_people(nomis):
    with pytest.raises(AnalysisInputError) as raised:
        _run(_counts(White_British=4, Not_stated=30))
    message = str(raised.value)
    assert message.startswith(
        "30 people have no label, or a label that matched no census group, so "
        "too few are left to give figures."
    )
    assert "'How your labels match census groups'" in message
    assert "Not stated" not in message  # the label as typed is not repeated


def test_few_people_brings_a_warning_about_chance(nomis):
    few = _run(_counts(White_British=60, Black_African=30))
    many = _run(CLIENTS)
    flag = "Fewer than 100 people were matched"
    assert any(w.startswith(flag) for w in few.warnings)
    assert not any(w.startswith(flag) for w in many.warnings)


# --- options and input that cannot be used ---------------------------------


@pytest.mark.parametrize("value", [0, 1.5, -1, "0.8", True, None])
def test_bad_line_for_under_represented_is_rejected(nomis, value):
    with pytest.raises(AnalysisInputError, match="'What counts as under-represented'"):
        _run(
            CLIENTS, options={"catchment": "Lewisham", "under_represented_below": value}
        )


@pytest.mark.parametrize("value", [0, 2, "a twentieth", False])
def test_bad_catchment_share_is_rejected(nomis, value):
    with pytest.raises(
        AnalysisInputError, match="'Share that makes a place part of your area'"
    ):
        _run(CLIENTS, options={"catchment": "Lewisham", "catchment_min_share": value})


@pytest.mark.parametrize("count", [-1, 2.5, "lots", None])
def test_bad_counts_are_rejected(nomis, count):
    rows = [*CLIENTS, {"Ethnicity": "Arab", "Clients": count}]
    with pytest.raises(
        AnalysisInputError,
        match="1 row had a count that is not a whole number of zero or more: row",
    ):
        _run(rows)


# --- the catchment ---------------------------------------------------------


def test_catchment_must_be_given_without_postcodes(nomis):
    with pytest.raises(AnalysisInputError, match="Fill in 'Area you serve'"):
        _run(CLIENTS, options={})


def test_catchment_can_name_local_authorities_by_name_or_code(nomis):
    result = _run(CLIENTS, options={"catchment": ["lewisham", "E09000011"]})
    assert result.figure("residents").value == 600000
    # 135,000 of 600,000 residents are Black, and 30 of 200 clients.
    assert _rows(result)["Black"]["share_of_residents"] == 22.5
    choice = next(c for c in result.choices if c.id == "catchment")
    assert choice.value == "Greenwich, Lewisham"
    assert choice.reason == "You gave the area."


def test_catchment_can_be_a_country(nomis):
    wales = _run(CLIENTS, options={"catchment": "Wales"})
    assert wales.figure("residents").value == 350000
    england = _run(CLIENTS, options={"catchment": "england"})
    assert england.figure("residents").value == 600000
    both = _run(CLIENTS, options={"catchment": "England and Wales"})
    assert both.figure("residents").value == 950000


@pytest.mark.parametrize("catchment", [["Lewisham", "Narnia"], 7, [], [""]])
def test_bad_catchment_is_rejected(nomis, catchment):
    with pytest.raises(AnalysisInputError, match="Area you serve") as caught:
        _run(CLIENTS, options={"catchment": catchment})
    assert caught.value.option == "catchment"


# --- one row per person ----------------------------------------------------


def test_rows_of_people_are_counted_one_each(nomis):
    people = (
        [{"Ethnic group": "White British"}] * 120
        + [{"Ethnic group": "Black African"}] * 30
        + [{"Ethnic group": "Bangladeshi"}] * 50
    )
    result = run_analysis(
        ANALYSIS_ID,
        people,
        columns={"group": "Ethnic group"},
        options={"catchment": "Lewisham"},
    )
    assert result.input_mode == "people"
    assert result.figure("people_supplied").value == 200
    assert _rows(result)["Black"]["representation"] == 0.6
    assert result.checks[0].id == "one_row_one_person"


# --- postcodes -------------------------------------------------------------

# Real postcodes never end in C, I, K, M, O or V, so none of these can exist.
PLACES = {
    "SE13 7VC": "E09000023",
    "SE13 6CM": "E09000023",
    "SE10 9OK": "E09000011",
    "CF10 1VC": "W06000015",
    "EH1 1VC": "S12000036",
}
# 150 people in Lewisham, 46 in Greenwich, 4 in Cardiff and 6 in Edinburgh.
# Three more cannot be placed.
PEOPLE = (
    [("SE13 7VC", "White British")] * 90
    + [("se136cm", "Black African")] * 30
    + [("SE13 7VC", "Indian")] * 30
    + [("SE10 9OK", "White Irish")] * 40
    + [("SE10 9OK", "Not stated")] * 6
    + [("CF10 1VC", "White Welsh")] * 4
    + [("EH1 1VC", "White Scottish")] * 6
    + [("SE13 7VO", "Arab"), ("not a postcode", "Arab"), ("", "Arab")]
)
PERSON_ROWS = [{"Home postcode": p, "Ethnicity": label} for p, label in PEOPLE]
PERSON_COLUMNS = {"postcode": "Home postcode", "group": "Ethnicity"}


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


def _run_people(options=None, sent=None):
    with mock.patch(
        "uk_open_data.analyses._steps.postcodes_to_geography",
        side_effect=_fake_lookup([] if sent is None else sent),
    ):
        return run_analysis(
            ANALYSIS_ID, PERSON_ROWS, columns=PERSON_COLUMNS, options=options
        )


def test_catchment_is_worked_out_from_where_people_live(nomis):
    sent: list = []
    result = _run_people(sent=sent)
    assert result.input_mode == "postcodes"
    level, postcodes = sent[0]
    assert level == "LAD"
    assert postcodes == sorted(set(postcodes))
    # Cardiff holds 4 of the 200 people placed in England and Wales, which is
    # under 5%, so the catchment is Lewisham and Greenwich.
    choice = next(c for c in result.choices if c.id == "catchment")
    assert choice.value == "Greenwich, Lewisham"
    assert "at least 5%" in choice.reason
    assert result.figure("people_supplied").value == 209
    assert result.figure("people_in_catchment").value == 196
    assert result.figure("people_matched").value == 190
    assert result.figure("people_not_matched").value == 6
    assert result.figure("residents").value == 600000
    rows = _rows(result)
    assert [row["people"] for row in rows.values()] == [30, 30, 0, 130, 0]
    assert any(w.startswith("10 people live outside") for w in result.warnings)
    assert "local authorities" in result.privacy.sent_to_third_parties[0]
    assert result.checks[0].id == "one_row_one_person"


def test_a_lower_share_brings_more_places_into_the_catchment(nomis):
    result = _run_people(options={"catchment_min_share": 0.02})
    choice = next(c for c in result.choices if c.id == "catchment")
    # Places are listed in the order of their codes, so England comes first.
    assert choice.value == "Greenwich, Lewisham, Cardiff"
    assert result.figure("people_in_catchment").value == 200


def test_whole_of_england_and_wales_is_used_when_people_are_spread_thin(nomis):
    result = _run_people(options={"catchment_min_share": 0.9})
    choice = next(c for c in result.choices if c.id == "catchment")
    assert choice.value == "England and Wales"
    assert result.figure("residents").value == 950000


def test_a_named_catchment_leaves_out_people_who_live_elsewhere(nomis):
    result = _run_people(options={"catchment": "Lewisham"})
    assert result.figure("people_in_catchment").value == 150
    assert [row["people"] for row in _rows(result).values()] == [30, 30, 0, 90, 0]
    assert any(w.startswith("56 people live outside") for w in result.warnings)
    step = next(s for s in result.working if s.title.startswith("Kept the people"))
    assert (step.rows_in, step.rows_out) == (206, 150)


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
        result = run_analysis(ANALYSIS_ID, PERSON_ROWS, columns=PERSON_COLUMNS)
    online.assert_not_called()
    assert result.privacy.sent_to_third_parties == ()
    assert result.figure("people_in_catchment").value == 196


def test_no_postcode_reaches_the_result(nomis):
    text = json.dumps(_run_people().to_dict()).upper().replace(" ", "")
    for postcode, _ in PEOPLE:
        compact = postcode.upper().replace(" ", "")
        assert not compact or compact not in text


# --- census figures kept on this machine -----------------------------------

KEPT = [
    (code, name, dict(zip(GROUPS, residents, strict=True)))
    for code, name, residents in RESIDENTS
]


def test_kept_census_figures_are_used_without_asking_nomis(nomis):
    assert residents_path() is None
    path = keep_residents("ethnic_group", KEPT, note="invented for a test.")
    assert residents_path() == path
    result = _run(CLIENTS)
    assert nomis.asked == []
    assert _rows(result)["Black"]["representation"] == 0.6
    (source,) = result.sources
    assert source.edition.endswith("A copy kept on this machine, invented for a test.")
    assert "A copy kept on this machine was used" in result.working[0].detail


def test_kept_figures_are_for_one_characteristic(nomis):
    keep_residents("ethnic_group", KEPT, note="invented for a test.")
    assert residents_path("sex") is None
    rows = _counts(Female=60, Male=140)
    _run(rows, options={"catchment": "Lewisham", "characteristic": "sex"})
    assert [dataset for dataset, _ in nomis.asked] == ["NM_2028_1"]


def test_census_figures_can_be_downloaded_and_kept(nomis):
    path = download_residents("ethnic_group")
    assert path == residents_path("ethnic_group")
    assert len(nomis.asked) == 1
    result = _run(CLIENTS)
    assert len(nomis.asked) == 1
    assert _rows(result)["Black"]["residents"] == 75000
    assert "fetched from Nomis on" in result.sources[0].edition


def test_kept_figures_that_cannot_be_read_are_an_input_error(nomis):
    path = keep_residents("ethnic_group", KEPT, note="invented for a test.")
    path.write_text('{"format": "something else"}', encoding="utf-8")
    with pytest.raises(AnalysisInputError, match="download_residents"):
        _run(CLIENTS)


def test_kept_figures_for_other_groups_are_not_read_as_these(nomis):
    path = keep_residents("ethnic_group", KEPT, note="invented for a test.")
    kept = json.loads(path.read_text(encoding="utf-8"))
    kept["groups"] = list(reversed(kept["groups"]))
    path.write_text(json.dumps(kept), encoding="utf-8")
    with pytest.raises(AnalysisInputError, match="download_residents"):
        _run(CLIENTS)


def test_keeping_figures_needs_a_known_characteristic_and_every_group():
    with pytest.raises(ValueError, match="No characteristic called 'age'"):
        keep_residents("age", KEPT, note="invented for a test.")
    short = [("E09000023", "Lewisham", {"Asian": 1, "Black": 2})]
    with pytest.raises(ValueError, match="needs a count for"):
        keep_residents("ethnic_group", short, note="invented for a test.")
    with pytest.raises(ValueError, match="No characteristic called 'age'"):
        download_residents("age")


# --- the command line ------------------------------------------------------


def test_command_line_runs_the_analysis(nomis, tmp_path, capsys):
    path = tmp_path / "counts.csv"
    path.write_text(
        "Ethnicity,Clients\nWhite British,120\nBlack African,30\nCode 7,50\n",
        encoding="utf-8",
    )
    code = main(
        [
            "analysis",
            "run",
            ANALYSIS_ID,
            str(path),
            "--column",
            "group=Ethnicity",
            "--column",
            "count=Clients",
            "--option",
            "catchment=Lewisham",
            "--option",
            'groups={"Code 7": "Asian"}',
        ]
    )
    out = capsys.readouterr().out
    assert code == EXIT_OK
    assert "Who we are missing" in out
    assert "Groups you reach less than their share of residents: 3" in out


def test_command_line_says_when_there_is_no_map(nomis, tmp_path, capsys):
    path = tmp_path / "counts.csv"
    path.write_text("group,count\nWhite British,120\nIndian,30\n", encoding="utf-8")
    code = main(
        [
            "analysis",
            "run",
            ANALYSIS_ID,
            str(path),
            "--option",
            "catchment=Lewisham",
            "--map",
            str(tmp_path / "map.svg"),
        ]
    )
    assert code == EXIT_INPUT_ERROR
    assert "no map" in capsys.readouterr().err
