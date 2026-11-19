"""
Unit tests for the analysis interface and the first analysis.

The deprivation index and the postcode lookup are replaced with small invented
tables, so the tests are isolated and repeatable.
"""

import json
import logging
import unittest.mock as mock

import pandas as pd
import pytest

from uk_open_data.analyses import (
    AnalysisInputError,
    Figure,
    describe_analysis,
    list_analyses,
    reach_deprivation,
    record_run,
    register_analysis,
    run_analysis,
)
from uk_open_data.analyses._inputs import (
    TabularData,
    resolve_columns,
    tidy_postcode,
    to_count,
)
from uk_open_data.analyses._privacy import band_labels, cells_to_hide, count_band
from uk_open_data.analyses.reach_deprivation import ANALYSIS
from uk_open_data.imd import keep_imd

ANALYSIS_ID = "reach-deprivation"
POSTCODE_COLUMN = {"postcode": "Client postcode"}
AUTHORITIES = (
    ("E09000023", "Lewisham"),
    ("E09000011", "Greenwich"),
    ("E06000001", "Hartlepool"),
)


def _area_code(authority: int, decile: int) -> str:
    """The invented code for an authority's neighbourhood of a given decile."""
    return f"E01{authority}{decile:05d}"


def _index() -> pd.DataFrame:
    """An invented index: three authorities, one area of 1,000 per decile."""
    rows = [
        {
            "geography_code": _area_code(position, decile),
            "geography_name": f"{name} {decile:03d}A",
            "lad_code": code,
            "lad_name": name,
            "imd_decile": decile,
            "population": 1000,
        }
        for position, (code, name) in enumerate(AUTHORITIES)
        for decile in range(1, 11)
    ]
    return pd.DataFrame(rows)


# Real postcodes never end in these letters, so the invented ones cannot be real.
UNUSED_LETTERS = "CIKMOV"


def _postcode(number: int) -> str:
    """An invented postcode: the right shape, but it cannot exist."""
    district, rest = divmod(number, 36)
    first, second = divmod(rest, 6)
    return f"SE{district + 1} 1{UNUSED_LETTERS[first]}{UNUSED_LETTERS[second]}"


class _World:
    """Invented people, with the postcode lookup that places them."""

    def __init__(self) -> None:
        self.lookup: dict[str, str | None] = {}
        self.rows: list[dict[str, str]] = []
        self.sent: list[str] = []

    def add(self, authority: int, decile: int, people: int) -> None:
        """Add people who live in one neighbourhood."""
        for _ in range(people):
            postcode = _postcode(len(self.lookup))
            self.lookup[postcode] = _area_code(authority, decile)
            self.rows.append({"Client postcode": postcode})

    def fake_lookup(self, postcodes: list[str], level: str) -> pd.DataFrame:
        """Stand in for the postcode lookup and record what was sent."""
        self.sent.extend(postcodes)
        return pd.DataFrame(
            {
                "postcode": postcodes,
                "geography_code": [self.lookup.get(item) for item in postcodes],
                "geography_name": [None] * len(postcodes),
            }
        )

    def run(self, rows=None, columns=POSTCODE_COLUMN, options=None):
        """Run the analysis against the invented index and lookup."""
        with (
            mock.patch(
                "uk_open_data.analyses.reach_deprivation.load_imd",
                return_value=_index(),
            ),
            mock.patch(
                "uk_open_data.analyses._steps.postcodes_to_geography",
                side_effect=self.fake_lookup,
            ),
        ):
            return run_analysis(
                ANALYSIS_ID,
                self.rows if rows is None else rows,
                columns=columns,
                options=options,
            )


@pytest.fixture
def world() -> _World:
    """Sixty people in Lewisham and ten in Greenwich, mostly deprived areas."""
    world = _World()
    world.add(0, 1, 30)
    world.add(0, 2, 12)
    world.add(0, 3, 10)
    world.add(0, 10, 8)
    world.add(1, 1, 6)
    world.add(1, 5, 4)
    return world


# --- privacy helpers -------------------------------------------------------


def test_cells_to_hide_hides_small_counts_and_a_partner():
    assert cells_to_hide([30, 3, 12, 0], 5) == [False, True, True, False]


def test_cells_to_hide_prefers_a_partner_from_the_same_group():
    groups = ((0, 1), (2, 3))
    assert cells_to_hide([30, 12, 3, 15], 5, groups) == [False, False, True, True]
    assert cells_to_hide([30, 12, 3, 0], 5, groups) == [False, True, True, False]


def test_cells_to_hide_needs_no_partner_when_two_are_small():
    assert cells_to_hide([30, 3, 2, 12], 5) == [False, True, True, False]


def test_cells_to_hide_leaves_zero_and_large_counts():
    assert cells_to_hide([0, 5, 100], 5) == [False, False, False]


def test_count_band_puts_zero_with_small_counts():
    assert count_band(0, 5) == count_band(4, 5) == "fewer than 5"
    assert count_band(5, 5) == "5 to 9"
    assert count_band(49, 5) == "20 to 49"
    assert count_band(50, 5) == "50 or more"
    assert band_labels(5) == [
        "fewer than 5",
        "5 to 9",
        "10 to 19",
        "20 to 49",
        "50 or more",
    ]


# --- input helpers ---------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("se137vc", "SE13 7VC"),
        ("  SE13  7VC ", "SE13 7VC"),
        ("M1 1VC", "M1 1VC"),
        ("EC1A 1VC", "EC1A 1VC"),
        ("not a postcode", None),
        ("SE13", None),
        ("", None),
        (None, None),
        (float("nan"), None),
    ],
)
def test_tidy_postcode(raw, expected):
    assert tidy_postcode(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(3, 3), ("12", 12), ("1,200", 1200), (4.0, 4), (0, 0)],
)
def test_to_count_accepts_whole_numbers(raw, expected):
    assert to_count(raw) == expected


@pytest.mark.parametrize("raw", [-1, 2.5, "many", None, "", True, float("nan")])
def test_to_count_rejects_everything_else(raw):
    assert to_count(raw) is None


def test_tabular_data_reads_rows_and_frames_alike():
    rows = [{"a": 1, "b": "x"}, {"a": 2}]
    from_rows = TabularData(rows)
    from_frame = TabularData(pd.DataFrame({"a": [1, 2], "b": ["x", "y"]}))
    assert from_rows.columns == from_frame.columns == ["a", "b"]
    assert from_rows.n_rows == from_frame.n_rows == 2
    assert from_rows.values("b") == ["x", None]
    assert from_frame.values("a") == [1, 2]


def test_tabular_data_rejects_other_types():
    with pytest.raises(AnalysisInputError, match="DataFrame"):
        TabularData("clients.csv")


def test_resolve_columns_uses_mapping_then_role_names():
    matched = resolve_columns(
        ["Client postcode", "count"],
        ["postcode", "count"],
        {"postcode": "Client postcode"},
    )
    assert matched == {"postcode": "Client postcode", "count": "count"}


def test_resolve_columns_reports_unknown_roles_and_columns():
    with pytest.raises(AnalysisInputError) as raised:
        resolve_columns(["a"], ["postcode"], {"postcode": "b", "age": "a"})
    assert len(raised.value.problems) == 2


# --- the interface ---------------------------------------------------------


def test_list_and_describe_analyses():
    assert ANALYSIS_ID in [analysis.id for analysis in list_analyses()]
    info = describe_analysis(ANALYSIS_ID)
    assert [mode.name for mode in info.input_modes] == [
        "postcodes",
        "neighbourhood_counts",
    ]
    assert [mode.aggregated for mode in info.input_modes] == [False, True]
    json.dumps(info.to_dict())


def test_amount_roles_are_marked_in_every_analysis():
    # A count or a volume is added up, so a lone row's number comes back as
    # its place's total. Nothing else that is a number may come back.
    amounts = {
        analysis.id: [role.name for role in analysis.roles if role.amount]
        for analysis in list_analyses()
    }
    assert amounts == {
        "reach-deprivation": ["count"],
        "need-reach": ["count"],
        "who-we-miss": ["count"],
        "provision-gap": ["volume"],
        "access-distance": [],
    }
    roles = describe_analysis("provision-gap").to_dict()["roles"]
    assert {role["name"]: role["amount"] for role in roles} == {
        "postcode": False,
        "local_authority": False,
        "volume": True,
    }


def test_unknown_analysis_names_the_known_ones():
    with pytest.raises(KeyError, match=ANALYSIS_ID):
        describe_analysis("no-such-analysis")


def test_registering_the_same_analysis_twice_fails():
    with pytest.raises(ValueError, match="already registered"):
        register_analysis(ANALYSIS)


def test_unknown_option_is_rejected(world):
    with pytest.raises(AnalysisInputError, match="no option called colour"):
        world.run(options={"colour": "red"})


def test_missing_columns_say_what_is_needed(world):
    with pytest.raises(
        AnalysisInputError, match="'postcode' or 'lsoa_code' and 'count'"
    ):
        world.run(rows=[{"Name": "x"}], columns={})


# --- the first analysis --------------------------------------------------------


def test_figures_from_postcodes(world):
    result = world.run()
    assert result.input_mode == "postcodes"
    assert result.figure("people_supplied").value == 70
    assert result.figure("people_located").value == 70
    assert result.figure("people_in_catchment").value == 70
    # 36 of 70 live in decile 1; 48 of 70 in deciles 1 and 2.
    assert result.figure("share_most_deprived_10").value == 51.4
    assert result.figure("share_most_deprived_20").value == 68.6
    # Two authorities, each with 2 of 10 equal areas in deciles 1 and 2.
    assert result.figure("catchment_share_most_deprived_20").value == 20.0
    assert result.figure("reach_per_1000_most_deprived_20").value == 12.0
    assert result.figure("reach_per_1000_elsewhere").value == 1.38


def test_catchment_is_where_most_people_live(world):
    world.add(2, 1, 3)  # three people in Hartlepool: under 5% of 73
    result = world.run()
    catchment = next(choice for choice in result.choices if choice.id == "catchment")
    assert catchment.value == ["Lewisham", "Greenwich"]
    assert catchment.option == "catchment"
    assert result.figure("people_located").value == 73
    assert result.figure("people_in_catchment").value == 70
    assert any("3 people live outside the catchment" in w for w in result.warnings)
    other = result.table("by_local_authority").rows[-1]
    assert other["lad_name"] == "Other local authorities"
    assert other["lad_code"] is None
    assert other["people"] == 3


def test_decile_table_hides_small_counts_and_a_partner(world):
    rows = world.run().table("by_decile").rows
    by_decile = {row["imd_decile"]: row for row in rows}
    # Decile 5 has 4 people, so it is hidden, and the next smallest (8) with it.
    assert by_decile[5]["people"] is None
    assert by_decile[5]["people_per_1000"] is None
    assert by_decile[5]["suppressed"] is True
    assert by_decile[10]["suppressed"] is True
    assert by_decile[1]["people"] == 36
    assert by_decile[1]["people_per_1000"] == 18.0
    assert by_decile[4]["people"] == 0
    assert by_decile[5]["residents"] == 2000  # public figures are never hidden


def test_partner_cell_comes_from_the_same_side_so_the_headline_survives():
    world = _World()
    world.add(0, 1, 30)
    world.add(0, 2, 12)
    world.add(0, 4, 3)  # hidden; its partner is decile 9, not the smaller decile 2
    world.add(0, 9, 15)
    result = world.run()
    hidden = [
        row["imd_decile"] for row in result.table("by_decile").rows if row["suppressed"]
    ]
    assert hidden == [4, 9]
    assert result.figure("share_most_deprived_20").value == 70.0
    assert result.figure("reach_per_1000_most_deprived_20").value == 21.0
    assert result.privacy.cells_suppressed == 2


def test_headline_is_hidden_when_it_would_give_a_cell_away():
    world = _World()
    world.add(0, 1, 3)  # hidden; nothing else in deciles 1 and 2 to pair it with
    world.add(0, 3, 10)
    world.add(0, 6, 20)
    result = world.run()
    hidden = [
        row["imd_decile"] for row in result.table("by_decile").rows if row["suppressed"]
    ]
    assert hidden == [1, 3]
    for figure_id in (
        "share_most_deprived_10",
        "share_most_deprived_20",
        "reach_per_1000_most_deprived_20",
        "reach_per_1000_elsewhere",
    ):
        figure = result.figure(figure_id)
        assert figure.value is None
        assert figure.suppressed is True
    assert result.privacy.cells_suppressed == 6


def test_rows_that_cannot_be_used_are_counted_not_quoted(world):
    world.rows += [
        {"Client postcode": ""},
        {"Client postcode": "Flat 2, Secret Road"},
        {"Client postcode": "ZZ99 9VC"},
    ]
    result = world.run()
    assert result.figure("people_supplied").value == 73
    assert result.figure("people_located").value == 70
    assert len(result.warnings) == 3
    text = json.dumps(result.to_dict())
    assert "Secret Road" not in text
    assert "ZZ99" not in text
    assert "Flat 2, Secret Road" not in world.sent


def test_result_never_holds_a_postcode(world):
    text = json.dumps(world.run().to_dict())
    for row in world.rows:
        assert row["Client postcode"] not in text
    assert world.run().privacy.row_level_output is False


def test_each_distinct_postcode_is_sent_once(world):
    world.rows += world.rows[:5]
    result = world.run()
    assert len(world.sent) == len(set(world.sent)) == 70
    assert result.figure("people_supplied").value == 75
    assert "70 distinct postcodes" in result.privacy.sent_to_third_parties[0]


def test_neighbourhood_counts_send_nothing_out(world):
    rows = [
        {"lsoa_code": _area_code(0, 1), "count": 30},
        {"lsoa_code": _area_code(0, 1).lower(), "count": "6"},
        {"lsoa_code": _area_code(0, 4), "count": 14},
        {"lsoa_code": "W01000001", "count": 7},
    ]
    result = world.run(rows=rows, columns={})
    assert result.input_mode == "neighbourhood_counts"
    assert world.sent == []
    assert result.privacy.sent_to_third_parties == ()
    assert [source.id for source in result.sources] == ["iod-2025"]
    assert result.figure("people_supplied").value == 57
    assert result.figure("people_located").value == 50
    assert result.figure("share_most_deprived_10").value == 72.0
    assert any("7 people were placed outside England" in w for w in result.warnings)


def test_bad_counts_are_reported_without_their_values(world):
    rows = [
        {"lsoa_code": _area_code(0, 1), "count": "lots"},
        {"lsoa_code": _area_code(0, 2), "count": -3},
    ]
    with pytest.raises(AnalysisInputError) as raised:
        world.run(rows=rows, columns={})
    assert "2 rows" in str(raised.value)
    assert "lots" not in str(raised.value)


def test_named_catchment_by_name_or_code(world):
    result = world.run(options={"catchment": ["lewisham"]})
    assert result.figure("people_in_catchment").value == 60
    assert result.figure("catchment_share_most_deprived_20").value == 20.0
    rows = result.table("by_local_authority").rows
    assert [row["in_catchment"] for row in rows] == [True, False]
    same = world.run(options={"catchment": "E09000023"})
    assert same.figure("people_in_catchment").value == 60


def test_unknown_catchment_is_rejected(world):
    with pytest.raises(AnalysisInputError, match="Narnia"):
        world.run(options={"catchment": ["Lewisham", "Narnia"]})


def test_whole_of_england_has_no_map(world):
    result = world.run(options={"catchment": "England"})
    assert result.map is None
    assert result.figure("people_in_catchment").value == 70
    assert [table.id for table in result.tables] == ["by_decile", "by_local_authority"]
    assert any("No map" in warning for warning in result.warnings)


def test_map_table_bands_every_catchment_neighbourhood(world):
    result = world.run()
    assert result.map is not None
    assert result.map.table == "by_neighbourhood"
    table = result.table("by_neighbourhood")
    assert table.detail is True
    assert len(table.rows) == 20  # every area of Lewisham and Greenwich
    bands = {row["geography_code"]: row["people_band"] for row in table.rows}
    assert bands[_area_code(0, 1)] == "20 to 49"
    assert bands[_area_code(1, 5)] == "fewer than 5"  # four people
    assert bands[_area_code(1, 9)] == "fewer than 5"  # nobody
    assert "people" not in table.columns


def test_summary_leaves_out_map_rows(world):
    result = world.run()
    summary = result.to_dict(include_detail=False)
    tables = {table["id"]: table for table in summary["tables"]}
    assert tables["by_neighbourhood"]["rows"] == []
    assert len(tables["by_decile"]["rows"]) == 10
    full = result.to_dict()
    assert len(full["tables"][-1]["rows"]) == 20


def test_table_to_frame(world):
    frame = world.run().table("by_decile").to_frame()
    assert list(frame.columns)[:2] == ["imd_decile", "people"]
    assert len(frame) == 10


def test_too_few_people_is_an_error():
    world = _World()
    world.add(0, 1, 4)
    with pytest.raises(AnalysisInputError, match="Fewer than 5 people"):
        world.run()


def test_too_few_people_in_a_named_catchment_is_an_error(world):
    world.add(2, 1, 3)
    with pytest.raises(AnalysisInputError, match="Hartlepool"):
        world.run(options={"catchment": "Hartlepool"})


def test_no_postcodes_at_all_points_at_the_column(world):
    with pytest.raises(AnalysisInputError, match="right column"):
        world.run(rows=[{"Client postcode": "Anna"}, {"Client postcode": "Ben"}])


@pytest.mark.parametrize(
    "options",
    [
        {"suppress_below": 2},
        {"suppress_below": "5"},
        {"suppress_below": True},
        {"catchment_min_share": 0},
        {"catchment_min_share": 1.5},
        {"catchment": 7},
    ],
)
def test_bad_options_are_rejected(world, options):
    with pytest.raises(AnalysisInputError):
        world.run(options=options)


def test_result_explains_itself(world):
    result = world.run(options={"suppress_below": 10})
    assert result.privacy.suppress_below == 10
    assert [check.id for check in result.checks] == [
        "one_row_one_person",
        "home_postcode",
        "period",
        "catchment",
    ]
    assert len(result.caveats) == 3
    assert [source.id for source in result.sources] == ["postcodes-io", "iod-2025"]
    assert all(source.licence and source.url for source in result.sources)
    assert result.working[0].rows_in == 70
    assert result.working[-1].title == "Hid small counts"
    # A reader must not take every hidden count for a small one.
    assert any("not always small" in note for note in result.privacy.notes)
    json.dumps(result.to_dict())


# --- the answer ------------------------------------------------------------

MOST_DEPRIVED_ANSWER = (
    "Of your people in the area you serve, {ours}% live in the 20% most "
    "deprived neighbourhoods in England. Of everyone who lives in that area, "
    "20.0% do, so you reach those neighbourhoods {verdict} their share."
)


def test_answer_opens_the_result_with_the_question_answered(world):
    result = world.run()
    assert result.answer == MOST_DEPRIVED_ANSWER.format(
        ours="68.6", verdict="more than"
    )
    assert result.key_figures == (
        "share_most_deprived_20",
        "catchment_share_most_deprived_20",
        "reach_per_1000_most_deprived_20",
    )
    payload = result.to_dict()
    assert payload["answer"] == result.answer
    assert payload["key_figures"] == list(result.key_figures)


@pytest.mark.parametrize(
    ("people", "ours", "verdict"),
    [
        ([(1, 5), (6, 45)], "10.0", "less than"),
        ([(1, 10), (2, 10), (5, 80)], "20.0", "in line with"),
    ],
)
def test_answer_says_which_way_the_comparison_falls(people, ours, verdict):
    world = _World()
    for decile, number in people:
        world.add(0, decile, number)
    assert world.run().answer == MOST_DEPRIVED_ANSWER.format(ours=ours, verdict=verdict)


def test_answer_does_not_give_away_a_hidden_share():
    world = _World()
    world.add(0, 1, 3)  # hidden, and so is the share that rests on it
    world.add(0, 3, 10)
    world.add(0, 6, 20)
    assert world.run().answer == (
        "Of everyone who lives in the area you serve, 20.0% live in the 20% "
        "most deprived neighbourhoods in England. The share of your people who "
        "do is hidden to protect a small count."
    )


def test_answer_when_the_area_has_no_deprived_neighbourhood():
    figures = [
        Figure("share_most_deprived_20", "", 0.0, "percent"),
        Figure("catchment_share_most_deprived_20", "", 0.0, "percent"),
    ]
    assert reach_deprivation._answer(figures, whole_country=False) == (
        "No neighbourhood in the area you serve is among the 20% most deprived "
        "in England, so none of your people there live in one."
    )


def test_answer_says_england_when_the_area_is_the_whole_country(world):
    result = world.run(options={"catchment": "England"})
    assert result.answer.startswith(
        "Of your people in England, 68.6% live in the 20% most deprived "
        "neighbourhoods in England. Of everyone who lives in England, "
    )
    assert "area you serve" not in result.answer
    assert "outside" not in result.answer


def test_answer_says_how_many_people_a_narrow_area_leaves_out():
    world = _World()
    world.add(0, 1, 30)
    world.add(0, 6, 30)
    world.add(1, 1, 20)  # a quarter of the people, in the other local authority
    result = world.run(options={"catchment": AUTHORITIES[0][1]})
    assert result.answer.endswith(
        " 20 of your people live outside that area and are not counted in these shares."
    )
    # A few people outside the area are not worth a sentence.
    world.add(0, 3, 40)
    assert "outside" not in world.run(options={"catchment": AUTHORITIES[0][1]}).answer


def test_a_hidden_key_figure_gives_way_to_one_that_can_be_shown():
    world = _World()
    world.add(0, 1, 3)  # hidden, and so is the share that rests on it
    world.add(0, 3, 10)
    world.add(0, 6, 20)
    result = world.run()
    assert result.key_figures == (
        "catchment_share_most_deprived_20",
        "people_in_catchment",
        "people_located",
    )
    assert not any(result.figure(i).suppressed for i in result.key_figures)


def test_key_figures_are_figures_of_the_result(world):
    result = world.run()
    assert {figure.id for figure in result.figures} >= set(result.key_figures)


# --- the index kept on this machine ----------------------------------------


def test_analysis_runs_on_an_index_kept_on_this_machine():
    keep_imd(_index(), note="invented for a test.")
    rows = [
        {"lsoa_code": _area_code(0, 1), "count": 30},
        {"lsoa_code": _area_code(0, 4), "count": 14},
    ]
    with mock.patch("uk_open_data.imd.api.requests.get") as get:
        result = run_analysis(ANALYSIS_ID, rows)
    get.assert_not_called()
    assert result.figure("people_located").value == 44
    source = next(s for s in result.sources if s.id == "iod-2025")
    assert source.edition.endswith("A copy kept on this machine, invented for a test.")
    step = result.working[1]
    assert step.title == "Read the deprivation index kept on this machine"
    assert step.detail.endswith("The copy was invented for a test.")


def test_an_index_kept_on_this_machine_that_cannot_be_read_is_an_input_error():
    path = keep_imd(_index(), note="invented for a test.")
    path.write_text("not json", encoding="utf-8")
    with pytest.raises(AnalysisInputError, match="download_imd"):
        run_analysis(ANALYSIS_ID, [{"lsoa_code": _area_code(0, 1), "count": 30}])


def test_an_error_from_the_download_is_not_blamed_on_a_kept_copy():
    with (
        mock.patch(
            "uk_open_data.analyses.reach_deprivation.load_imd",
            side_effect=ValueError("the published file changed"),
        ),
        pytest.raises(ValueError, match="the published file changed") as raised,
    ):
        run_analysis(ANALYSIS_ID, [{"lsoa_code": _area_code(0, 1), "count": 30}])
    assert not isinstance(raised.value, AnalysisInputError)


# --- options with a fixed list of values -----------------------------------


def test_options_with_a_fixed_list_say_what_can_be_picked():
    for analysis in list_analyses():
        for option in analysis.options:
            values = [choice.value for choice in option.choices]
            assert len(set(values)) == len(values)
            assert all(choice.label for choice in option.choices)
            # The value used when nothing is picked is one that can be picked.
            assert not values or option.default in values
    lookup = {o.name: o for o in describe_analysis(ANALYSIS_ID).options}[
        "postcode_lookup"
    ]
    assert [choice.value for choice in lookup.choices] == ["auto", "offline", "online"]
    assert {o.name: o for o in describe_analysis(ANALYSIS_ID).options}[
        "catchment"
    ].choices == ()


def test_choices_are_in_the_description_as_plain_json_types():
    options = {
        o["name"]: o for o in describe_analysis(ANALYSIS_ID).to_dict()["options"]
    }
    assert options["postcode_lookup"]["choices"][1] == {
        "value": "offline",
        "label": "On this machine only",
    }
    assert options["suppress_below"]["choices"] == []
    json.dumps(options)


# --- charts ----------------------------------------------------------------


@pytest.mark.parametrize("analysis_id", ["reach-deprivation", "need-reach"])
def test_every_chart_can_be_drawn_from_a_table_in_the_result(world, analysis_id):
    if analysis_id == ANALYSIS_ID:
        result = world.run()
    else:
        need = pd.DataFrame(
            {
                "geography_code": ["E09000023", "E09000011"],
                "geography_name": ["Lewisham", "Greenwich"],
                "obs_value": [9000, 8000],
            }
        )
        with mock.patch("uk_open_data.analyses._need.load_ons", return_value=need):
            result = run_analysis(
                analysis_id, [{"local_authority": "Lewisham", "count": 60}]
            )
    assert result.charts
    for chart in result.charts:
        table = result.table(chart.table)
        assert table.detail is False
        assert chart.kind == "bar"
        assert chart.category_column in table.columns
        assert len({series.unit for series in chart.series}) == 1
        for series in chart.series:
            assert series.column in table.columns
    payload = result.to_dict()
    assert [chart["id"] for chart in payload["charts"]] == [
        chart.id for chart in result.charts
    ]
    json.dumps(payload["charts"])


def test_decile_chart_sets_people_against_residents(world):
    chart = world.run().charts[0]
    assert chart.id == "people_by_decile"
    assert chart.table == "by_decile"
    assert chart.category_column == "imd_decile"
    assert [series.column for series in chart.series] == [
        "share_of_people",
        "share_of_residents",
    ]


# --- counting completed runs -----------------------------------------------

RUNS_LOGGER = "uk_open_data.runs"


def test_record_run_writes_one_record_with_three_fixed_words(caplog):
    with caplog.at_level(logging.INFO, logger=RUNS_LOGGER):
        record_run(ANALYSIS_ID, "postcodes", "page")
    (record,) = caplog.records
    assert record.name == RUNS_LOGGER
    assert record.levelno == logging.INFO
    assert record.getMessage() == (
        "run analysis=reach-deprivation mode=postcodes door=page"
    )
    assert record.analysis_id == ANALYSIS_ID
    assert record.input_mode == "postcodes"
    assert record.door == "page"


@pytest.mark.parametrize(
    ("analysis_id", "input_mode", "door", "error"),
    [
        ("SE13 7VC", "postcodes", "page", KeyError),
        (ANALYSIS_ID, "SE13 7VC", "page", ValueError),
        (ANALYSIS_ID, "postcodes", "SE13 7VC", ValueError),
        (ANALYSIS_ID, "postcodes", "python", ValueError),
    ],
)
def test_record_run_refuses_a_word_off_its_lists_without_repeating_it(
    analysis_id, input_mode, door, error, caplog
):
    with (
        caplog.at_level(logging.INFO, logger=RUNS_LOGGER),
        pytest.raises(error) as raised,
    ):
        record_run(analysis_id, input_mode, door)
    assert caplog.records == []
    assert "SE13" not in str(raised.value)
    assert "python" not in str(raised.value)


def test_running_an_analysis_records_nothing_by_itself(world, caplog):
    # A run from Python is not counted: only a door that gave a person an
    # answer calls record_run.
    with caplog.at_level(logging.INFO, logger=RUNS_LOGGER):
        world.run()
    assert caplog.records == []
