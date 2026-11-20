"""
Unit tests for the access and distance analysis.

The need figures, the centres of local authorities and neighbourhoods and the
postcode lookup are replaced with small invented tables, so the tests are
isolated and repeatable.
"""

import json
import unittest.mock as mock
import xml.etree.ElementTree as ET

import pandas as pd
import pytest
import requests
from working_checks import check_working

from uk_open_data.analyses import (
    AnalysisInputError,
    describe_analysis,
    render_map,
    run_analysis,
)
from uk_open_data.analyses._centres import distance_km
from uk_open_data.analyses.access_distance import (
    DISTANCE_BANDS,
    centres_path,
    download_centres,
    keep_centres,
)
from uk_open_data.analyses.need_reach import NEED_BANDS, keep_need_figures
from uk_open_data.cli import EXIT_OK, main
from uk_open_data.connector.privacy import find_row_values
from uk_open_data.postcodes import build_postcode_table, install_postcode_table

ANALYSIS_ID = "access-distance"
COLUMNS = {"latitude": "Lat", "longitude": "Lon"}

# Invented people for real local authority codes.
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
# Rough centres, to two decimal places.
CENTRES = (
    ("E06000053", 49.92, -6.30),
    ("E07000223", 50.85, -0.32),
    ("E06000001", 54.68, -1.21),
    ("E09000011", 51.47, 0.05),
    ("E09000023", 51.45, -0.02),
    ("W06000015", 51.50, -3.20),
    ("E08000003", 53.47, -2.23),
    ("E08000025", 52.48, -1.88),
)
# One invented site in Lewisham and one in Manchester.
SITES = [{"Lat": 51.4613, "Lon": -0.0117}, {"Lat": "53.48", "Lon": " -2.24 "}]


@pytest.fixture
def kept():
    """Keep invented people and centres, so nothing is fetched."""
    keep_need_figures("residents", NEED, "invented for a test.")
    keep_centres(CENTRES, "invented for a test.")


def _run(rows=SITES, options=None, columns=COLUMNS):
    return run_analysis(ANALYSIS_ID, rows, columns=columns, options=options)


def _names(table) -> list[str]:
    return [row["geography_name"] for row in table.rows]


def _by_name(table) -> dict[str, dict]:
    return {row["geography_name"]: row for row in table.rows}


# --- the analysis is listed ----------------------------------------------------


def test_analysis_is_described():
    info = describe_analysis(ANALYSIS_ID)
    assert info.question.startswith("How far are people from our nearest site")
    modes = {mode.name: mode for mode in info.input_modes}
    assert list(modes) == ["site_coordinates", "site_postcodes"]
    assert modes["site_coordinates"].roles == ("latitude", "longitude")
    assert modes["site_postcodes"].roles == ("postcode",)
    # A list of sites is not a table of totals.
    assert not any(mode.aggregated for mode in info.input_modes)
    # The analysis hides nothing, so it has no threshold to set.
    assert [option.name for option in info.options] == [
        "postcode_lookup",
        "need",
        "catchment",
        "within_km",
        "top",
    ]
    assert info.coverage == "England and Wales"
    assert not any(role.reported for role in info.roles)
    need = next(option for option in info.options if option.name == "need")
    assert need.default == "residents"
    assert "residents" in [choice.value for choice in need.choices]


def test_distance_is_in_a_straight_line_over_the_globe():
    london, paris = (51.5074, -0.1278), (48.8566, 2.3522)
    assert distance_km(london, paris) == pytest.approx(343.6, abs=0.1)
    assert distance_km(london, london) == 0


# --- figures ---------------------------------------------------------------


def test_figures_from_site_positions(kept):
    result = _run()
    assert result.input_mode == "site_coordinates"
    values = {figure.id: figure.value for figure in result.figures}
    assert values == {
        "sites_supplied": 2,
        "sites_located": 2,
        "areas_compared": 8,
        "people_in_need": 91020,
        "average_distance_km": 80.8,
        "share_of_people_within_reach": 40.7,
        "people_beyond_reach": 54020,
        "areas_beyond_reach": 5,
        "farthest_distance_km": 475,
    }
    assert result.figure("people_in_need").label.endswith("(Residents of every age)")


def test_each_place_is_measured_to_its_nearest_site(kept):
    table = _by_name(_run().table("by_local_authority"))
    assert table["Lewisham"]["distance_km"] == 1
    assert table["Greenwich"]["distance_km"] == 4
    assert table["Manchester"]["distance_km"] == 1
    # Birmingham is nearer the Manchester site, Cardiff the Lewisham one.
    assert table["Birmingham"]["distance_km"] == 114
    assert table["Cardiff"]["distance_km"] == 221
    assert table["Greenwich"]["within_reach"] is True
    assert table["Birmingham"]["within_reach"] is False


def test_priority_areas_are_beyond_reach_with_the_most_people_first(kept):
    table = _run().table("priority_areas")
    assert _names(table) == [
        "Birmingham",
        "Cardiff",
        "Hartlepool",
        "Adur",
        "Isles of Scilly",
    ]
    assert [row["rank"] for row in table.rows] == [1, 2, 3, 4, 5]
    assert table.rows[0]["people_in_need"] == 40000
    assert table.rows[0]["distance_km"] == 114


def test_top_sets_the_length_of_the_list(kept):
    table = _run(options={"top": 2}).table("priority_areas")
    assert _names(table) == ["Birmingham", "Cardiff"]


@pytest.mark.parametrize("top", [0, 51, 2.5, "ten", True])
def test_bad_top_is_rejected(kept, top):
    with pytest.raises(AnalysisInputError, match="Places listed") as caught:
        _run(options={"top": top})
    assert caught.value.option == "top"


def test_within_km_moves_the_line(kept):
    result = _run(options={"within_km": 120})
    assert result.figure("areas_beyond_reach").value == 3
    assert result.figure("share_of_people_within_reach").value == 85.7
    assert "120 km" in result.figure("areas_beyond_reach").label
    assert _names(result.table("priority_areas")) == [
        "Cardiff",
        "Hartlepool",
        "Isles of Scilly",
    ]
    choice = next(c for c in result.choices if c.id == "within_km")
    assert choice.value == "120 km"
    assert choice.reason == "You set the distance."


def test_the_reason_for_the_distance_fits_the_distance_used(kept):
    choice = next(c for c in _run().choices if c.id == "within_km")
    assert choice.value == "10 km"
    assert choice.reason.startswith("10 km is what the analysis uses when no distance")
    # The reason is true for a person who set 10 themselves.
    asked = next(
        c for c in _run(options={"within_km": 10}).choices if c.id == "within_km"
    )
    assert asked.reason == choice.reason
    assert "No distance was given" not in asked.reason
    # The analysis measures no time, so no choice may speak of one.
    for result in (_run(), _run(options={"within_km": 3})):
        text = " ".join(f"{c.value} {c.reason}" for c in result.choices)
        assert "hour" not in text
        assert "minute" not in text


def test_a_distance_on_the_line_is_within_reach(kept):
    table = _by_name(_run(options={"within_km": 4}).table("by_local_authority"))
    assert table["Greenwich"]["within_reach"] is True
    table = _by_name(_run(options={"within_km": 3.5}).table("by_local_authority"))
    assert table["Greenwich"]["within_reach"] is False


@pytest.mark.parametrize("within", [0, -1, 501, "near", True, None])
def test_bad_within_km_is_rejected(kept, within):
    with pytest.raises(
        AnalysisInputError, match="Distance within reach, in kilometres"
    ) as caught:
        _run(options={"within_km": within})
    assert caught.value.option == "within_km"


def test_nowhere_beyond_reach_is_said_not_hidden(kept):
    result = _run(options={"within_km": 500})
    assert result.table("priority_areas").rows == []
    assert result.figure("share_of_people_within_reach").value == 100.0
    assert any(
        w.startswith("The centre of every local authority in the area you serve")
        for w in result.warnings
    )


# --- the answer ------------------------------------------------------------

AVERAGE = (
    "Counting each person at the centre of their local authority, {who} are "
    "80.8 km from your nearest site on average, and {share} are within "
    "{within} km of one."
)


def test_answer_says_how_far_people_are_and_where_a_site_would_help(kept):
    result = _run()
    assert result.answer == (
        AVERAGE.format(who="residents", share="40.7%", within="10")
        + " Of the places farther away, a new site would reach most residents "
        "in Birmingham."
    )
    assert result.key_figures == (
        "average_distance_km",
        "share_of_people_within_reach",
        "areas_beyond_reach",
    )
    assert {figure.id for figure in result.figures} >= set(result.key_figures)
    assert result.to_dict()["answer"] == result.answer


def test_answer_says_when_nowhere_is_beyond_reach(kept):
    result = _run(options={"within_km": 500})
    assert result.answer == (
        AVERAGE.format(who="residents", share="all", within="500")
        + " No local authority in the area you serve is farther away than that."
    )


def test_answer_says_none_when_no_place_is_within_reach(kept):
    # The two sites are a little way from the centres they are nearest to.
    result = _run(options={"within_km": 0.1})
    assert result.figure("areas_beyond_reach").value == len(NEED)
    assert ", and none are within 0.1 km of one." in result.answer


def test_answer_says_people_in_need_when_a_need_is_chosen(kept):
    keep_need_figures("unemployed", NEED, "invented for a test.")
    result = _run(options={"need": "unemployed"})
    assert result.answer == (
        AVERAGE.format(who="people in need", share="40.7%", within="10")
        + " Of the places farther away, a new site would reach most people in "
        "need in Birmingham."
    )


# --- the need and the catchment --------------------------------------------


def test_need_can_be_another_built_in_measure(kept):
    doubled = [(code, name, people * 2) for code, name, people in NEED]
    keep_need_figures("unemployed_women", doubled, "invented for a test.")
    result = _run(options={"need": "unemployed_women"})
    assert result.figure("people_in_need").value == 182040
    assert "women" in result.figure("people_in_need").label


@pytest.mark.parametrize("need", ["everyone", 7, None, {"dataset": "NM_1_1"}])
def test_bad_need_is_rejected(kept, need):
    with pytest.raises(
        AnalysisInputError, match="People you are trying to reach"
    ) as caught:
        _run(options={"need": need})
    assert caught.value.option == "need"


def test_catchment_can_name_local_authorities(kept):
    result = _run(options={"catchment": ["Lewisham", "Greenwich", "Adur"]})
    assert result.figure("areas_compared").value == 3
    assert result.figure("people_in_need").value == 18000
    assert _names(result.table("priority_areas")) == ["Adur"]
    choice = next(c for c in result.choices if c.id == "catchment")
    assert choice.reason == "You gave the area."


def test_a_site_outside_the_catchment_still_counts_as_the_nearest(kept):
    result = _run(options={"catchment": "Wales"})
    assert result.figure("areas_compared").value == 1
    table = _by_name(result.table("by_local_authority"))
    assert table["Cardiff"]["distance_km"] == 221


@pytest.mark.parametrize("catchment", [["Lewisham", "Narnia"], 7, [], [""]])
def test_bad_catchment_is_rejected(kept, catchment):
    with pytest.raises(AnalysisInputError, match="Area you serve") as caught:
        _run(options={"catchment": catchment})
    assert caught.value.option == "catchment"


def test_a_place_without_a_centre_is_left_out_and_counted(kept):
    keep_centres(CENTRES[:6], "invented for a test.")
    result = _run()
    assert result.figure("areas_compared").value == 6
    assert "Birmingham" not in _names(result.table("by_local_authority"))
    assert any(w.startswith("2 local authorities in the area") for w in result.warnings)


def test_a_catchment_without_any_centre_is_an_input_error(kept):
    keep_centres(CENTRES[:5], "invented for a test.")
    with pytest.raises(AnalysisInputError, match="Area you serve") as caught:
        _run(options={"catchment": "Wales"})
    assert caught.value.option == "catchment"


# --- reading the positions -------------------------------------------------


def test_rows_that_cannot_be_placed_are_counted_not_repeated(kept):
    rows = [
        *SITES,
        {"Lat": "", "Lon": -0.5},
        {"Lat": "north a bit", "Lon": -0.5},
        {"Lat": 51.5, "Lon": None},
        {"Lat": 999, "Lon": 0},
        {"Lat": -0.0117, "Lon": 51.4613},
        {"Lat": 40.4168, "Lon": -3.7038},
    ]
    result = _run(rows)
    assert result.figure("sites_supplied").value == 8
    assert result.figure("sites_located").value == 2
    assert any(w.startswith("4 rows had no latitude") for w in result.warnings)
    assert any(w.startswith("2 rows hold a position outside") for w in result.warnings)
    text = json.dumps(result.to_dict())
    assert "north a bit" not in text
    assert "40.4168" not in text


def test_swapped_columns_are_an_input_error_that_says_so(kept):
    with pytest.raises(AnalysisInputError, match="swapped"):
        _run(columns={"latitude": "Lon", "longitude": "Lat"})


def test_no_position_reaches_the_result(kept):
    payload = _run().to_dict()
    given = [value for row in SITES for value in row.values()]
    assert find_row_values(payload, given) == []
    text = json.dumps(payload)
    for value in ("51.4613", "0.0117", "53.48", "2.24"):
        assert value not in text


# --- site postcodes --------------------------------------------------------

# Real postcodes never end in C, I, K, M, O or V, so none of these can exist.
PLACES = {
    "SE13 7VC": (51.4613, -0.0117),
    "M1 1VC": (53.48, -2.24),
    "EH1 1VC": (55.95, -3.19),
}
POSTCODE_ROWS = [
    {"Site postcode": postcode}
    for postcode in ["SE13 7VC", "se137vc", "M1 1VC", "SE13 7VO", "not one", ""]
]
POSTCODE_COLUMN = {"postcode": "Site postcode"}


def _fake_lookup(sent: list):
    def lookup(postcodes: list[str]) -> pd.DataFrame:
        sent.append(list(postcodes))
        found = [PLACES.get(postcode, (None, None)) for postcode in postcodes]
        return pd.DataFrame(
            {
                "postcode": postcodes,
                "latitude": [latitude for latitude, _ in found],
                "longitude": [longitude for _, longitude in found],
            }
        )

    return lookup


def _run_postcodes(rows=POSTCODE_ROWS, sent=None):
    with mock.patch(
        "uk_open_data.analyses._steps.lookup_postcodes",
        side_effect=_fake_lookup([] if sent is None else sent),
    ):
        return _run(rows, columns=POSTCODE_COLUMN)


def test_site_postcodes_are_placed_online_and_the_result_says_so(kept):
    sent: list = []
    result = _run_postcodes(sent=sent)
    assert result.input_mode == "site_postcodes"
    assert sent == [["M1 1VC", "SE13 7VC", "SE13 7VO"]]
    assert result.figure("sites_supplied").value == 6
    assert result.figure("sites_located").value == 3
    table = _by_name(result.table("by_local_authority"))
    assert table["Lewisham"]["distance_km"] == 1
    assert table["Birmingham"]["distance_km"] == 114
    assert "3 distinct postcodes" in result.privacy.sent_to_third_parties[0]
    source = next(s for s in result.sources if s.id == "postcodes-io")
    assert source.used_for == "Finding where each site is."
    choice = result.choices[0]
    assert choice.id == "postcode_lookup"
    assert choice.option == "postcode_lookup"
    assert "No postcode table is installed" in choice.reason
    assert not any("centre of its neighbourhood" in c for c in result.caveats)
    assert any(w.startswith("1 row had no postcode") for w in result.warnings)
    assert any(w.startswith("1 row held something") for w in result.warnings)
    assert any(
        w.startswith("1 row had a postcode that was not") for w in result.warnings
    )


def test_a_site_in_scotland_counts_as_a_site(kept):
    rows = [{"Site postcode": "EH1 1VC"}]
    result = _run_postcodes(rows)
    assert result.figure("sites_located").value == 1
    table = _by_name(result.table("by_local_authority"))
    assert table["Hartlepool"]["distance_km"] == 189


def test_postcodes_that_are_not_found_are_an_input_error(kept):
    with pytest.raises(AnalysisInputError, match="None of the rows holds a position"):
        _run_postcodes([{"Site postcode": "SE13 7VO"}])


def test_no_postcode_reaches_the_result(kept):
    payload = _run_postcodes().to_dict()
    given = [row["Site postcode"] for row in POSTCODE_ROWS]
    assert find_row_values(payload, given) == []


def test_positions_given_directly_send_nothing(kept):
    with mock.patch("uk_open_data.analyses._steps.lookup_postcodes") as online:
        result = _run()
    online.assert_not_called()
    assert result.privacy.sent_to_third_parties == ()


@pytest.mark.parametrize("how", ["sometimes", None, 1])
def test_bad_postcode_lookup_is_rejected_in_either_mode(kept, how):
    with pytest.raises(
        AnalysisInputError, match="Where postcodes are looked up"
    ) as caught:
        _run(options={"postcode_lookup": how})
    assert caught.value.option == "postcode_lookup"


# --- site postcodes that stay on this machine ------------------------------

# The neighbourhood of each invented postcode, and where its centre is. The
# last postcode is in the table, but its neighbourhood has no centre kept.
NEIGHBOURHOODS = {
    "SE13 7VC": "E01000001",
    "M1 1VC": "E01000002",
    "CF10 1VC": "W01000003",
}
NEIGHBOURHOOD_CENTRES = (
    ("E01000001", 51.46, -0.01),
    ("E01000002", 53.48, -2.24),
)


@pytest.fixture
def table(tmp_path):
    """Install a postcode table that holds the invented postcodes."""
    lines = [
        f"{postcode[:-3].strip().ljust(4)}{postcode[-3:]},{code},E09000023"
        for postcode, code in NEIGHBOURHOODS.items()
    ]
    source = tmp_path / "lookup.csv"
    source.write_text(
        "\n".join(["pcd7,lsoa21cd,ladcd", *lines]) + "\n", encoding="utf-8"
    )
    packed = tmp_path / "postcodes.ktpc.gz"
    build_postcode_table(source, packed, "May 2026")
    install_postcode_table(packed)


@pytest.fixture
def neighbourhoods():
    """Keep invented centres of neighbourhoods."""
    keep_centres(NEIGHBOURHOOD_CENTRES, "invented for a test.", "neighbourhood")


def _run_here(rows=POSTCODE_ROWS, how=None):
    """Run with site postcodes, and fail the test if any is sent out."""
    options = None if how is None else {"postcode_lookup": how}
    with (
        mock.patch("uk_open_data.analyses._steps.lookup_postcodes") as online,
        mock.patch("uk_open_data.analyses._centres.requests.get") as fetch,
        mock.patch("uk_open_data.analyses._centres.load_geodata") as boundaries,
    ):
        try:
            return _run(rows, options=options, columns=POSTCODE_COLUMN)
        finally:
            online.assert_not_called()
            fetch.assert_not_called()
            boundaries.assert_not_called()


@pytest.mark.parametrize("how", [None, "auto", "offline"])
def test_site_postcodes_stay_on_this_machine(kept, table, neighbourhoods, how):
    result = _run_here(how=how)
    assert result.privacy.sent_to_third_parties == ()
    assert result.figure("sites_supplied").value == 6
    assert result.figure("sites_located").value == 3
    by_name = _by_name(result.table("by_local_authority"))
    assert by_name["Lewisham"]["distance_km"] == 1
    assert by_name["Manchester"]["distance_km"] == 1
    choice = result.choices[0]
    assert choice.id == "postcode_lookup"
    assert choice.option == "postcode_lookup"
    assert choice.value.startswith("On this machine, at the centre of each")
    assert "May 2026" in choice.value
    assert "no postcode was sent out" in choice.reason
    assert not any(s.id == "postcodes-io" for s in result.sources)
    lookup = next(s for s in result.sources if s.id == "ons-postcode-lookup")
    assert lookup.used_for == "Finding the neighbourhood each site is in."
    centres = next(
        s for s in result.sources if s.id == "ons-neighbourhood-centres-2021"
    )
    assert centres.edition.endswith("A copy kept on this machine, invented for a test.")
    step = next(s for s in result.working if s.title.startswith("Found where"))
    assert "3 distinct postcodes were looked up on this machine" in step.detail
    assert (step.rows_in, step.rows_out) == (4, 3)
    assert any("centre of its neighbourhood" in c for c in result.caveats)
    assert any(
        w.startswith("1 row had a postcode that was not found")
        and "outside England and Wales" in w
        for w in result.warnings
    )


def test_no_postcode_placed_here_reaches_the_result(kept, table, neighbourhoods):
    payload = _run_here().to_dict()
    given = [row["Site postcode"] for row in POSTCODE_ROWS]
    assert find_row_values(payload, given) == []


def test_a_neighbourhood_without_a_centre_is_counted_as_not_found(
    kept, table, neighbourhoods
):
    rows = [{"Site postcode": "SE13 7VC"}, {"Site postcode": "CF10 1VC"}]
    result = _run_here(rows)
    assert result.figure("sites_supplied").value == 2
    assert result.figure("sites_located").value == 1
    assert any(
        w.startswith("1 row had a postcode that was not found") for w in result.warnings
    )


@pytest.mark.parametrize("how", ["auto", "offline"])
def test_without_kept_centres_the_analysis_stops_and_sends_nothing(kept, table, how):
    with pytest.raises(AnalysisInputError) as raised:
        _run_here(how=how)
    message = str(raised.value)
    assert "download_centres('neighbourhood')" in message
    assert "No postcode was sent anywhere" in message
    assert not any(row["Site postcode"] in message for row in POSTCODE_ROWS[:5])


def test_offline_without_a_table_stops_and_sends_nothing(kept, neighbourhoods):
    with pytest.raises(AnalysisInputError, match="postcode table"):
        _run_here(how="offline")


def test_online_sends_postcodes_even_with_a_table(kept, table, neighbourhoods):
    sent: list = []
    with mock.patch(
        "uk_open_data.analyses._steps.lookup_postcodes", side_effect=_fake_lookup(sent)
    ):
        result = _run(
            POSTCODE_ROWS,
            options={"postcode_lookup": "online"},
            columns=POSTCODE_COLUMN,
        )
    assert sent == [["M1 1VC", "SE13 7VC", "SE13 7VO"]]
    assert "3 distinct postcodes" in result.privacy.sent_to_third_parties[0]
    reason = result.choices[0].reason
    assert reason.startswith("You chose the online service.")
    assert "No postcode table is installed" not in reason


def test_site_positions_need_no_table_when_offline(kept):
    result = _run(options={"postcode_lookup": "offline"})
    assert result.privacy.sent_to_third_parties == ()
    assert [choice.id for choice in result.choices][0] == "need"


def test_a_kept_neighbourhood_file_that_cannot_be_read_is_an_input_error(
    kept, table, neighbourhoods
):
    path = centres_path("neighbourhood")
    path.write_text('{"format": "kindtech-centres-1"}', encoding="utf-8")
    with pytest.raises(
        AnalysisInputError, match=r"download_centres\('neighbourhood'\)"
    ):
        _run_here()


# --- the centres -----------------------------------------------------------


def _boundaries(*args, **kwargs) -> dict:
    """Boundary features as the ONS returns them, with one from Scotland."""
    rows = [*CENTRES, ("S12000036", 55.95, -3.19)]
    features = [
        {"properties": {"LAD23CD": code, "LAT": latitude, "LONG": longitude}}
        for code, latitude, longitude in rows
    ]
    features.append({"properties": {"LAD23CD": "E06000002", "LAT": None}})
    return {"type": "FeatureCollection", "features": features}


def test_centres_are_fetched_once_for_england_and_wales():
    keep_need_figures("residents", NEED, "invented for a test.")
    target = "uk_open_data.analyses._centres.load_geodata"
    with mock.patch(target, side_effect=_boundaries) as fetch:
        first = _run()
        second = _run()
    assert fetch.call_count == 1
    assert fetch.call_args.args == ("LAD",)
    assert fetch.call_args.kwargs["year"] == "2023"
    assert first.figure("areas_compared").value == 8
    assert second.figure("farthest_distance_km").value == 475
    source = next(s for s in first.sources if s.id.startswith("ons-local-authority"))
    assert source.edition == "December 2023"
    assert "Fetched from the ONS" in first.working[1].detail


def test_kept_centres_are_used_and_nothing_is_fetched(kept):
    with mock.patch("uk_open_data.analyses._centres.load_geodata") as fetch:
        result = _run()
    fetch.assert_not_called()
    source = next(s for s in result.sources if s.id.startswith("ons-local-authority"))
    assert source.edition.endswith("A copy kept on this machine, invented for a test.")
    assert "kept on this machine" in result.working[1].detail


def test_download_fetches_and_keeps_the_centres():
    assert centres_path() is None
    with mock.patch(
        "uk_open_data.analyses._centres.load_geodata", side_effect=_boundaries
    ):
        path = download_centres()
    assert centres_path() == path
    kept_file = json.loads(path.read_text(encoding="utf-8"))
    assert len(kept_file["centres"]) == 8
    assert kept_file["note"].startswith("fetched from the ONS Open Geography Portal")


def _pages(asked: list, rows: list[tuple]) -> mock.Mock:
    """The boundary service, giving two neighbourhoods at a time."""

    def get(url, params, timeout):
        asked.append((url, dict(params), timeout))
        start = params["resultOffset"]
        features = [
            {"attributes": {"LSOA21CD": code, "LAT": latitude, "LONG": longitude}}
            for code, latitude, longitude in rows[start : start + 2]
        ]
        response = mock.Mock()
        response.json.return_value = {"features": features}
        return response

    return mock.Mock(side_effect=get)


def test_download_fetches_neighbourhood_centres_page_by_page():
    rows = [
        ("E01000001", 51.46, -0.01),
        ("E01000002", 53.48, -2.24),
        ("W01000003", 51.48, -3.18),
        ("S01000004", 55.95, -3.19),
        ("E01000005", None, None),
    ]
    asked: list = []
    assert centres_path("neighbourhood") is None
    with mock.patch("uk_open_data.analyses._centres.requests.get", _pages(asked, rows)):
        path = download_centres("neighbourhood")
    assert centres_path("neighbourhood") == path
    assert path.name == "neighbourhoods-2021.json"
    assert centres_path() is None
    assert [params["resultOffset"] for _, params, _ in asked] == [0, 2, 4, 5]
    url, params, timeout = asked[0]
    assert url.endswith("/0/query")
    assert params["returnGeometry"] == "false"
    assert params["orderByFields"] == "LSOA21CD"
    assert timeout == 60
    kept_file = json.loads(path.read_text(encoding="utf-8"))
    assert kept_file["level"] == "neighbourhood"
    assert [code for code, _, _ in kept_file["centres"]] == [
        "E01000001",
        "E01000002",
        "W01000003",
    ]


@pytest.mark.parametrize(
    "response",
    [
        mock.Mock(side_effect=requests.ConnectionError("down")),
        mock.Mock(return_value=mock.Mock(json=lambda: {"error": {"code": 400}})),
        mock.Mock(return_value=mock.Mock(json=lambda: {"features": []})),
    ],
)
def test_neighbourhood_centres_that_cannot_be_fetched_keep_nothing(response):
    with (
        mock.patch("uk_open_data.analyses._centres.requests.get", response),
        pytest.raises(ValueError, match="boundary service"),
    ):
        download_centres("neighbourhood")
    assert centres_path("neighbourhood") is None


def test_a_service_that_does_not_page_stops_the_fetch():
    same = {"features": [{"attributes": {"LSOA21CD": "E01000001"}}] * 2000}
    response = mock.Mock(return_value=mock.Mock(json=lambda: same))
    with (
        mock.patch("uk_open_data.analyses._centres.requests.get", response),
        pytest.raises(ValueError, match="kept returning"),
    ):
        download_centres("neighbourhood")
    assert response.call_count == 51


@pytest.mark.parametrize("call", [centres_path, download_centres])
def test_an_unknown_level_is_refused(call):
    with pytest.raises(ValueError, match="No centres for 'street'"):
        call("street")


def test_keeping_centres_for_an_unknown_level_is_refused():
    with pytest.raises(ValueError, match="No centres for 'street'"):
        keep_centres(NEIGHBOURHOOD_CENTRES, "invented for a test.", "street")


def test_centres_that_cannot_be_fetched_are_an_input_error():
    keep_need_figures("residents", NEED, "invented for a test.")
    empty = {"type": "FeatureCollection", "features": []}
    with (
        mock.patch("uk_open_data.analyses._centres.load_geodata", return_value=empty),
        pytest.raises(AnalysisInputError, match="download_centres"),
    ):
        _run()


def test_a_kept_file_that_cannot_be_read_is_an_input_error(kept):
    centres_path().write_text('{"format": "kindtech-centres-1"}', encoding="utf-8")
    with pytest.raises(AnalysisInputError, match="could not be read"):
        _run()


# --- the map ---------------------------------------------------------------


def test_map_is_described_by_local_authority(kept):
    result = _run()
    spec = result.map
    assert (spec.geography_type, spec.geography_year) == ("LAD", 2023)
    assert spec.table == "by_local_authority"
    assert [layer.id for layer in spec.layers] == ["distance", "need"]
    assert spec.layers[0].categories == DISTANCE_BANDS
    assert spec.layers[1].categories == NEED_BANDS
    table = result.table(spec.table)
    assert table.detail is True
    rows = _by_name(table)
    assert rows["Lewisham"]["distance_band"] == "Under 5 km"
    assert rows["Adur"]["distance_band"] == "40 km or more"
    assert rows["Birmingham"]["need_band"] == "Highest fifth"
    # A place for every group: nothing is said of few places.
    assert spec.layers[1].note == "Local authorities in five equal groups by people."


@pytest.mark.parametrize(
    ("site", "band"),
    [
        ((51.45, -0.02), "Under 5 km"),
        ((51.50, -0.02), "5 to under 10 km"),
        ((51.60, -0.02), "10 to under 20 km"),
        ((51.75, -0.02), "20 to under 40 km"),
        ((52.00, -0.02), "40 km or more"),
    ],
)
def test_distance_bands(kept, site, band):
    rows = [{"Lat": site[0], "Lon": site[1]}]
    result = _run(rows, options={"catchment": "Lewisham"})
    assert result.table("by_local_authority").rows[0]["distance_band"] == band


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


def test_map_can_be_drawn(kept):
    result = _run()
    boundaries = {
        "type": "FeatureCollection",
        "features": [_square(n, code) for n, (code, _, _) in enumerate(NEED)],
    }
    for layer in ("distance", "need"):
        svg = render_map(result, layer=layer, boundaries=boundaries)
        root = ET.fromstring(svg)
        titles = [
            title.text for title in root.iter("{http://www.w3.org/2000/svg}title")
        ]
        assert any(text.startswith("Lewisham: ") for text in titles[1:])


def test_the_map_credits_the_boundaries_once(kept):
    # Distances are measured from the middle of each place, so the boundaries
    # are a source of the figures as well as of the outlines.
    result = _run()
    assert any("Boundaries" in source.name for source in result.sources)
    boundaries = {
        "type": "FeatureCollection",
        "features": [_square(n, code) for n, (code, _, _) in enumerate(NEED)],
    }
    texts = ET.fromstring(render_map(result, boundaries=boundaries)).iter(
        "{http://www.w3.org/2000/svg}text"
    )
    credit = " ".join(text.text for text in texts if text.get("class") == "ink2")
    assert credit.count("Boundaries") == 1
    assert "Boundaries: Office for National Statistics" in credit
    # The other sources are still named.
    assert "Sources: " in credit


# --- the whole result ------------------------------------------------------


def test_charts_use_columns_of_the_list(kept):
    result = _run()
    assert [chart.id for chart in result.charts] == [
        "people_in_priority_areas",
        "distance_in_priority_areas",
    ]
    columns = set(result.table("priority_areas").columns)
    for chart in result.charts:
        assert chart.table == "priority_areas"
        assert chart.category_column in columns
        assert {series.column for series in chart.series} <= columns


def test_result_explains_itself(kept):
    result = _run()
    options = check_working(result)
    assert options == {
        "postcode_lookup": "auto",
        "need": "residents",
        "within_km": 10,
        "top": 10,
    }
    # The average is given before rounding. A distance from one place is not:
    # it is rounded to the kilometre on purpose.
    assert result.figure("average_distance_km").exact == pytest.approx(80.8449, 1e-4)
    assert result.figure("farthest_distance_km").exact is None
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
        "Loaded the centre of each local authority",
        "Read the site positions",
        "Measured the distance to the nearest site",
        "Listed the places far from a site",
    ]
    assert [check.id for check in result.checks] == [
        "sites_public",
        "everything_listed",
        "straight_line",
        "need_fits",
        "catchment",
    ]
    assert [choice.id for choice in result.choices] == [
        "need",
        "distance",
        "within_km",
        "catchment",
        "top",
    ]
    option_names = {option.name for option in describe_analysis(ANALYSIS_ID).options}
    for choice in result.choices:
        assert choice.option is None or choice.option in option_names
    assert any("straight line" in caveat for caveat in result.caveats)
    assert result.privacy.cells_suppressed == 0
    assert result.privacy.suppress_below is None
    assert any("hides no count" in note for note in result.privacy.notes)
    assert any("confidential" in note for note in result.privacy.notes)
    summary = result.to_dict(include_detail=False)
    json.dumps(summary)
    detail = next(t for t in summary["tables"] if t["id"] == "by_local_authority")
    assert detail["rows"] == []


def test_every_distance_is_said_to_be_from_a_centre(kept):
    # A person is counted at the centre of their local authority, so a site
    # can be inside a large place and the place still be listed as far from
    # one. Each label that gives a distance or judges reach by it says so.
    result = _run()
    labels = {figure.id: figure.label for figure in result.figures}
    assert labels["share_of_people_within_reach"] == (
        "Share of people in a local authority whose centre is within 10 km of a site"
    )
    assert labels["people_beyond_reach"] == (
        "People in a local authority whose centre is more than 10 km from a site"
    )
    assert labels["areas_beyond_reach"] == (
        "Local authorities whose centre is more than 10 km from a site"
    )
    assert "centre" in labels["farthest_distance_km"]
    for table in result.tables:
        assert table.headings["distance_km"] == "From its centre to your nearest site"
    assert "centre" in result.charts[1].title
    assert result.answer.startswith(
        "Counting each person at the centre of their local authority, "
    )
    listed = next(s for s in result.working if s.title.startswith("Listed"))
    assert "whose centre is more than 10 km from a site" in listed.detail
    assert any(
        "a site can be inside the place and still be far from its centre" in caveat
        for caveat in result.caveats
    )


def test_headings_do_not_call_every_resident_a_need(kept):
    # Distance is measured for every resident unless another measure is set,
    # so the column of people is headed "Residents", not "People in need".
    result = _run()
    for table in result.tables:
        assert table.headings["people_in_need"] == "Residents"
    assert result.table("by_local_authority").headings["need_band"] == (
        "Residents, grouped"
    )
    option = {o.name: o for o in describe_analysis(ANALYSIS_ID).options}["need"]
    choice = next(c for c in result.choices if c.id == "need")
    assert choice.label == option.label == "People you are trying to reach"
    assert result.sources[0].used_for == (
        "People you are trying to reach: Residents of every age."
    )


def test_command_line_runs_the_analysis(kept, tmp_path, capsys):
    path = tmp_path / "sites.csv"
    path.write_text("Lat,Lon\n51.4613,-0.0117\n53.48,-2.24\n", encoding="utf-8")
    code = main(
        [
            "analysis",
            "run",
            ANALYSIS_ID,
            str(path),
            "--column",
            "latitude=Lat",
            "--column",
            "longitude=Lon",
            "--option",
            "within_km=120",
            "--json",
        ]
    )
    assert code == EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["analysis_id"] == ANALYSIS_ID
    figures = {figure["id"]: figure["value"] for figure in payload["figures"]}
    assert figures["areas_beyond_reach"] == 3
