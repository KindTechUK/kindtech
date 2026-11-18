"""
Unit tests for the need against reach lens.

The need figures and the postcode lookup are replaced with small invented
tables, so the tests are isolated and repeatable.
"""

import json
import unittest.mock as mock
import xml.etree.ElementTree as ET

import pandas as pd
import pytest

from kindtech.cli import EXIT_OK, main
from kindtech.lenses import LensInputError, describe_lens, render_map, run_lens
from kindtech.lenses.need_reach import (
    NEED_BANDS,
    NO_REACH,
    REACH_BANDS,
    clear_need_cache,
    download_need_figures,
    keep_need_figures,
    need_figures_path,
)
from kindtech.postcodes import build_postcode_table, install_postcode_table

LENS_ID = "need-reach"
COLUMNS = {"local_authority": "Area", "count": "Clients"}

# Invented need figures for real local authority codes. The middle value is
# 8,500, so the last four are high need.
NEED = (
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


class _Nomis:
    """Stands in for Nomis and records what it was asked."""

    def __init__(self) -> None:
        self.asked: list[tuple[str, dict]] = []

    def load(self, dataset: str, **query) -> pd.DataFrame:
        """Return each authority's need split over four rows, as Nomis would."""
        self.asked.append((dataset, query))
        rows = [
            {"geography_code": code, "geography_name": name, "obs_value": need / 4}
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
    with mock.patch("kindtech.lenses.need_reach.load_ons", side_effect=fake.load):
        yield fake


def _counts(**people: int) -> list[dict]:
    """Rows of counts by local authority name, with the user's column names."""
    return [
        {"Area": name.replace("_", " "), "Clients": n} for name, n in people.items()
    ]


def _run(rows, options=None, columns=COLUMNS):
    return run_lens(LENS_ID, rows, columns=columns, options=options)


def _names(table) -> list[str]:
    return [row["geography_name"] for row in table.rows]


# --- the lens is listed ----------------------------------------------------


def test_lens_is_described():
    info = describe_lens(LENS_ID)
    assert info.question == "Where is need high and our presence low?"
    assert [mode.name for mode in info.input_modes] == ["postcodes", "area_counts"]
    assert info.input_modes[1].aggregated
    assert {option.name for option in info.options} == {
        "suppress_below",
        "postcode_lookup",
        "need",
        "catchment",
        "top",
    }
    assert info.coverage == "England and Wales"
    # Local authorities are public places the result names. Nothing else may
    # come back from the input.
    reported = {role.name: role.reported for role in info.roles}
    assert reported == {"postcode": False, "local_authority": True, "count": False}


# --- counts by local authority ---------------------------------------------


def test_figures_from_counts(nomis):
    result = _run(_counts(Lewisham=60, Greenwich=30, Adur=10))
    assert result.input_mode == "area_counts"
    assert result.figure("people_supplied").value == 100
    assert result.figure("people_located").value == 100
    assert result.figure("people_in_catchment").value == 100
    assert result.figure("areas_compared").value == 8
    assert result.figure("people_in_need").value == 91020
    assert result.figure("reach_per_100_in_need").value == 0.11
    assert result.figure("high_need_areas").value == 4
    assert result.figure("high_need_areas_without_people").value == 3
    assert result.figure("share_of_people_in_high_need_areas").value == 60.0
    assert result.figure("share_of_need_in_high_need_areas").value == 86.8


def test_need_is_added_up_for_england_and_wales_only(nomis):
    result = _run(_counts(Lewisham=60))
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
    _run(_counts(Lewisham=60))
    _run(_counts(Greenwich=30), options={"catchment": "England"})
    assert len(nomis.asked) == 1
    _run(_counts(Lewisham=60), options={"need": "unemployed_women"})
    assert len(nomis.asked) == 2
    clear_need_cache()
    _run(_counts(Lewisham=60))
    assert len(nomis.asked) == 3


# --- need figures kept on this machine -------------------------------------

INVENTED = [(code, name, need * 2) for code, name, need in NEED]


def test_kept_need_figures_are_used_and_nothing_is_fetched(nomis):
    assert need_figures_path() is None
    path = keep_need_figures("unemployed", INVENTED, "invented for a demonstration.")
    assert need_figures_path() == path
    result = _run(_counts(Lewisham=60))
    assert nomis.asked == []
    assert result.figure("people_in_need").value == 182040
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
    assert len(nomis.asked) == 1
    _run(_counts(Lewisham=60), options={"need": "unemployed_women"})
    assert len(nomis.asked) == 1


def test_download_fetches_and_keeps_the_figures(nomis):
    path = download_need_figures("unemployed_men")
    assert path == need_figures_path("unemployed_men")
    assert nomis.asked[0][1]["c_sex"] == [2]
    result = _run(_counts(Lewisham=60), options={"need": "unemployed_men"})
    assert len(nomis.asked) == 1
    assert result.figure("people_in_need").value == 91020
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
    with pytest.raises(LensInputError, match="kept on this machine could not be read"):
        _run(_counts(Lewisham=60))
    assert nomis.asked == []


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
    assert "Disabled people" in result.figure("people_in_need").label
    assert result.sources[0].id == "nomis-nm_2056_1"
    assert not any("21 March 2021" in caveat for caveat in result.caveats)
    assert any("latest that Nomis holds" in caveat for caveat in result.caveats)


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
    with pytest.raises(LensInputError, match="need"):
        _run(_counts(Lewisham=60), options={"need": need})
    assert nomis.asked == []


def test_a_table_nomis_does_not_have_is_an_input_error():
    with (
        mock.patch(
            "kindtech.lenses.need_reach.load_ons",
            side_effect=ValueError("NOMIS dataset 'NM_0_0' does not exist."),
        ),
        pytest.raises(LensInputError, match="could not be loaded"),
    ):
        _run(
            _counts(Lewisham=60),
            options={"need": {"dataset": "NM_0_0", "label": "Nothing"}},
        )


def test_filters_that_are_not_plain_values_are_an_input_error(nomis):
    need = {"dataset": "NM_2056_1", "label": "x", "filters": {"c_sex": {1, 2}}}
    with pytest.raises(LensInputError, match="could not be loaded"):
        _run(_counts(Lewisham=60), options={"need": need})


def test_need_without_local_authorities_is_an_input_error():
    empty = pd.DataFrame(
        {"geography_code": ["S12000036"], "geography_name": ["x"], "obs_value": [5]}
    )
    with (
        mock.patch("kindtech.lenses.need_reach.load_ons", return_value=empty),
        pytest.raises(LensInputError, match="no local authority"),
    ):
        _run(_counts(Lewisham=60))


def test_places_can_be_names_or_codes_in_any_case(nomis):
    rows = [
        {"Area": "lewisham ", "Clients": 20},
        {"Area": "E09000023", "Clients": "1,000"},
        {"Area": "e09000011", "Clients": 30.0},
    ]
    result = _run(rows)
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
    assert any(w.startswith("1 rows named a local authority") for w in result.warnings)
    assert any(w.startswith("9 people were placed outside") for w in result.warnings)
    assert "Atlantis" not in json.dumps(result.to_dict())


def test_bad_counts_are_an_input_error(nomis):
    rows = [*_counts(Lewisham=60), {"Area": "Adur", "Clients": "a few"}]
    with pytest.raises(LensInputError, match="1 rows have a count"):
        _run(rows)


def test_too_few_people_is_an_input_error(nomis):
    with pytest.raises(LensInputError, match="Fewer than 5 people"):
        _run(_counts(Lewisham=4))


# --- the list of places ----------------------------------------------------


def test_priority_areas_are_high_need_with_the_lowest_reach(nomis):
    result = _run(_counts(Lewisham=90, Cardiff=10, Manchester=40, Greenwich=50))
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
    result = _run(_counts(Greenwich=50))
    table = result.table("priority_areas")
    assert _names(table) == ["Birmingham", "Manchester", "Cardiff", "Lewisham"]


def test_top_sets_the_length_of_the_list(nomis):
    result = _run(_counts(Greenwich=50), options={"top": 2})
    assert _names(result.table("priority_areas")) == ["Birmingham", "Manchester"]
    choice = next(c for c in result.choices if c.id == "top")
    assert choice.value == 2


@pytest.mark.parametrize("top", [0, 51, 2.5, "ten", True])
def test_bad_top_is_rejected(nomis, top):
    with pytest.raises(LensInputError, match="top"):
        _run(_counts(Greenwich=50), options={"top": top})


# --- small counts ----------------------------------------------------------


def test_small_counts_are_hidden_in_both_tables(nomis):
    result = _run(_counts(Lewisham=60, Birmingham=3, Cardiff=4, Greenwich=30))
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
    result = _run(_counts(Lewisham=60, Birmingham=3, Cardiff=4, Manchester=6))
    assert _names(result.table("priority_areas")) == [
        "Birmingham",
        "Manchester",
        "Cardiff",
        "Lewisham",
    ]


def test_one_small_count_has_the_smallest_other_count_hidden_with_it(nomis):
    # The total is shown, so Birmingham's 3 could be worked out if it were the
    # only count hidden. Adur's 8 is the smallest other count.
    result = _run(_counts(Lewisham=60, Birmingham=3, Cardiff=20, Adur=8))
    rows = {r["geography_name"]: r for r in result.table("by_local_authority").rows}
    assert rows["Birmingham"]["suppressed"] is True
    assert rows["Adur"]["suppressed"] is True
    assert rows["Cardiff"]["people"] == 20
    assert rows["Lewisham"]["people"] == 60
    # Birmingham is then the only hidden count among the high-need places.
    assert result.figure("share_of_people_in_high_need_areas").suppressed is True
    assert result.privacy.cells_suppressed == 3


def test_a_count_hidden_to_protect_another_is_flagged_in_the_list(nomis):
    result = _run(_counts(Lewisham=60, Birmingham=3, Cardiff=20))
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


def test_suppress_below_can_be_raised_but_not_dropped(nomis):
    result = _run(
        _counts(Lewisham=60, Cardiff=8, Manchester=9),
        options={"suppress_below": 10},
    )
    rows = {r["geography_name"]: r for r in result.table("by_local_authority").rows}
    assert rows["Cardiff"]["people"] is None
    assert rows["Manchester"]["people"] is None
    with pytest.raises(LensInputError, match="suppress_below"):
        _run(_counts(Lewisham=60), options={"suppress_below": 2})


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
    # The middle value of 1,000, 8,000 and 9,000 is 8,000.
    assert _names(result.table("priority_areas")) == ["Greenwich", "Lewisham"]
    choice = next(c for c in result.choices if c.id == "catchment")
    assert choice.value == "Adur, Greenwich, Lewisham"
    check = next(c for c in result.checks if c.id == "catchment")
    assert "Adur, Greenwich, Lewisham" in check.question


def test_catchment_can_be_a_country(nomis):
    wales = _run(_counts(Cardiff=10), options={"catchment": "Wales"})
    assert _names(wales.table("by_local_authority")) == ["Cardiff"]
    england = _run(_counts(Lewisham=10), options={"catchment": "england"})
    assert england.figure("areas_compared").value == 7
    both = _run(_counts(Lewisham=10), options={"catchment": "England and Wales"})
    assert both.figure("areas_compared").value == 8


@pytest.mark.parametrize("catchment", [["Lewisham", "Narnia"], 7, [], [""]])
def test_bad_catchment_is_rejected(nomis, catchment):
    with pytest.raises(LensInputError, match="catchment"):
        _run(_counts(Lewisham=60), options={"catchment": catchment})


def test_catchment_with_too_few_people_is_an_input_error(nomis):
    with pytest.raises(LensInputError, match="live in the catchment"):
        _run(_counts(Lewisham=60, Adur=2), options={"catchment": "Adur"})


def test_a_wide_comparison_is_flagged_when_people_are_in_few_places():
    many = pd.DataFrame(
        {
            "geography_code": [f"E0600{n:04d}" for n in range(30)],
            "geography_name": [f"Place {n}" for n in range(30)],
            "obs_value": [100 + n for n in range(30)],
        }
    )
    rows = [{"Area": "Place 1", "Clients": 40}, {"Area": "Place 2", "Clients": 20}]
    with mock.patch("kindtech.lenses.need_reach.load_ons", return_value=many):
        wide = _run(rows)
        named = _run(rows, options={"catchment": "England"})
    flag = "Your people live in 2 of the 30 local authorities compared."
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
        "kindtech.lenses._steps.postcodes_to_geography", side_effect=_fake_lookup(sent)
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
    with mock.patch("kindtech.lenses._steps.postcodes_to_geography") as online:
        result = _run(POSTCODE_ROWS, columns=POSTCODE_COLUMN)
    online.assert_not_called()
    assert result.privacy.sent_to_third_parties == ()
    assert result.figure("people_located").value == 45
    source = next(s for s in result.sources if s.id == "ons-postcode-lookup")
    assert source.used_for == "Finding the local authority each postcode is in."


def test_no_postcode_reaches_the_result(nomis):
    with mock.patch(
        "kindtech.lenses._steps.postcodes_to_geography", side_effect=_fake_lookup([])
    ):
        result = _run(POSTCODE_ROWS, columns=POSTCODE_COLUMN)
    text = json.dumps(result.to_dict()).upper().replace(" ", "")
    for postcode in PEOPLE:
        compact = postcode.upper().replace(" ", "")
        assert not compact or compact not in text


# --- the map ---------------------------------------------------------------


def test_map_is_described_by_local_authority(nomis):
    result = _run(_counts(Lewisham=60, Greenwich=30, Adur=10, Cardiff=3, Manchester=4))
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
    assert rows["Birmingham"]["need_band"] == "Highest fifth"
    assert rows["Isles of Scilly"]["need_band"] == "Lowest fifth"
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


# --- the whole result ------------------------------------------------------


def test_result_explains_itself(nomis):
    result = _run(_counts(Lewisham=60, Greenwich=30, Adur=10))
    assert result.lens_id == LENS_ID
    assert [step.title for step in result.working] == [
        "Loaded the need figures",
        "Read the local authority counts",
        "Joined people to the need figures",
        "Set the area to compare",
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
    option_names = {option.name for option in describe_lens(LENS_ID).options}
    for choice in result.choices:
        assert choice.option is None or choice.option in option_names
    summary = result.to_dict(include_detail=False)
    json.dumps(summary)
    detail = next(t for t in summary["tables"] if t["id"] == "by_local_authority")
    assert detail["rows"] == []


def test_command_line_runs_the_lens(nomis, tmp_path, capsys):
    path = tmp_path / "counts.csv"
    path.write_text("Area,Clients\nLewisham,60\nGreenwich,30\n", encoding="utf-8")
    code = main(
        [
            "lens",
            "run",
            LENS_ID,
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
    assert payload["lens_id"] == LENS_ID
    assert nomis.asked[0][1]["c_sex"] == [1]
