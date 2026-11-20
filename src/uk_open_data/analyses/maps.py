"""Drawing the map an analysis describes, as a still picture.

An :class:`~uk_open_data.analyses.AnalysisResult` carries a description of a map: which
areas, and what to colour them by. :func:`render_map` turns that into an SVG
picture, using boundaries from the ONS Open Geography Portal.

The picture reads as a map: the shaded areas sit in a frame with a scale line,
the places around them are drawn in pale grey when their outlines are given,
places are named where a name fits, and the title says what the colour shows.

The picture is drawn from the result's table of totals, so it shows nothing
the result does not already hold.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Iterator
from dataclasses import dataclass
from html import escape
from typing import Any

from uk_open_data._mapping import geo_code_field
from uk_open_data.analyses._model import AnalysisResult, MapLayer, MapSpec
from uk_open_data.geo import load_geodata

logger = logging.getLogger(__name__)

# The boundary service is asked for this many areas at a time, to keep each
# request address a sensible length.
BOUNDARY_BATCH_SIZE = 50
BOUNDARY_TYPE = "BSC"  # super generalised: small files, fine for a still map
_COVERAGE = {"LSOA": "EW", "MSOA": "EW"}
BOUNDARY_CREDIT = (
    "Boundaries: Office for National Statistics, Open Government Licence v3.0. "
    "Contains OS data © Crown copyright and database right."
)
# What one area of a map is called, and what many are called.
AREA_WORDS = {
    "LSOA": ("neighbourhood", "neighbourhoods"),
    "LAD": ("local authority", "local authorities"),
}

# One hue for each layer, light to dark. Light means little; dark means a
# lot. The first layer of a map is blue and the second orange, so two
# pictures of one result never look like the same measure.
_RAMPS = (
    (
        "#cde2fb",
        "#b7d3f6",
        "#9ec5f4",
        "#6da7ec",
        "#3987e5",
        "#256abf",
        "#1c5cab",
        "#184f95",
        "#104281",
        "#0d366b",
    ),
    (
        "#f3ece6",
        "#f8cdb9",
        "#f5b596",
        "#f19c75",
        "#ec8253",
        "#e2622d",
        "#c9521f",
        "#b04418",
        "#9c3a12",
        "#7f2d0c",
    ),
)
# land and border are the places around the map; outline is the line round a
# place whose neighbourhoods are shaded.
_LIGHT = {
    "surface": "#ffffff",
    "ink": "#0b0b0b",
    "ink2": "#52514e",
    "none": "#e1e0d9",
    "land": "#eceef1",
    "border": "#b9bdc4",
    "frame": "#d6d4cc",
    "outline": "#3d3c39",
}
_DARK = {
    "surface": "#1a1a19",
    "ink": "#f0efec",
    "ink2": "#c3c2b7",
    "none": "#2c2c2a",
    "land": "#252629",
    "border": "#4a4c51",
    "frame": "#3b3a37",
    "outline": "#e3e2dc",
}

_MARGIN = 16
_FONT = "Arial, Helvetica, sans-serif"
# The frame leaves this share of the shaded areas' size free on each side,
# and is never flatter or taller than these heights.
_ROOM = 0.08
_MIN_MAP_HEIGHT = 300
_MAX_MAP_HEIGHT = 560
_KM_PER_DEGREE = 111.2
_SCALE_LENGTHS = (0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500)
_MAX_SCALE_WIDTH = 110
# Larger areas are named one by one when there are no more than this many.
_MAX_NAMES = 12
# A name is tried on lines this far apart, in letters about this wide.
_NAME_STEP = 10
_NAME_LETTER = 6.2
# About how wide a letter is, as a share of the size of the text. Lines are
# broken by counting letters, so that no text runs off the picture.
_LETTER = 0.52
_BOLD_LETTER = 0.6
_TITLE_SIZE = 16
_TITLE_LINE = 20
_NOTE_SIZE = 12
_NOTE_LINE = 15
_CREDIT_SIZE = 11
_CREDIT_LINE = 14
_KEY_BOX = 14
_KEY_WIDEST = 128
_KEY_SHORT = 44
_KEY_ROW = 22


def load_map_boundaries(result: AnalysisResult) -> dict[str, Any]:
    """Fetch the boundaries of every area on a result's map.

    Only area codes are sent to the boundary service. They are public codes for
    the whole catchment, so they say nothing about where people in the data
    live.

    Args:
        result: An analysis result that has a map.

    Returns:
        A GeoJSON FeatureCollection.

    Raises:
        ValueError: If the result has no map.
    """
    spec = _map_of(result)
    table = result.table(spec.table)
    codes = [str(row[spec.code_column]) for row in table.rows]
    field = geo_code_field(spec.geography_type, spec.geography_year)
    features: list[dict[str, Any]] = []
    for start in range(0, len(codes), BOUNDARY_BATCH_SIZE):
        filters: dict[str, Any] = {field: codes[start : start + BOUNDARY_BATCH_SIZE]}
        geojson = load_geodata(
            spec.geography_type,
            year=str(spec.geography_year),
            coverage=_COVERAGE.get(spec.geography_type, "UK"),
            boundary_type=BOUNDARY_TYPE,
            **filters,
        )
        features.extend(geojson.get("features", []))
    return {"type": "FeatureCollection", "features": features}


def render_map(
    result: AnalysisResult,
    layer: str | None = None,
    boundaries: dict[str, Any] | None = None,
    width: int = 720,
) -> str:
    """Draw one layer of a result's map as an SVG picture.

    Args:
        result: An analysis result that has a map.
        layer: The id of the layer to colour areas by. The first layer is used
            when this is left out.
        boundaries: A GeoJSON FeatureCollection of the areas. Left out, the
            boundaries are fetched with :func:`load_map_boundaries`. Outlines
            of places that are not in the result are drawn around the map in
            pale grey. They can be among the features or in a list under
            ``"surroundings"``. Codes listed under ``"focus"`` are the
            surrounding places that hold the shaded areas: each gets a darker
            line and its name.
        width: Width of the picture in pixels.

    Returns:
        The SVG as text. Save it to a ``.svg`` file or put it in a web page.

    Raises:
        ValueError: If the result has no map, the layer id is unknown, or no
            boundary matches an area in the result.
    """
    spec = _map_of(result)
    chosen = _layer_of(spec, layer)
    table = result.table(spec.table)
    geojson = load_map_boundaries(result) if boundaries is None else boundaries
    shapes = _shapes(geojson, spec)
    rows = {str(row[spec.code_column]): row for row in table.rows}
    drawn = sorted(code for code in rows if code in shapes)
    if not drawn:
        msg = "None of the boundaries matches an area in the result."
        raise ValueError(msg)
    if len(drawn) < len(rows):
        logger.warning(
            "%d of %d areas have no boundary and are not drawn.",
            len(rows) - len(drawn),
            len(rows),
        )
    title = _wrap(_heading(spec, chosen), _letters(width, _TITLE_SIZE, _BOLD_LETTER))
    view = _View([shapes[code] for code in drawn], width, len(title) * _TITLE_LINE + 18)
    areas = {code: (rows[code], view.rings(shapes[code])) for code in drawn}
    around = _around(geojson, set(rows), view)
    names = _place_names(areas, around)
    key_top = round(view.top + view.height) + 16
    key, note_top = _key(chosen, key_top, width)
    note = _wrap(chosen.note, _letters(width, _NOTE_SIZE))
    credit_top = note_top + len(note) * _NOTE_LINE + 6
    credit = _wrap(_credit(result), _letters(width, _CREDIT_SIZE))
    height = credit_top + len(credit) * _CREDIT_LINE + _MARGIN
    scope = _scope(chosen)
    parts = [
        _open_svg(width, height, spec, chosen),
        _style(chosen, spec.layers.index(chosen)),
        f'<rect class="surface" width="{width}" height="{height}"/>',
        _lines(title, 26, _TITLE_LINE, "ink", _TITLE_SIZE, bold=True),
        f'<clipPath id="{scope}-frame">{view.frame()}</clipPath>',
        f'<g clip-path="url(#{scope}-frame)">',
        *(_ring_path(place.rings, "land") for place in around),
        *(_area_path(rings, row, chosen) for row, rings in areas.values()),
        *(_ring_path(place.rings, "outline") for place in around if place.focus),
        *(_name_text(name) for name in _around_names(around, view, names)),
        *(_name_text(name) for name in names),
        "</g>",
        view.frame("frame"),
        _scale_mark(view),
        key,
        _lines(note, note_top + 11, _NOTE_LINE, "ink2", _NOTE_SIZE),
        _lines(credit, credit_top + 11, _CREDIT_LINE, "ink2", _CREDIT_SIZE),
        "</svg>",
    ]
    return "\n".join(part for part in parts if part)


# --- reading the description and the boundaries ----------------------------


def _map_of(result: AnalysisResult) -> MapSpec:
    """Return the result's map description, or say there is none."""
    if result.map is None:
        msg = "This result has no map."
        raise ValueError(msg)
    return result.map


def _layer_of(spec: MapSpec, layer_id: str | None) -> MapLayer:
    """Pick a layer by id, or the first when no id is given."""
    if layer_id is None:
        return spec.layers[0]
    for layer in spec.layers:
        if layer.id == layer_id:
            return layer
    known = ", ".join(layer.id for layer in spec.layers)
    msg = f"The map has no layer called '{layer_id}'. Its layers are: {known}."
    raise ValueError(msg)


def _shapes(geojson: dict[str, Any], spec: MapSpec) -> dict[str, list[Any]]:
    """Return the rings of each area, keyed by area code."""
    field = geo_code_field(spec.geography_type, spec.geography_year)
    shapes: dict[str, list[Any]] = {}
    for feature in geojson.get("features", []):
        code = (feature.get("properties") or {}).get(field)
        geometry = feature.get("geometry") or {}
        rings = list(_rings(geometry))
        if code and rings:
            shapes[str(code)] = rings
    return shapes


def _rings(geometry: dict[str, Any]) -> Iterator[list[Any]]:
    """Yield every ring of a Polygon or MultiPolygon."""
    kind = geometry.get("type")
    coordinates = geometry.get("coordinates") or []
    if kind == "Polygon":
        yield from coordinates
    elif kind == "MultiPolygon":
        for polygon in coordinates:
            yield from polygon


class _View:
    """Where the map sits in the picture.

    The shaded areas are in the middle with some room around them, in a frame
    as wide as the picture. The frame is never very flat, so a wide place
    still shows what is north and south of it.
    """

    def __init__(self, shapes: list[list[Any]], width: int, top: int) -> None:
        points = [point for rings in shapes for ring in rings for point in ring]
        lons = [point[0] for point in points]
        lats = [point[1] for point in points]
        # A degree of longitude is shorter than a degree of latitude away from
        # the equator, so it is squeezed by the cosine of the latitude.
        self._squeeze = math.cos(math.radians((min(lats) + max(lats)) / 2))
        room = 1 + 2 * _ROOM
        span_x = max((max(lons) - min(lons)) * self._squeeze * room, 1e-9)
        span_y = max((max(lats) - min(lats)) * room, 1e-9)
        self.left = _MARGIN
        self.top = top
        self.width = width - 2 * _MARGIN
        self._scale = min(self.width / span_x, _MAX_MAP_HEIGHT / span_y)
        self.height = round(max(span_y * self._scale, _MIN_MAP_HEIGHT))
        self._middle = ((min(lons) + max(lons)) / 2, (min(lats) + max(lats)) / 2)
        self.pixels_per_km = self._scale / _KM_PER_DEGREE

    def point(self, lon: float, lat: float) -> tuple[float, float]:
        """Return a place on the ground as a point on the picture."""
        x = self.left + self.width / 2
        y = self.top + self.height / 2
        x += (lon - self._middle[0]) * self._squeeze * self._scale
        return x, y - (lat - self._middle[1]) * self._scale

    def rings(self, rings: list[Any]) -> list[_Ring]:
        """Return the rings of an outline as points on the picture."""
        return [[self.point(point[0], point[1]) for point in ring] for ring in rings]

    def shows(self, rings: list[_Ring]) -> bool:
        """Say whether any part of an outline could fall inside the frame."""
        xs = [x for ring in rings for x, _ in ring]
        ys = [y for ring in rings for _, y in ring]
        return (
            min(xs) <= self.left + self.width
            and max(xs) >= self.left
            and min(ys) <= self.top + self.height
            and max(ys) >= self.top
        )

    def frame(self, css_class: str = "") -> str:
        """Draw the rectangle the map sits in."""
        named = f' class="{css_class}"' if css_class else ""
        return (
            f'<rect{named} x="{self.left}" y="{self.top}" '
            f'width="{self.width}" height="{self.height}"/>'
        )


_Ring = list[tuple[float, float]]


@dataclass(frozen=True)
class _Place:
    """A place around the map.

    ``focus`` is true when the place holds the shaded areas.
    """

    name: str
    rings: list[_Ring]
    focus: bool


@dataclass(frozen=True)
class _Name:
    """A name written on the map, with the room it takes."""

    text: str
    x: float
    y: float
    width: float
    css_class: str


def _around(geojson: dict[str, Any], shaded: set[str], view: _View) -> list[_Place]:
    """Return the places around the map that the frame shows.

    They are every outline given for a place that the result does not shade.
    """
    focus = {str(code) for code in geojson.get("focus", [])}
    features = [*geojson.get("features", []), *geojson.get("surroundings", [])]
    places = []
    for feature in features:
        properties = feature.get("properties") or {}
        code = _property(properties, "CD")
        rings = view.rings(list(_rings(feature.get("geometry") or {})))
        if code in shaded or not rings or not view.shows(rings):
            continue
        places.append(_Place(_property(properties, "NM"), rings, code in focus))
    return places


def _property(properties: dict[str, Any], ending: str) -> str:
    """Return the code or the name of an outline, whatever year its field has.

    The service names a field after its layer and year, such as ``LAD23CD``
    and ``LAD23NM``.
    """
    for key, value in properties.items():
        if str(key).upper().endswith(ending) and value:
            return str(value)
    return ""


# --- colour ----------------------------------------------------------------


def _ramp(steps: int, position: int) -> list[str]:
    """Pick evenly spaced colours from a layer's ramp, lightest first."""
    ramp = _RAMPS[position % len(_RAMPS)]
    if steps <= 1:
        return [ramp[len(ramp) // 2]]
    last = len(ramp) - 1
    return [ramp[round(index * last / (steps - 1))] for index in range(steps)]


def _strength(layer: MapLayer) -> list[int]:
    """Return each category's position on the ramp, 0 being the weakest."""
    order = list(range(len(layer.categories)))
    return order[::-1] if layer.emphasis == "low" else order


def _class_of(layer: MapLayer, value: Any) -> str:
    """Return the style class for a value, or the class for no data."""
    if value not in layer.categories:
        return "none"
    return f"c{_strength(layer)[layer.categories.index(value)]}"


def _scope(layer: MapLayer) -> str:
    """Return the class that ties style rules and ids to one map layer."""
    safe = "".join(char if char.isalnum() else "-" for char in layer.id)
    return f"kindtech-map-{safe}"


def _style(layer: MapLayer, position: int) -> str:
    """Write the colours once, for light and for dark surroundings.

    On a dark surface the ramp runs the other way, so the weakest colour still
    sits closest to the background.
    """
    ramp = _ramp(len(layer.categories), position)
    # Every rule is tied to this map, so two maps on one page keep their own
    # colours.
    scope = f".{_scope(layer)}"

    def rules(theme: dict[str, str], colours: list[str]) -> str:
        fills = "".join(
            f"{scope} .c{index}{{fill:{colour}}}"
            for index, colour in enumerate(colours)
        )
        halo = "stroke-linejoin:round;paint-order:stroke"
        return (
            f"{scope} .surface{{fill:{theme['surface']}}}"
            f"{scope} .area{{stroke:{theme['surface']};stroke-width:0.6}}"
            f"{scope} .none{{fill:{theme['none']}}}"
            f"{scope} .ink{{fill:{theme['ink']}}}"
            f"{scope} .ink2{{fill:{theme['ink2']}}}"
            f"{scope} .land{{fill:{theme['land']};stroke:{theme['border']};"
            "stroke-width:0.8}"
            f"{scope} .outline{{fill:none;stroke:{theme['outline']};"
            "stroke-width:1.2}"
            f"{scope} .frame{{fill:none;stroke:{theme['frame']}}}"
            f"{scope} .rule{{fill:none;stroke:{theme['ink']};stroke-width:1.2}}"
            f"{scope} .key{{stroke:{theme['border']};stroke-width:0.5}}"
            f"{scope} .name{{fill:{theme['ink']};stroke:{theme['surface']};"
            f"stroke-width:3;{halo}}}"
            f"{scope} .held{{fill:{theme['ink']};stroke:{theme['surface']};"
            f"stroke-width:4;font-weight:700;{halo}}}"
            f"{scope} .near{{fill:{theme['ink2']};stroke:{theme['land']};"
            f"stroke-width:3;{halo}}}"
            f"{fills}"
        )

    return (
        f"<style>{scope} text{{font-family:{_FONT}}}"
        f"{scope} path{{stroke-linejoin:round}}"
        f"{rules(_LIGHT, ramp)}"
        f"@media (prefers-color-scheme: dark){{{rules(_DARK, ramp[::-1])}}}"
        "</style>"
    )


# --- words -----------------------------------------------------------------


def _heading(spec: MapSpec, layer: MapLayer) -> str:
    """Say what the colour shows, so the title fits the layer that is drawn."""
    area = AREA_WORDS.get(spec.geography_type, ("area", "areas"))[0]
    return f"{layer.label}, by {area}"


def _credit(result: AnalysisResult) -> str:
    """Say where the figures and the outlines come from."""
    names = "; ".join(f"{source.name}, {source.publisher}" for source in result.sources)
    return f"Sources: {names}. {BOUNDARY_CREDIT}"


def _letters(width: int, size: int, letter: float = _LETTER) -> int:
    """Work out how many letters of a size fit across the picture."""
    return max(20, int((width - 2 * _MARGIN) / (size * letter)))


def _wrap(text: str, letters: int) -> list[str]:
    """Break a sentence into lines at spaces, so none is longer than fits."""
    lines: list[str] = []
    line = ""
    for word in text.split():
        if line and len(line) + len(word) + 1 > letters:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    return [*lines, line] if line else lines


def _lines(
    lines: list[str], top: int, step: int, css_class: str, size: int, bold: bool = False
) -> str:
    """Write lines of text one under another, from the left margin."""
    weight = ' font-weight="700"' if bold else ""
    return "".join(
        f'<text class="{css_class}" x="{_MARGIN}" y="{top + index * step}" '
        f'font-size="{size}"{weight}>{escape(line)}</text>'
        for index, line in enumerate(lines)
    )


# --- drawing ---------------------------------------------------------------


def _open_svg(width: int, height: int, spec: MapSpec, layer: MapLayer) -> str:
    """Open the picture, with a title and description for screen readers."""
    areas = AREA_WORDS.get(spec.geography_type, ("area", "areas"))[1]
    description = f"Map of {areas}. {layer.note}".strip()
    scope = _scope(layer)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" class="{scope}" '
        f'width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'role="img" aria-labelledby="{scope}-title {scope}-desc">'
        f'<title id="{scope}-title">{escape(_heading(spec, layer))}</title>'
        f'<desc id="{scope}-desc">{escape(description)}</desc>'
    )


def _d(rings: list[_Ring]) -> str:
    """Write rings as the path of an outline."""
    return " ".join(
        "M " + " L ".join(f"{x:.1f} {y:.1f}" for x, y in ring) + " Z" for ring in rings
    )


def _ring_path(rings: list[_Ring], css_class: str) -> str:
    """Draw an outline that is not shaded: a place around, or a line round one."""
    return f'<path class="{css_class}" d="{_d(rings)}"/>'


def _area_path(rings: list[_Ring], row: dict[str, Any], layer: MapLayer) -> str:
    """Draw one area, with its name and value shown on hover."""
    value = row.get(layer.value_column)
    name = row.get("geography_name") or row.get("geography_code") or ""
    shown = "no data" if value is None else value
    return (
        f'<path class="area {_class_of(layer, value)}" fill-rule="evenodd" '
        f'd="{_d(rings)}"><title>{escape(f"{name}: {layer.label} {shown}")}'
        "</title></path>"
    )


def _scale_length(pixels_per_km: float) -> tuple[float, str]:
    """Pick the longest round distance that fits a scale line, and its words."""
    fitting = [km for km in _SCALE_LENGTHS if km * pixels_per_km <= _MAX_SCALE_WIDTH]
    km = fitting[-1] if fitting else _SCALE_LENGTHS[0]
    return km * pixels_per_km, f"{km * 1000:g} m" if km < 1 else f"{km:g} km"


def _scale_mark(view: _View) -> str:
    """Draw the scale line at the bottom left of the frame."""
    length, words = _scale_length(view.pixels_per_km)
    x = view.left + 12
    y = view.top + view.height - 14
    return (
        f'<rect class="surface" fill-opacity="0.85" x="{x - 6}" y="{y - 20}" '
        f'width="{max(length, 40) + 12:.1f}" height="27" rx="3"/>'
        f'<path class="rule" d="M {x} {y - 4} V {y} H {x + length:.1f} V {y - 4}"/>'
        f'<text class="ink" x="{x}" y="{y - 8}" font-size="11">{words}</text>'
    )


def _key(layer: MapLayer, top: int, width: int) -> tuple[str, int]:
    """Draw a box and a label for every category, lowest first.

    The boxes sit in one row with each label under its box. When a label is
    too long for that, each category takes a box and its label side by side.

    Returns:
        The key, and where the text under it starts.
    """
    labels = [str(category) for category in layer.categories]
    longest = max((len(label) for label in labels), default=1)
    short = longest <= 3
    inner = width - 2 * _MARGIN
    box = min(_KEY_SHORT if short else _KEY_WIDEST, inner // max(len(labels), 1))
    if longest * _NAME_LETTER > box - 4 and not short:
        return _key_rows(layer, labels, top, inner)
    parts = []
    for index, label in enumerate(labels):
        x = _MARGIN + index * box
        at = f'x="{x + (box - 2) / 2:g}" text-anchor="middle"' if short else f'x="{x}"'
        parts.append(
            f'<rect class="key {_class_of(layer, layer.categories[index])}" '
            f'x="{x}" y="{top}" width="{box - 2}" height="{_KEY_BOX}"/>'
            f'<text class="ink" {at} y="{top + 30}" font-size="12">'
            f"{escape(label)}</text>"
        )
    return "".join(parts), top + 40


def _key_rows(
    layer: MapLayer, labels: list[str], top: int, inner: int
) -> tuple[str, int]:
    """Draw the key with each label beside its box, in as many rows as needed."""
    longest = max(len(label) for label in labels)
    entry = _KEY_BOX + 6 + round(longest * _NAME_LETTER) + 16
    columns = max(1, inner // entry)
    parts = []
    for index, label in enumerate(labels):
        x = _MARGIN + (index % columns) * entry
        y = top + (index // columns) * _KEY_ROW
        parts.append(
            f'<rect class="key {_class_of(layer, layer.categories[index])}" '
            f'x="{x}" y="{y}" width="{_KEY_BOX}" height="{_KEY_BOX}"/>'
            f'<text class="ink" x="{x + _KEY_BOX + 6}" y="{y + 11}" '
            f'font-size="12">{escape(label)}</text>'
        )
    return "".join(parts), top + math.ceil(len(labels) / columns) * _KEY_ROW + 4


# --- names -----------------------------------------------------------------


def _name_text(name: _Name) -> str:
    """Write a name on the map, centred on its spot."""
    size = 13 if name.css_class == "held" else 12 if name.css_class == "name" else 11
    return (
        f'<text class="{name.css_class}" x="{name.x:.1f}" y="{name.y + 4:.1f}" '
        f'text-anchor="middle" font-size="{size}">{escape(name.text)}</text>'
    )


def _place_names(
    areas: dict[str, tuple[dict[str, Any], list[_Ring]]], around: list[_Place]
) -> list[_Name]:
    """Name the shaded places.

    Neighbourhoods get one name for each local authority, at the middle of
    its neighbourhoods. With places drawn around them even a single authority
    is named, so the picture says where it is. Larger areas are named one by
    one when there are few enough to read.
    """
    grouped = any(row.get("lad_name") for row, _ in areas.values())
    if not grouped and len(areas) > _MAX_NAMES:
        return []
    boxes: dict[str, list[tuple[float, float]]] = {}
    for row, rings in areas.values():
        name = str(row.get("lad_name") if grouped else row.get("geography_name") or "")
        boxes.setdefault(name, []).extend(point for ring in rings for point in ring)
    boxes.pop("", None)
    if grouped and len(boxes) < 2 and not around:
        return []
    names = []
    for name, points in boxes.items():
        xs = [x for x, _ in points]
        ys = [y for _, y in points]
        wide = len(name) * _NAME_LETTER * (1.25 if grouped else 1.1)
        spot = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
        names.append(_Name(name, *spot, wide, "held" if grouped else "name"))
    return names


def _around_names(around: list[_Place], view: _View, taken: list[_Name]) -> list[_Name]:
    """Name the places around the map, each where its name fits.

    A name goes inside the part of its place that the frame shows. A name
    with no room, or one that would sit on another name, is left out. A place
    that holds the shaded areas is named with them, so it is not named here.
    """
    names: list[_Name] = []
    kept_clear = [*taken, _scale_room(view)]
    for place in around:
        wide = len(place.name) * _NAME_LETTER
        named = place.name and not place.focus
        spot = _name_spot(place.rings, view, wide) if named else None
        if spot is None:
            continue
        name = _Name(place.name, *spot, wide, "near")
        if all(_clear(name, other) for other in [*kept_clear, *names]):
            names.append(name)
    return names


def _scale_room(view: _View) -> _Name:
    """Return the room the scale line takes, so that no name is put on it."""
    wide = max(_scale_length(view.pixels_per_km)[0], 40) + 12
    return _Name("", view.left + 6 + wide / 2, view.top + view.height - 20, wide, "")


def _clear(name: _Name, other: _Name) -> bool:
    """Say whether two names keep out of each other's way."""
    apart = abs(other.x - name.x) > (other.width + name.width) / 2 + 6
    return apart or abs(other.y - name.y) > 16


def _name_spot(
    rings: list[_Ring], view: _View, wide: float
) -> tuple[float, float] | None:
    """Find where a name of a given width fits inside an outline and the frame.

    It is the middle of the widest stretch that has room above and below it
    too. There may be no such place.
    """
    levels = range(view.top + _NAME_STEP, view.top + view.height - _NAME_STEP + 1, 10)
    rows = [_spans(rings, y, view, wide) for y in levels]

    def holds(index: int, x: float) -> bool:
        if not 0 <= index < len(rows):
            return False
        return any(
            start <= x - wide / 2 - 4 and end >= x + wide / 2 + 4
            for start, end in rows[index]
        )

    best: tuple[float, float, float] | None = None
    for index, spans in enumerate(rows):
        for start, end in spans:
            x = (start + end) / 2
            depth = 0
            while (
                depth < 4
                and holds(index - depth - 1, x)
                and holds(index + depth + 1, x)
            ):
                depth += 1
            score = depth * min(end - start, 3 * wide)
            if depth and (best is None or score > best[2]):
                best = (x, levels[index], score)
    return None if best is None else (best[0], best[1])


def _spans(
    rings: list[_Ring], y: float, view: _View, wide: float
) -> list[tuple[float, float]]:
    """Return the stretches of a level line inside an outline that hold a name.

    The outline is entered at every other crossing and left at the ones
    between.
    """
    xs = sorted(
        x1 + (y - y1) / (y2 - y1) * (x2 - x1)
        for ring in rings
        for (x1, y1), (x2, y2) in zip(ring, [ring[-1], *ring[:-1]], strict=True)
        if (y1 > y) != (y2 > y)
    )
    spans = []
    for start, end in zip(xs[::2], xs[1::2], strict=False):
        start = max(start, view.left + 4)
        end = min(end, view.left + view.width - 4)
        if end - start >= wide + 8:
            spans.append((start, end))
    return spans
