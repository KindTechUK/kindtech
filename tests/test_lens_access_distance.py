"""
Unit tests for the access and distance lens.

The need figures, the centres of local authorities and the postcode lookup are
replaced with small invented tables, so the tests are isolated and repeatable.
"""

import json
import unittest.mock as mock
import xml.etree.ElementTree as ET

import pandas as pd
import pytest

from kindtech.cli import EXIT_OK, main
from kindtech.connector.privacy import find_row_values
from kindtech.lenses import LensInputError, describe_lens, render_map, run_lens
from kindtech.lenses._centres import distance_km
from kindtech.lenses.access_distance import (
    DISTANCE_BANDS,
    centres_path,
    download_centres,
    keep_centres,
)
from kindtech.lenses.need_reach import NEED_BANDS, keep_need_figures

LENS_ID = "access-distance"
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
    return run_lens(LENS_ID, rows, columns=columns, options=options)


def _names(table) -> list[str]:
    return [row["geography_name"] for row in table.rows]


def _by_name(table) -> dict[str, dict]:
    return {row["geography_name"]: row for row in table.rows}


# --- the lens is listed ----------------------------------------------------


def test_lens_is_described():
    info = describe_lens(LENS_ID)
    assert info.question.startswith("How far are people from our nearest site")
    modes = {mode.name: mode for mode in info.input_modes}
    assert list(modes) == ["site_coordinates", "site_postcodes"]
    assert modes["site_coordinates"].roles == ("latitude", "longitude")
    assert modes["site_postcodes"].roles == ("postcode",)
    # A list of sites is not a table of totals.
    assert not any(mode.aggregated for mode in info.input_modes)
    # The lens hides nothing, so it has no threshold to set.
    assert [option.name for option in info.options] == [
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
    assert result.figure("people_in_need").label.endswith("Residents of every age")


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
    with pytest.raises(LensInputError, match="top"):
        _run(options={"top": top})


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


def test_a_distance_on_the_line_is_within_reach(kept):
    table = _by_name(_run(options={"within_km": 4}).table("by_local_authority"))
    assert table["Greenwich"]["within_reach"] is True
    table = _by_name(_run(options={"within_km": 3.5}).table("by_local_authority"))
    assert table["Greenwich"]["within_reach"] is False


@pytest.mark.parametrize("within", [0, -1, 501, "near", True, None])
def test_bad_within_km_is_rejected(kept, within):
    with pytest.raises(LensInputError, match="within_km"):
        _run(options={"within_km": within})


def test_nowhere_beyond_reach_is_said_not_hidden(kept):
    result = _run(options={"within_km": 500})
    assert result.table("priority_areas").rows == []
    assert result.figure("share_of_people_within_reach").value == 100.0
    assert any(w.startswith("Every local authority compared") for w in result.warnings)


# --- the need and the catchment --------------------------------------------


def test_need_can_be_another_built_in_measure(kept):
    doubled = [(code, name, people * 2) for code, name, people in NEED]
    keep_need_figures("unemployed_women", doubled, "invented for a test.")
    result = _run(options={"need": "unemployed_women"})
    assert result.figure("people_in_need").value == 182040
    assert "women" in result.figure("people_in_need").label


@pytest.mark.parametrize("need", ["everyone", 7, None, {"dataset": "NM_1_1"}])
def test_bad_need_is_rejected(kept, need):
    with pytest.raises(LensInputError, match="need"):
        _run(options={"need": need})


def test_catchment_can_name_local_authorities(kept):
    result = _run(options={"catchment": ["Lewisham", "Greenwich", "Adur"]})
    assert result.figure("areas_compared").value == 3
    assert result.figure("people_in_need").value == 18000
    assert _names(result.table("priority_areas")) == ["Adur"]
    choice = next(c for c in result.choices if c.id == "catchment")
    assert choice.reason == "You set the catchment."


def test_a_site_outside_the_catchment_still_counts_as_the_nearest(kept):
    result = _run(options={"catchment": "Wales"})
    assert result.figure("areas_compared").value == 1
    table = _by_name(result.table("by_local_authority"))
    assert table["Cardiff"]["distance_km"] == 221


@pytest.mark.parametrize("catchment", [["Lewisham", "Narnia"], 7, [], [""]])
def test_bad_catchment_is_rejected(kept, catchment):
    with pytest.raises(LensInputError, match="catchment"):
        _run(options={"catchment": catchment})


def test_a_place_without_a_centre_is_left_out_and_counted(kept):
    keep_centres(CENTRES[:6], "invented for a test.")
    result = _run()
    assert result.figure("areas_compared").value == 6
    assert "Birmingham" not in _names(result.table("by_local_authority"))
    assert any(w.startswith("2 local authorities in the area") for w in result.warnings)


def test_a_catchment_without_any_centre_is_an_input_error(kept):
    keep_centres(CENTRES[:5], "invented for a test.")
    with pytest.raises(LensInputError, match="catchment"):
        _run(options={"catchment": "Wales"})


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
    with pytest.raises(LensInputError, match="swapped"):
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
        "kindtech.lenses._steps.lookup_postcodes",
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
    assert choice.option is None
    assert any(w.startswith("1 rows had no postcode") for w in result.warnings)
    assert any(w.startswith("1 rows held something") for w in result.warnings)
    assert any(
        w.startswith("1 rows had a postcode that was not") for w in result.warnings
    )


def test_a_site_in_scotland_counts_as_a_site(kept):
    rows = [{"Site postcode": "EH1 1VC"}]
    result = _run_postcodes(rows)
    assert result.figure("sites_located").value == 1
    table = _by_name(result.table("by_local_authority"))
    assert table["Hartlepool"]["distance_km"] == 189


def test_postcodes_that_are_not_found_are_an_input_error(kept):
    with pytest.raises(LensInputError, match="None of the rows holds a position"):
        _run_postcodes([{"Site postcode": "SE13 7VO"}])


def test_no_postcode_reaches_the_result(kept):
    payload = _run_postcodes().to_dict()
    given = [row["Site postcode"] for row in POSTCODE_ROWS]
    assert find_row_values(payload, given) == []


def test_positions_given_directly_send_nothing(kept):
    with mock.patch("kindtech.lenses._steps.lookup_postcodes") as online:
        result = _run()
    online.assert_not_called()
    assert result.privacy.sent_to_third_parties == ()


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
    target = "kindtech.lenses._centres.load_geodata"
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
    with mock.patch("kindtech.lenses._centres.load_geodata") as fetch:
        result = _run()
    fetch.assert_not_called()
    source = next(s for s in result.sources if s.id.startswith("ons-local-authority"))
    assert source.edition.endswith("A copy kept on this machine, invented for a test.")
    assert "kept on this machine" in result.working[1].detail


def test_download_fetches_and_keeps_the_centres():
    assert centres_path() is None
    with mock.patch("kindtech.lenses._centres.load_geodata", side_effect=_boundaries):
        path = download_centres()
    assert centres_path() == path
    kept_file = json.loads(path.read_text(encoding="utf-8"))
    assert len(kept_file["centres"]) == 8
    assert kept_file["note"].startswith("fetched from the ONS Open Geography Portal")


def test_centres_that_cannot_be_fetched_are_an_input_error():
    keep_need_figures("residents", NEED, "invented for a test.")
    empty = {"type": "FeatureCollection", "features": []}
    with (
        mock.patch("kindtech.lenses._centres.load_geodata", return_value=empty),
        pytest.raises(LensInputError, match="download_centres"),
    ):
        _run()


def test_a_kept_file_that_cannot_be_read_is_an_input_error(kept):
    centres_path().write_text('{"format": "kindtech-centres-1"}', encoding="utf-8")
    with pytest.raises(LensInputError, match="could not be read"):
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
    assert result.lens_id == LENS_ID
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
    option_names = {option.name for option in describe_lens(LENS_ID).options}
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


def test_command_line_runs_the_lens(kept, tmp_path, capsys):
    path = tmp_path / "sites.csv"
    path.write_text("Lat,Lon\n51.4613,-0.0117\n53.48,-2.24\n", encoding="utf-8")
    code = main(
        [
            "lens",
            "run",
            LENS_ID,
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
    assert payload["lens_id"] == LENS_ID
    figures = {figure["id"]: figure["value"] for figure in payload["figures"]}
    assert figures["areas_beyond_reach"] == 3
