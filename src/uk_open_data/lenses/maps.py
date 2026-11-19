"""Drawing the map a lens describes, as a still picture.

A :class:`~uk_open_data.lenses.LensResult` carries a description of a map: which
areas, and what to colour them by. :func:`render_map` turns that into an SVG
picture with a legend, using boundaries from the ONS Open Geography Portal.

The picture is drawn from the result's table of totals, so it shows nothing
the result does not already hold.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Iterator
from html import escape
from typing import Any

from uk_open_data._mapping import geo_code_field
from uk_open_data.geo import load_geodata
from uk_open_data.lenses._model import LensResult, MapLayer, MapSpec

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

# One hue, light to dark. Light means little; dark means a lot.
_RAMP = (
    "#cde2fb",
    "#b7d3f6",
    "#9ec5f4",
    "#86b6ef",
    "#6da7ec",
    "#5598e7",
    "#3987e5",
    "#2a78d6",
    "#256abf",
    "#1c5cab",
    "#184f95",
    "#104281",
    "#0d366b",
)
_LIGHT = {"surface": "#fcfcfb", "ink": "#0b0b0b", "ink2": "#52514e", "none": "#e1e0d9"}
_DARK = {"surface": "#1a1a19", "ink": "#f0efec", "ink2": "#c3c2b7", "none": "#2c2c2a"}

_MARGIN = 16
_TITLE_HEIGHT = 58
_SWATCH = 14
_LEGEND_ROW = 22
_FOOTER_LINE = 15
_FONT = "system-ui, -apple-system, 'Segoe UI', sans-serif"


def load_map_boundaries(result: LensResult) -> dict[str, Any]:
    """Fetch the boundaries of every area on a result's map.

    Only area codes are sent to the boundary service. They are public codes for
    the whole catchment, so they say nothing about where people in the data
    live.

    Args:
        result: A lens result that has a map.

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
    result: LensResult,
    layer: str | None = None,
    boundaries: dict[str, Any] | None = None,
    width: int = 720,
) -> str:
    """Draw one layer of a result's map as an SVG picture.

    Args:
        result: A lens result that has a map.
        layer: The id of the layer to colour areas by. The first layer is used
            when this is left out.
        boundaries: A GeoJSON FeatureCollection of the areas. Left out, the
            boundaries are fetched with :func:`load_map_boundaries`.
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
    drawn = [code for code in rows if code in shapes]
    if not drawn:
        msg = "None of the boundaries matches an area in the result."
        raise ValueError(msg)
    if len(drawn) < len(rows):
        logger.warning(
            "%d of %d areas have no boundary and are not drawn.",
            len(rows) - len(drawn),
            len(rows),
        )
    projection = _Projection([shapes[code] for code in drawn], width)
    legend_rows = math.ceil(len(chosen.categories) / _legend_columns(chosen, width))
    legend_top = _TITLE_HEIGHT + projection.height + _MARGIN
    footer_top = legend_top + legend_rows * _LEGEND_ROW + 8
    footer = _footer_lines(result)
    height = footer_top + len(footer) * _FOOTER_LINE + _MARGIN
    parts = [
        _open_svg(width, height, spec, chosen),
        _style(chosen),
        f'<rect class="surface" width="{width}" height="{height}"/>',
        _heading(spec, chosen),
        f'<g transform="translate(0 {_TITLE_HEIGHT})">',
        *(
            _area_path(shapes[code], rows[code], chosen, projection)
            for code in sorted(drawn)
        ),
        "</g>",
        _legend(chosen, legend_top, width),
        _footer(footer, footer_top),
        "</svg>",
    ]
    return "\n".join(parts)


# --- reading the description and the boundaries ----------------------------


def _map_of(result: LensResult) -> MapSpec:
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


class _Projection:
    """Fits longitude and latitude into the picture, keeping shapes true."""

    def __init__(self, shapes: list[list[Any]], width: int) -> None:
        points = [point for rings in shapes for ring in rings for point in ring]
        lons = [point[0] for point in points]
        lats = [point[1] for point in points]
        self._west, self._north = min(lons), max(lats)
        # A degree of longitude is shorter than a degree of latitude away from
        # the equator, so it is squeezed by the cosine of the latitude.
        self._squeeze = math.cos(math.radians((min(lats) + max(lats)) / 2))
        span_x = (max(lons) - min(lons)) * self._squeeze or 1e-9
        span_y = (max(lats) - min(lats)) or 1e-9
        inner = width - 2 * _MARGIN
        self._scale = min(inner / span_x, inner / span_y)
        self._left = _MARGIN + (inner - span_x * self._scale) / 2
        self.height = round(span_y * self._scale)

    def point(self, lon: float, lat: float) -> str:
        """Return a point as picture coordinates."""
        x = self._left + (lon - self._west) * self._squeeze * self._scale
        y = (self._north - lat) * self._scale
        return f"{x:.1f} {y:.1f}"


# --- colour ----------------------------------------------------------------


def _ramp(steps: int) -> list[str]:
    """Pick evenly spaced colours from the ramp, lightest first."""
    if steps <= 1:
        return [_RAMP[len(_RAMP) // 2]]
    last = len(_RAMP) - 1
    return [_RAMP[round(index * last / (steps - 1))] for index in range(steps)]


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


def _style(layer: MapLayer) -> str:
    """Write the colours once, for light and for dark surroundings.

    On a dark surface the ramp runs the other way, so the weakest colour still
    sits closest to the background.
    """
    ramp = _ramp(len(layer.categories))
    # Every rule is tied to this map, so two maps on one page keep their own
    # colours.
    scope = f".{_scope(layer)}"

    def rules(theme: dict[str, str], colours: list[str]) -> str:
        fills = "".join(
            f"{scope} .c{index}{{fill:{colour}}}"
            for index, colour in enumerate(colours)
        )
        return (
            f"{scope} .surface{{fill:{theme['surface']}}}"
            f"{scope} .area{{stroke:{theme['surface']};stroke-width:0.6}}"
            f"{scope} .none{{fill:{theme['none']}}}"
            f"{scope} .ink{{fill:{theme['ink']}}}"
            f"{scope} .ink2{{fill:{theme['ink2']}}}"
            f"{fills}"
        )

    return (
        f"<style>{scope} text{{font-family:{_FONT}}}"
        f"{rules(_LIGHT, ramp)}"
        f"@media (prefers-color-scheme: dark){{{rules(_DARK, ramp[::-1])}}}"
        "</style>"
    )


# --- drawing ---------------------------------------------------------------


def _open_svg(width: int, height: int, spec: MapSpec, layer: MapLayer) -> str:
    """Open the picture, with a title and description for screen readers."""
    description = f"{layer.label} for each area. {layer.note}".strip()
    scope = _scope(layer)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" class="{scope}" '
        f'width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'role="img" aria-labelledby="{scope}-title {scope}-desc">'
        f'<title id="{scope}-title">{escape(spec.title)}</title>'
        f'<desc id="{scope}-desc">{escape(description)}</desc>'
    )


def _heading(spec: MapSpec, layer: MapLayer) -> str:
    """Write the title and, under it, what the colour shows."""
    subtitle = f"{layer.label}. {layer.note}".strip()
    return (
        f'<text class="ink" x="{_MARGIN}" y="26" font-size="16" '
        f'font-weight="600">{escape(spec.title)}</text>'
        f'<text class="ink2" x="{_MARGIN}" y="46" font-size="12">'
        f"{escape(subtitle)}</text>"
    )


def _area_path(
    rings: list[Any], row: dict[str, Any], layer: MapLayer, projection: _Projection
) -> str:
    """Draw one area, with its name and value shown on hover."""
    path = " ".join(
        "M " + " L ".join(projection.point(point[0], point[1]) for point in ring) + " Z"
        for ring in rings
    )
    value = row.get(layer.value_column)
    name = row.get("geography_name") or row.get("geography_code") or ""
    shown = "no data" if value is None else value
    return (
        f'<path class="area {_class_of(layer, value)}" fill-rule="evenodd" '
        f'd="{path}"><title>{escape(f"{name}: {layer.label} {shown}")}</title></path>'
    )


def _legend_columns(layer: MapLayer, width: int) -> int:
    """Work out how many legend entries fit on one row."""
    longest = max((len(str(category)) for category in layer.categories), default=1)
    entry = _SWATCH + 6 + longest * 7 + 16
    return max(1, (width - 2 * _MARGIN) // entry)


def _legend(layer: MapLayer, top: int, width: int) -> str:
    """Draw a swatch and a label for every category, lowest first."""
    columns = _legend_columns(layer, width)
    entry = (width - 2 * _MARGIN) // columns
    parts = []
    for index, category in enumerate(layer.categories):
        x = _MARGIN + (index % columns) * entry
        y = top + (index // columns) * _LEGEND_ROW
        parts.append(
            f'<rect class="{_class_of(layer, category)}" x="{x}" y="{y}" '
            f'width="{_SWATCH}" height="{_SWATCH}" rx="2"/>'
            f'<text class="ink2" x="{x + _SWATCH + 6}" y="{y + 11}" '
            f'font-size="12">{escape(str(category))}</text>'
        )
    return "".join(parts)


def _footer_lines(result: LensResult) -> list[str]:
    """List the credits printed under the map."""
    names = "; ".join(f"{source.name}, {source.publisher}" for source in result.sources)
    return [f"Data: {names}.", BOUNDARY_CREDIT]


def _footer(lines: list[str], top: int) -> str:
    """Write the credits."""
    return "".join(
        f'<text class="ink2" x="{_MARGIN}" y="{top + 11 + index * _FOOTER_LINE}" '
        f'font-size="10">{escape(line)}</text>'
        for index, line in enumerate(lines)
    )
