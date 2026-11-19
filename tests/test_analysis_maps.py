"""
Unit tests for drawing an analysis map.

Boundaries are invented squares and the deprivation index is an invented table,
so the tests are isolated and repeatable.
"""

import logging
import unittest.mock as mock
import xml.etree.ElementTree as ET

import pandas as pd
import pytest

from uk_open_data.analyses import load_map_boundaries, render_map, run_analysis
from uk_open_data.cli import EXIT_INPUT_ERROR, EXIT_OK, main

SVG = "{http://www.w3.org/2000/svg}"
ANALYSIS_ID = "reach-deprivation"
AREAS = 20


def _code(number: int) -> str:
    """An invented neighbourhood code."""
    return f"E010{number:05d}"


def _index() -> pd.DataFrame:
    """An invented index: one authority, two areas of 1,000 per decile."""
    rows = [
        {
            "geography_code": _code(number),
            "geography_name": f"Lewisham {number:03d}A & B",
            "lad_code": "E09000023",
            "lad_name": "Lewisham",
            "imd_decile": number % 10 + 1,
            "population": 1000,
        }
        for number in range(AREAS)
    ]
    return pd.DataFrame(rows)


def _square(number: int) -> list[list[float]]:
    """A small square, one per area, laid out in a row of five."""
    west = -0.05 + 0.01 * (number % 5)
    south = 51.40 + 0.01 * (number // 5)
    return [
        [west, south],
        [west + 0.01, south],
        [west + 0.01, south + 0.01],
        [west, south + 0.01],
        [west, south],
    ]


def _feature(number: int) -> dict:
    """An invented boundary for one area."""
    return {
        "type": "Feature",
        "properties": {"LSOA21CD": _code(number)},
        "geometry": {"type": "Polygon", "coordinates": [_square(number)]},
    }


def _boundaries(numbers=None) -> dict:
    """Invented boundaries for some or all of the areas."""
    chosen = range(AREAS) if numbers is None else numbers
    features = [_feature(number) for number in chosen]
    return {"type": "FeatureCollection", "features": features}


COUNTS = [
    {"lsoa_code": _code(0), "count": 60},
    {"lsoa_code": _code(1), "count": 22},
    {"lsoa_code": _code(2), "count": 7},
    {"lsoa_code": _code(13), "count": 3},
]


@pytest.fixture
def result():
    """An analysis result on invented counts."""
    with mock.patch(
        "uk_open_data.analyses.reach_deprivation.load_imd", return_value=_index()
    ):
        return run_analysis(ANALYSIS_ID, COUNTS)


def _paths(svg: str) -> list[ET.Element]:
    """Every area drawn in the picture."""
    return ET.fromstring(svg).findall(f".//{SVG}path")


def test_draws_every_area_with_a_colour_class(result):
    svg = render_map(result, boundaries=_boundaries())
    paths = _paths(svg)
    assert len(paths) == AREAS
    # Decile 1 is the most deprived, so it takes the strongest of ten colours.
    by_title = {path.find(f"{SVG}title").text: path.get("class") for path in paths}
    assert by_title["Lewisham 000A & B: Deprivation decile 1"] == "area c9"
    assert by_title["Lewisham 009A & B: Deprivation decile 10"] == "area c0"


def test_people_layer_uses_bands_never_counts(result):
    svg = render_map(result, layer="people", boundaries=_boundaries())
    titles = {path.find(f"{SVG}title").text for path in _paths(svg)}
    assert "Lewisham 000A & B: People reached 50 or more" in titles
    assert "Lewisham 013A & B: People reached fewer than 5" in titles  # three people
    assert "Lewisham 019A & B: People reached fewer than 5" in titles  # nobody
    assert ">60<" not in svg and ">3<" not in svg


def test_legend_lists_every_category_lowest_first(result):
    svg = render_map(result, layer="people", boundaries=_boundaries())
    root = ET.fromstring(svg)
    labels = [text.text for text in root.findall(f"{SVG}text")]
    start = labels.index("fewer than 5")
    assert labels[start : start + 5] == [
        "fewer than 5",
        "5 to 9",
        "10 to 19",
        "20 to 49",
        "50 or more",
    ]
    assert any(label.startswith("Boundaries: Office for National") for label in labels)
    assert any("English Indices of Deprivation 2025" in label for label in labels)


def test_styles_are_tied_to_the_layer_so_maps_can_share_a_page(result):
    deprivation = render_map(result, boundaries=_boundaries())
    people = render_map(result, layer="people", boundaries=_boundaries())
    assert 'class="kindtech-map-deprivation"' in deprivation
    assert ".kindtech-map-deprivation .c9{" in deprivation
    assert ".kindtech-map-people .c4{" in people
    assert ".kindtech-map-people .c5{" not in people
    assert "prefers-color-scheme: dark" in people


def test_picture_is_well_formed_and_described(result):
    root = ET.fromstring(render_map(result, boundaries=_boundaries(), width=400))
    assert root.get("width") == "400"
    assert root.get("role") == "img"
    assert root.find(f"{SVG}title").text.startswith("Deprivation and people")
    assert "most deprived" in root.find(f"{SVG}desc").text


def test_multipolygons_are_drawn_as_one_area(result):
    boundaries = _boundaries()
    boundaries["features"][0]["geometry"] = {
        "type": "MultiPolygon",
        "coordinates": [[_square(0)], [_square(0)]],
    }
    paths = _paths(render_map(result, boundaries=boundaries))
    assert len(paths) == AREAS
    assert max(path.get("d").count("Z") for path in paths) == 2


def test_areas_without_a_boundary_are_left_out_with_a_warning(result, caplog):
    with caplog.at_level(logging.WARNING, logger="uk_open_data.analyses.maps"):
        svg = render_map(result, boundaries=_boundaries(range(15)))
    assert len(_paths(svg)) == 15
    assert "5 of 20 areas have no boundary" in caplog.text


def test_no_matching_boundary_is_an_error(result):
    empty = {"type": "FeatureCollection", "features": []}
    with pytest.raises(ValueError, match="None of the boundaries"):
        render_map(result, boundaries=empty)


def test_unknown_layer_names_the_known_ones(result):
    with pytest.raises(ValueError, match="deprivation, people"):
        render_map(result, layer="income", boundaries=_boundaries())


def test_result_without_a_map_is_an_error():
    with mock.patch(
        "uk_open_data.analyses.reach_deprivation.load_imd", return_value=_index()
    ):
        result = run_analysis(ANALYSIS_ID, COUNTS, options={"catchment": "England"})
    with pytest.raises(ValueError, match="no map"):
        render_map(result, boundaries=_boundaries())


def test_boundaries_are_fetched_in_batches_of_area_codes(result):
    def fake_load(geography_type, year, coverage, boundary_type, **filters):
        numbers = [int(code[-5:]) for code in filters["LSOA21CD"]]
        return _boundaries(numbers)

    with (
        mock.patch("uk_open_data.analyses.maps.BOUNDARY_BATCH_SIZE", 8),
        mock.patch(
            "uk_open_data.analyses.maps.load_geodata", side_effect=fake_load
        ) as load,
    ):
        boundaries = load_map_boundaries(result)
        svg = render_map(result)
    assert len(boundaries["features"]) == AREAS
    assert load.call_count == 6  # three batches for each of the two calls
    assert load.call_args_list[0].args == ("LSOA",)
    assert load.call_args_list[0].kwargs["year"] == "2021"
    assert load.call_args_list[0].kwargs["boundary_type"] == "BSC"
    assert len(_paths(svg)) == AREAS


def test_command_line_saves_the_map(tmp_path, capsys):
    counts = tmp_path / "counts.csv"
    counts.write_text(
        "lsoa_code,count\n" + "".join(f"{_code(n)},{9 + n}\n" for n in range(6)),
        encoding="utf-8",
    )
    picture = tmp_path / "map.svg"
    with (
        mock.patch(
            "uk_open_data.analyses.reach_deprivation.load_imd", return_value=_index()
        ),
        mock.patch(
            "uk_open_data.analyses.maps.load_geodata", return_value=_boundaries()
        ),
    ):
        args = ["analysis", "run", ANALYSIS_ID, str(counts), "--map", str(picture)]
        assert main([*args, "--map-layer", "people"]) == EXIT_OK
        assert "kindtech-map-people" in picture.read_text(encoding="utf-8")
        assert main([*args, "--map-layer", "income"]) == EXIT_INPUT_ERROR
    assert "no layer called 'income'" in capsys.readouterr().err
