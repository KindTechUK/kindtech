"""
Unit tests for drawing an analysis map.

Boundaries are invented squares and the deprivation index is an invented table,
so the tests are isolated and repeatable.
"""

import logging
import threading
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


LEWISHAM, GREENWICH, HARTLEPOOL = "E09000023", "E09000011", "E06000001"


class _Service:
    """Stands in for the boundary service and records what it was asked.

    Lewisham holds the shaded squares, Greenwich lies beside them and
    Hartlepool is far away. Each outline says how it was asked for, so a test
    can tell a fine one from one simplified to 200 metres.
    """

    def __init__(self, fail_first=0, authorities=True, fine_authorities=None):
        self.asked: list[dict] = []
        self._failures = fail_first
        self._authorities = authorities
        self._fine = fine_authorities

    def load(self, geography_type, **asked):
        self.asked.append({"type": geography_type, **asked})
        fine = asked.get("simplify_m")
        if geography_type == "LSOA":
            if self._failures:
                self._failures -= 1
                return {"type": "FeatureCollection", "features": []}
            numbers = [int(code[-5:]) for code in asked["LSOA21CD"]]
            return _boundaries(numbers)
        places = [
            _place(LEWISHAM, "Lewisham", -0.06, 51.39, 0.07),
            _place(GREENWICH, "Greenwich", 0.0, 51.39, 0.07),
            _place(HARTLEPOOL, "Hartlepool", 5.0, 54.0, 0.07),
        ]
        wanted = asked.get("LAD23CD")
        if not self._authorities:
            places = []
        elif wanted is not None:
            comes = wanted if self._fine is None else self._fine
            places = [p for p in places if p["properties"]["LAD23CD"] in comes]
        for place in places:
            place["properties"]["detail"] = fine
        return {"type": "FeatureCollection", "features": places}


def _fetch(result, service, **changes):
    """Fetch a result's outlines from a stand-in service."""
    patches = [
        mock.patch(f"uk_open_data.analyses.maps.{name}", value)
        for name, value in changes.items()
    ]
    with mock.patch("uk_open_data.analyses.maps.load_geodata", service.load):
        for patch in patches:
            patch.start()
        try:
            return load_map_boundaries(result)
        finally:
            for patch in patches:
                patch.stop()


def _details(features) -> dict[str, object]:
    """How each local authority's outline was asked for, by its code."""
    return {f["properties"]["LAD23CD"]: f["properties"]["detail"] for f in features}


def test_a_few_neighbourhoods_are_fetched_in_fine_detail(result):
    service = _Service()
    boundaries = _fetch(result, service, _FINE_BATCH={"LSOA": 8, "LAD": 10})
    assert len(boundaries["features"]) == AREAS
    areas = [asked for asked in service.asked if asked["type"] == "LSOA"]
    assert len(areas) == 3  # twenty codes, eight at a time
    assert {asked["boundary_type"] for asked in areas} == {"BFE"}
    assert {asked["simplify_m"] for asked in areas} == {10}
    assert {(asked["year"], asked["coverage"]) for asked in areas} == {("2021", "EW")}


def test_many_neighbourhoods_take_the_200_metre_outlines(result):
    service = _Service()
    boundaries = _fetch(result, service, _FINE_UP_TO={"LSOA": 5}, BOUNDARY_BATCH_SIZE=8)
    assert len(boundaries["features"]) == AREAS
    areas = [asked for asked in service.asked if asked["type"] == "LSOA"]
    assert len(areas) == 3
    assert {asked["boundary_type"] for asked in areas} == {"BSC"}
    assert {asked["simplify_m"] for asked in areas} == {None}
    # A map drawn small takes its surroundings at 200 metres too, from the
    # one request for every local authority.
    authorities = [asked for asked in service.asked if asked["type"] == "LAD"]
    assert len(authorities) == 1
    assert _details(boundaries["surroundings"]) == {LEWISHAM: None, GREENWICH: None}


def test_a_batch_that_does_not_come_is_asked_for_once_more(result):
    service = _Service(fail_first=1)
    boundaries = _fetch(result, service, _FINE_BATCH={"LSOA": 8, "LAD": 10})
    assert len(boundaries["features"]) == AREAS
    areas = [asked for asked in service.asked if asked["type"] == "LSOA"]
    assert len(areas) == 4
    assert areas[3]["LSOA21CD"] == areas[0]["LSOA21CD"]


def test_rough_outlines_stand_in_when_the_fine_ones_do_not_come(result):
    # Both tries at the fine outlines fail. A rough map is better than none.
    service = _Service(fail_first=2)
    boundaries = _fetch(result, service)
    assert len(boundaries["features"]) == AREAS
    areas = [asked for asked in service.asked if asked["type"] == "LSOA"]
    assert [asked["boundary_type"] for asked in areas] == ["BFE", "BFE", "BSC"]
    # The places around then come at 200 metres too, so that they still meet.
    assert _details(boundaries["surroundings"]) == {LEWISHAM: None, GREENWICH: None}


def test_places_around_come_from_the_same_layer_as_the_areas(result):
    # A neighbour simplified to 200 metres does not sit on neighbourhoods
    # drawn to 10, so the places on and near a small map are fetched again
    # from the full outlines at the same detail.
    service = _Service()
    boundaries = _fetch(result, service)
    everywhere, near = [asked for asked in service.asked if asked["type"] == "LAD"]
    assert everywhere["boundary_type"] == "BSC"
    assert "LAD23CD" not in everywhere
    assert near["boundary_type"] == "BFE"
    assert near["simplify_m"] == 10
    # Hartlepool is far from the map, so it is neither asked for nor kept.
    assert near["LAD23CD"] == [GREENWICH, LEWISHAM]
    assert _details(boundaries["surroundings"]) == {LEWISHAM: 10, GREENWICH: 10}
    # The authority the result counts as the area served holds the map.
    assert boundaries["focus"] == [LEWISHAM]


def test_a_neighbour_keeps_its_rough_outline_when_the_fine_one_does_not_come(result):
    service = _Service(fine_authorities=[LEWISHAM])
    boundaries = _fetch(result, service)
    assert _details(boundaries["surroundings"]) == {LEWISHAM: 10, GREENWICH: None}


def test_map_is_whole_when_the_places_around_do_not_come(result):
    service = _Service(authorities=False)
    boundaries = _fetch(result, service)
    assert len(boundaries["features"]) == AREAS
    assert boundaries["surroundings"] == []
    svg = render_map(result, boundaries=boundaries)
    assert len(_paths(svg)) == AREAS
    assert _paths(svg, "land") == []


def test_map_is_drawn_with_what_it_fetches(result):
    service = _Service()
    with mock.patch("uk_open_data.analyses.maps.load_geodata", service.load):
        svg = render_map(result)
    assert len(_paths(svg)) == AREAS
    assert len(_paths(svg, "land")) == 2
    assert len(_paths(svg, "outline")) == 1
    assert _texts(svg, "held") == ["Lewisham"]
    assert _texts(svg, "near") == ["Greenwich"]


def test_every_authority_is_fetched_once_for_the_life_of_the_process(result):
    # It is about a megabyte and the same for every map.
    service = _Service()
    _fetch(result, service)
    _fetch(result, service)
    everywhere = [
        asked
        for asked in service.asked
        if asked["type"] == "LAD" and "LAD23CD" not in asked
    ]
    assert len(everywhere) == 1
    maps.clear_outline_cache()
    _fetch(result, service)
    assert len([a for a in service.asked if a["type"] == "LAD"]) > 3


def test_a_caller_that_cannot_wait_takes_the_quick_outlines(result):
    # The fine outlines can take a minute the first time. With fine=False
    # nothing fine is asked for, and the places around still come.
    service = _Service()
    with mock.patch("uk_open_data.analyses.maps.load_geodata", service.load):
        boundaries = load_map_boundaries(result, fine=False)
    assert len(boundaries["features"]) == AREAS
    assert {asked["boundary_type"] for asked in service.asked} == {"BSC"}
    assert {asked.get("simplify_m") for asked in service.asked} == {None}
    assert _details(boundaries["surroundings"]) == {LEWISHAM: None, GREENWICH: None}
    assert boundaries["focus"] == [LEWISHAM]
    # Every authority at 200 metres, and the neighbourhoods: nothing by name.
    assert not [a for a in service.asked if "LAD23CD" in a]


def test_two_maps_fetched_at_once_fetch_every_authority_once(result):
    # A door can fetch a second map while the first is still on its way.
    service = _Service()
    started = threading.Event()
    go_on = threading.Event()

    def slow(geography_type, **asked):
        if geography_type == "LAD" and "LAD23CD" not in asked:
            started.set()
            go_on.wait(timeout=5)
        return service.load(geography_type, **asked)

    fetched: list[dict] = []

    def fetch():
        fetched.append(load_map_boundaries(result, fine=False))

    with mock.patch("uk_open_data.analyses.maps.load_geodata", slow):
        threads = [threading.Thread(target=fetch) for _ in range(2)]
        threads[0].start()
        assert started.wait(timeout=5)
        threads[1].start()
        go_on.set()
        for thread in threads:
            thread.join(timeout=5)
    everywhere = [
        asked
        for asked in service.asked
        if asked["type"] == "LAD" and "LAD23CD" not in asked
    ]
    assert len(everywhere) == 1
    assert [len(b["surroundings"]) for b in fetched] == [2, 2]


def test_an_empty_answer_for_every_authority_is_not_kept(result):
    down = _Service(authorities=False)
    assert _fetch(result, down)["surroundings"] == []
    # The service is back: the next map asks again and gets its places.
    assert len(_fetch(result, _Service())["surroundings"]) == 2


def test_credit_carries_the_year_of_the_outlines(result):
    words = " ".join(_texts(render_map(result, boundaries=_boundaries()), "ink2"))
    assert words.endswith("Crown copyright and database right 2021.")


def test_points_closer_than_a_dot_are_left_out():
    close = [(0.0, 0.0), (0.2, 0.1), (0.3, 0.2), (5.0, 0.0), (5.0, 5.0), (0.0, 0.0)]
    assert maps._thinned(close) == [(0.0, 0.0), (5.0, 0.0), (5.0, 5.0), (0.0, 0.0)]
    # A ring is never thinned to less than a shape, and still closes.
    speck = [(0.0, 0.0), (0.1, 0.0), (0.1, 0.1), (0.0, 0.1), (0.0, 0.0)]
    assert maps._thinned(speck) == speck
    assert maps._thinned([]) == []


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
