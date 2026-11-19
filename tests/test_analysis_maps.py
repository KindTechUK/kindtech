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

from uk_open_data.analyses import load_map_boundaries, maps, render_map, run_analysis
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


def _paths(svg: str, kind: str = "area") -> list[ET.Element]:
    """Every outline of one kind in the picture: by default the shaded areas."""
    paths = ET.fromstring(svg).findall(f".//{SVG}path")
    return [path for path in paths if kind in (path.get("class") or "").split()]


def _texts(svg: str, kind: str | None = None) -> list[str]:
    """The words written on the picture, or only those of one kind."""
    texts = ET.fromstring(svg).iter(f"{SVG}text")
    return [text.text for text in texts if kind in (None, text.get("class"))]


def _place(code: str, name: str, west: float, south: float, size: float) -> dict:
    """An invented outline of a place that is not in the result."""
    ring = [
        [west, south],
        [west + size, south],
        [west + size, south + size],
        [west, south + size],
        [west, south],
    ]
    return {
        "type": "Feature",
        "properties": {"LAD23CD": code, "LAD23NM": name},
        "geometry": {"type": "Polygon", "coordinates": [ring]},
    }


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
    labels = [text.text for text in root.iter(f"{SVG}text")]
    start = labels.index("fewer than 5")
    assert labels[start : start + 5] == [
        "fewer than 5",
        "5 to 9",
        "10 to 19",
        "20 to 49",
        "50 or more",
    ]
    words = " ".join(labels)
    assert "Boundaries: Office for National Statistics" in words
    assert "Sources: English Indices of Deprivation 2025" in words


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
    assert root.find(f"{SVG}title").text == "Deprivation decile, by neighbourhood"
    assert root.find(f"{SVG}desc").text.startswith("Map of neighbourhoods. ")
    assert "most deprived" in root.find(f"{SVG}desc").text
    # The picture is as tall as what is in it: the last line sits inside it.
    lowest = max(float(text.get("y")) for text in root.iter(f"{SVG}text"))
    assert lowest < float(root.get("height")) < lowest + 40


def test_title_says_what_the_colour_shows(result):
    # A picture shows one layer, so its title names that layer and not both.
    deprivation = render_map(result, boundaries=_boundaries())
    people = render_map(result, layer="people", boundaries=_boundaries())
    assert _texts(deprivation, "ink")[0] == "Deprivation decile, by neighbourhood"
    assert _texts(people, "ink")[0] == "People reached, by neighbourhood"
    assert "Deprivation and people reached" not in deprivation


@pytest.mark.parametrize("width", [320, 480, 720, 1000])
def test_no_line_of_text_runs_off_the_picture(result, width):
    svg = render_map(result, layer="people", boundaries=_boundaries(), width=width)
    for text in ET.fromstring(svg).iter(f"{SVG}text"):
        if text.get("text-anchor") == "middle":
            continue
        # A letter is about half the size of the text wide, and a bold one
        # a little more. The right margin is as wide as the left one.
        letter = 0.6 if text.get("font-weight") else 0.52
        wide = len(text.text) * float(text.get("font-size")) * letter
        assert float(text.get("x")) + wide <= width - 16 + 1


def test_long_words_are_wrapped_and_none_is_lost():
    sentence = "Local authorities in five equal groups by people in need."
    lines = maps._wrap(sentence, 24)
    assert max(len(line) for line in lines) <= 24
    assert " ".join(lines) == sentence
    assert maps._wrap("", 24) == []
    assert maps._wrap("Supercalifragilistic", 5) == ["Supercalifragilistic"]


def test_map_sits_in_a_frame_with_a_scale_line(result):
    svg = render_map(result, boundaries=_boundaries())
    root = ET.fromstring(svg)
    frame = next(r for r in root.iter(f"{SVG}rect") if r.get("class") == "frame")
    assert float(frame.get("width")) == 720 - 32
    # Five squares by four is flat, and the frame is never very flat.
    assert float(frame.get("height")) >= 300
    assert len(_paths(svg, "rule")) == 1
    assert "1 km" in _texts(svg, "ink")


@pytest.mark.parametrize(
    ("pixels_per_km", "words"),
    [(400, "200 m"), (60, "1 km"), (21, "5 km"), (1.5, "50 km"), (0.01, "500 km")],
)
def test_scale_line_is_the_longest_round_distance_that_fits(pixels_per_km, words):
    length, said = maps._scale_length(pixels_per_km)
    assert said == words
    assert length <= 110


def test_places_around_are_drawn_pale_and_named(result):
    boundaries = _boundaries()
    # Lewisham holds the shaded squares; the other two lie beside them.
    boundaries["surroundings"] = [
        _place("E09000023", "Lewisham", -0.06, 51.39, 0.07),
        _place("E09000011", "Greenwich", 0.0, 51.39, 0.07),
        _place("E06000001", "Hartlepool", 5.0, 54.0, 0.07),
    ]
    boundaries["focus"] = ["E09000023"]
    svg = render_map(result, boundaries=boundaries)
    assert len(_paths(svg)) == AREAS
    # A place far outside the frame is not drawn at all.
    assert len(_paths(svg, "land")) == 2
    # The place that holds the shaded areas gets a darker line and one name.
    assert len(_paths(svg, "outline")) == 1
    assert _texts(svg, "held") == ["Lewisham"]
    assert _texts(svg, "near") == ["Greenwich"]
    assert "Hartlepool" not in svg


def test_outlines_not_in_the_result_are_the_places_around(result):
    # A file that holds more areas than the result shades: the rest are drawn
    # pale, never shaded, and the shaded areas alone set the frame.
    boundaries = _boundaries()
    boundaries["features"].append(_place("E09000011", "Greenwich", 0.0, 51.39, 0.07))
    svg = render_map(result, boundaries=boundaries)
    assert len(_paths(svg)) == AREAS
    assert len(_paths(svg, "land")) == 1


def test_one_authority_alone_is_not_named(result):
    # With nothing drawn around it, a name on the only place says nothing.
    svg = render_map(result, boundaries=_boundaries())
    assert _texts(svg, "held") == []
    assert _texts(svg, "near") == []


def test_a_name_gives_way_when_there_is_no_room(result):
    boundaries = _boundaries()
    boundaries["surroundings"] = [
        _place("E09000011", "Greenwich", 0.0, 51.39, 0.07),
        # Too small to hold its name.
        _place("E09000012", "Hackney", -0.06, 51.42, 0.0008),
        # Has room, but its name would sit on Greenwich's.
        _place("E09000013", "Greenwich Park", 0.0, 51.39, 0.07),
    ]
    svg = render_map(result, boundaries=boundaries)
    assert len(_paths(svg, "land")) == 3
    assert _texts(svg, "near") == ["Greenwich"]


def test_second_layer_has_its_own_hue(result):
    deprivation = render_map(result, boundaries=_boundaries())
    people = render_map(result, layer="people", boundaries=_boundaries())
    assert "#0d366b" in deprivation and "#7f2d0c" not in deprivation
    assert "#7f2d0c" in people and "#0d366b" not in people


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
