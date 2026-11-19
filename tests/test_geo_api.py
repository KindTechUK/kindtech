"""
Unit tests for the KindTech Geo API.

These tests focus on how users interact with the public API methods.
External web requests are mocked to ensure tests are isolated and repeatable.
The catalog (CSV-based) is not mocked — it loads real service metadata.
"""

import unittest.mock as mock

import pytest
import requests

from uk_open_data.geo import (
    BoundaryType,
    CoverageArea,
    GeographyType,
    api,
    geodata_to_properties,
    get_available_boundary_types,
    get_available_coverage_areas,
    get_available_geography_types,
    get_field_info,
    load_geodata,
)

REAL_FIRST_LAYER = api._first_layer


@pytest.fixture(autouse=True)
def layer_zero(monkeypatch):
    """Every service holds layer 0, and is not asked, unless a test says so."""
    monkeypatch.setattr(api, "_LAYERS", {})
    monkeypatch.setattr(api, "_first_layer", lambda service_url: 0)


@pytest.fixture
def asks_for_layers(monkeypatch):
    """Let a test see the request that asks a service for its layers."""
    monkeypatch.setattr(api, "_first_layer", REAL_FIRST_LAYER)


def _answers(*payloads: object) -> mock.Mock:
    """A service that gives these answers in order; an exception is raised."""
    responses = []
    for payload in payloads:
        if isinstance(payload, Exception):
            responses.append(payload)
            continue
        response = mock.MagicMock()
        response.json.return_value = payload
        responses.append(response)
    return mock.Mock(side_effect=responses)


GEOJSON_RESPONSE = {
    "type": "FeatureCollection",
    "features": [{"properties": {"LAD21NM": "Manchester"}}],
}


@mock.patch("uk_open_data.geo.api.requests.get")
def test_load_geodata_basic(mock_get):
    """Test loading geodata with basic string parameters."""
    mock_response = mock.MagicMock()
    mock_response.json.return_value = GEOJSON_RESPONSE
    mock_get.return_value = mock_response

    result = load_geodata(geography_type="LAD", coverage="UK", boundary_type="BGC")

    assert result["type"] == "FeatureCollection"
    assert len(result["features"]) > 0
    mock_get.assert_called_once()
    call_url = mock_get.call_args[0][0]
    assert "FeatureServer" in call_url
    assert "query" in call_url


@mock.patch("uk_open_data.geo.api.requests.get")
def test_load_geodata_with_filters(mock_get):
    """Test loading geodata with filters."""
    mock_response = mock.MagicMock()
    mock_response.json.return_value = {
        "type": "FeatureCollection",
        "features": [{"properties": {"LAD21NM": "Manchester", "LAD21CD": "E08000003"}}],
    }
    mock_get.return_value = mock_response

    result = load_geodata(geography_type="LAD", LAD21NM="Manchester")

    assert result["type"] == "FeatureCollection"
    assert len(result["features"]) == 1
    assert result["features"][0]["properties"]["LAD21NM"] == "Manchester"

    # Verify the WHERE clause was built correctly
    call_params = mock_get.call_args[1]["params"]
    assert call_params["where"] == "LAD21NM = 'Manchester'"


@mock.patch("uk_open_data.geo.api.requests.get")
def test_load_geodata_with_enum_parameters(mock_get):
    """Test loading geodata with enum parameters."""
    mock_response = mock.MagicMock()
    mock_response.json.return_value = GEOJSON_RESPONSE
    mock_get.return_value = mock_response

    result = load_geodata(
        geography_type=GeographyType.LAD,
        coverage=CoverageArea.UK,
        boundary_type=BoundaryType.BGC,
    )

    assert result["type"] == "FeatureCollection"
    assert len(result["features"]) > 0


def test_load_geodata_no_matching_service():
    """Test loading geodata when no matching service is found."""
    result = load_geodata(geography_type="NONEXISTENT")

    assert result["type"] == "FeatureCollection"
    assert len(result["features"]) == 0


@mock.patch("uk_open_data.geo.api.requests.get")
def test_load_geodata_with_request_error(mock_get):
    """Test loading geodata when request raises an exception."""
    mock_get.side_effect = requests.exceptions.RequestException("Connection error")

    result = load_geodata(geography_type="LAD")

    assert result["type"] == "FeatureCollection"
    assert len(result["features"]) == 0


@pytest.mark.usefixtures("asks_for_layers")
def test_load_geodata_reads_the_layer_a_service_holds():
    """Not every service numbers its layer 0, so the service is asked once."""
    layers = {"layers": [{"id": 3, "name": "LSOA_2021_EW_BFE_V10_RUC"}]}
    get = _answers(layers, GEOJSON_RESPONSE, GEOJSON_RESPONSE)
    with mock.patch("uk_open_data.geo.api.requests.get", get):
        first = load_geodata("LSOA", year="2021", boundary_type="BFE")
        second = load_geodata("LSOA", year="2021", boundary_type="BFE")

    assert first == second == GEOJSON_RESPONSE
    asked = [call.args[0] for call in get.call_args_list]
    assert asked[0].endswith("/FeatureServer")
    assert asked[1].endswith("/FeatureServer/3/query")
    # The second call did not ask for the layers again.
    assert asked[2].endswith("/FeatureServer/3/query")


@pytest.mark.usefixtures("asks_for_layers")
@pytest.mark.parametrize(
    "listing",
    [
        requests.exceptions.RequestException("Connection error"),
        {"layers": []},
        {"error": {"code": 499, "message": "Token Required"}},
    ],
)
def test_load_geodata_tries_layer_zero_when_a_service_lists_no_layer(listing):
    """A service that cannot say is tried at layer 0, and asked again next time."""
    get = _answers(listing, GEOJSON_RESPONSE, listing, GEOJSON_RESPONSE)
    with mock.patch("uk_open_data.geo.api.requests.get", get):
        load_geodata(geography_type="LAD")
        load_geodata(geography_type="LAD")

    asked = [call.args[0] for call in get.call_args_list]
    assert [url.rsplit("/FeatureServer", 1)[1] for url in asked] == [
        "",
        "/0/query",
        "",
        "/0/query",
    ]


@pytest.mark.usefixtures("asks_for_layers")
def test_get_field_info_reads_the_layer_a_service_holds():
    fields = {"fields": [{"name": "LSOA21CD"}]}
    get = _answers({"layers": [{"id": 3}]}, fields)
    with mock.patch("uk_open_data.geo.api.requests.get", get):
        result = get_field_info("LSOA", year="2021", boundary_type="BFE")

    assert result == fields["fields"]
    assert get.call_args_list[1].args[0].endswith("/FeatureServer/3")


def _paged(pages: list[dict]) -> mock.Mock:
    """A boundary service that gives one page for each request, in order."""
    responses = []
    for page in pages:
        response = mock.MagicMock()
        response.json.return_value = page
        responses.append(response)
    return mock.Mock(side_effect=responses)


def _page(names: list[str], cut_short: bool, geojson: bool = True) -> dict:
    """One answer from the service, which may say it has more to give."""
    page: dict = {
        "type": "FeatureCollection",
        "features": [{"properties": {"LAD21NM": name}} for name in names],
    }
    if cut_short and geojson:
        page["properties"] = {"exceededTransferLimit": True}
    elif cut_short:
        page["exceededTransferLimit"] = True
    return page


@pytest.mark.parametrize("geojson", [True, False])
def test_load_geodata_fetches_every_page_of_a_large_layer(geojson):
    """A layer cut short by the service is asked for page by page."""
    pages = [
        _page(["Adur", "Barnet"], True, geojson),
        _page(["Cardiff", "Derby"], True, geojson),
        _page(["Exeter"], False),
    ]
    with mock.patch("uk_open_data.geo.api.requests.get", _paged(pages)) as get:
        result = load_geodata(geography_type="LAD", LAD21NM=["Adur", "Exeter"])

    names = [feature["properties"]["LAD21NM"] for feature in result["features"]]
    assert names == ["Adur", "Barnet", "Cardiff", "Derby", "Exeter"]
    assert result["type"] == "FeatureCollection"
    # The whole collection no longer says it was cut short.
    assert "exceededTransferLimit" not in result
    assert "exceededTransferLimit" not in result.get("properties", {})
    asked = [call.kwargs["params"] for call in get.call_args_list]
    assert [params.get("resultOffset") for params in asked] == [None, 2, 4]
    assert all(params["where"] == asked[0]["where"] for params in asked)


def test_load_geodata_stops_when_a_cut_page_is_empty():
    """A service that says there is more but gives nothing ends the paging."""
    pages = [_page(["Adur"], True), _page([], True)]
    with mock.patch("uk_open_data.geo.api.requests.get", _paged(pages)) as get:
        result = load_geodata(geography_type="LAD")

    assert len(result["features"]) == 1
    assert get.call_count == 2


def test_load_geodata_gives_nothing_when_a_later_page_fails(caplog):
    """A part of a layer is never returned as if it were the whole."""
    first = mock.MagicMock()
    first.json.return_value = _page(["Adur", "Barnet"], True)
    get = mock.Mock(
        side_effect=[first, requests.exceptions.RequestException("Connection error")]
    )
    with mock.patch("uk_open_data.geo.api.requests.get", get):
        result = load_geodata(geography_type="LAD")

    assert result == {"type": "FeatureCollection", "features": []}
    assert "Error querying ArcGIS service" in caplog.text


def test_load_geodata_gives_nothing_when_the_service_repeats_a_page(caplog):
    """A service that ignores the offset is stopped after one more request."""
    response = mock.MagicMock()
    response.json.return_value = _page(["Adur", "Barnet"], True)
    with mock.patch("uk_open_data.geo.api.requests.get", return_value=response) as get:
        result = load_geodata(geography_type="LAD")

    assert result == {"type": "FeatureCollection", "features": []}
    assert get.call_count == 2
    assert "did not stop paging" in caplog.text


def test_load_geodata_gives_nothing_when_the_pages_never_end(caplog):
    """A service that always says there is more is stopped at the page limit."""
    pages = [_page([f"Place {number}"], True) for number in range(5)]
    with (
        mock.patch("uk_open_data.geo.api.MAX_PAGES", 3),
        mock.patch("uk_open_data.geo.api.requests.get", _paged(pages)) as get,
    ):
        result = load_geodata(geography_type="LAD")

    assert result == {"type": "FeatureCollection", "features": []}
    assert get.call_count == 4
    assert "did not stop paging" in caplog.text


@mock.patch("uk_open_data.geo.api.requests.get")
def test_get_field_info(mock_get):
    """Test getting field info."""
    mock_response = mock.MagicMock()
    mock_response.json.return_value = {
        "fields": [
            {"name": "LAD21CD", "type": "esriFieldTypeString", "alias": "LAD Code"},
            {"name": "LAD21NM", "type": "esriFieldTypeString", "alias": "LAD Name"},
        ]
    }
    mock_get.return_value = mock_response

    result = get_field_info(geography_type="LAD")

    assert len(result) == 2
    assert result[0]["name"] == "LAD21CD"
    assert result[1]["name"] == "LAD21NM"


@mock.patch("uk_open_data.geo.api.requests.get")
def test_load_geodata_with_year(mock_get):
    """Test loading geodata with a specific year."""
    mock_response = mock.MagicMock()
    mock_response.json.return_value = GEOJSON_RESPONSE
    mock_get.return_value = mock_response

    result = load_geodata(geography_type="LAD", year="2021", boundary_type="BGC")

    assert result["type"] == "FeatureCollection"
    mock_get.assert_called_once()


@mock.patch("uk_open_data.geo.api.requests.get")
def test_load_geodata_with_year_and_month_fallback(mock_get):
    """Test that month filter is dropped when no exact match found."""
    mock_response = mock.MagicMock()
    mock_response.json.return_value = GEOJSON_RESPONSE
    mock_get.return_value = mock_response

    # Use a real geography type with a year, plus a month that won't match.
    # The code should fall back to searching without the month filter.
    result = load_geodata(
        geography_type="LAD", year="2021", month="JAN", boundary_type="BGC"
    )

    assert result["type"] == "FeatureCollection"


@mock.patch("uk_open_data.geo.api.requests.get")
def test_load_geodata_asks_for_simplified_outlines(mock_get):
    """``simplify_m`` reaches the service in degrees, the units of the answer."""
    mock_response = mock.MagicMock()
    mock_response.json.return_value = GEOJSON_RESPONSE
    mock_get.return_value = mock_response

    load_geodata(geography_type="LAD", boundary_type="BFE", simplify_m=20)

    call_params = mock_get.call_args[1]["params"]
    assert call_params["maxAllowableOffset"] == pytest.approx(0.00018, abs=0.00001)
    assert call_params["outSR"] == 4326


@mock.patch("uk_open_data.geo.api.requests.get")
def test_load_geodata_leaves_outlines_alone_by_default(mock_get):
    mock_response = mock.MagicMock()
    mock_response.json.return_value = GEOJSON_RESPONSE
    mock_get.return_value = mock_response

    load_geodata(geography_type="LAD")

    assert "maxAllowableOffset" not in mock_get.call_args[1]["params"]


@pytest.mark.parametrize("metres", [0, -5])
@mock.patch("uk_open_data.geo.api.requests.get")
def test_load_geodata_refuses_a_simplify_distance_not_above_zero(mock_get, metres):
    with pytest.raises(ValueError, match="simplify_m"):
        load_geodata(geography_type="LAD", simplify_m=metres)

    mock_get.assert_not_called()


@mock.patch("uk_open_data.geo.api.requests.get")
def test_load_geodata_with_numeric_filter(mock_get):
    """Test filter clause with numeric value."""
    mock_response = mock.MagicMock()
    mock_response.json.return_value = GEOJSON_RESPONSE
    mock_get.return_value = mock_response

    load_geodata(geography_type="LAD", OBJECTID=42)

    call_params = mock_get.call_args[1]["params"]
    assert call_params["where"] == "OBJECTID = 42"


@mock.patch("uk_open_data.geo.api.requests.get")
def test_load_geodata_with_list_filter(mock_get):
    """Test filter clause with list value (IN clause)."""
    mock_response = mock.MagicMock()
    mock_response.json.return_value = GEOJSON_RESPONSE
    mock_get.return_value = mock_response

    load_geodata(geography_type="LAD", LAD21NM=["Manchester", "Leeds"])

    call_params = mock_get.call_args[1]["params"]
    assert "IN" in call_params["where"]
    assert "'Manchester'" in call_params["where"]
    assert "'Leeds'" in call_params["where"]


@mock.patch("uk_open_data.geo.api.requests.get")
def test_get_field_info_no_matching_service(mock_get):
    """Test get_field_info returns empty list when no service matches."""
    result = get_field_info(geography_type="NONEXISTENT")

    assert result == []
    mock_get.assert_not_called()


@mock.patch("uk_open_data.geo.api.requests.get")
def test_get_field_info_request_error(mock_get):
    """Test get_field_info returns empty list on request error."""
    mock_get.side_effect = requests.exceptions.RequestException("Connection error")

    result = get_field_info(geography_type="LAD")

    assert result == []


def test_get_available_geography_types():
    """Test that available geography types returns expected structure."""
    types = get_available_geography_types()

    assert len(types) > 0
    assert all("code" in t and "description" in t for t in types)
    codes = [t["code"] for t in types]
    assert "LAD" in codes
    assert "LSOA" in codes


def test_get_available_boundary_types():
    """Test that available boundary types returns expected structure."""
    types = get_available_boundary_types()

    assert len(types) > 0
    assert all("code" in t and "description" in t for t in types)
    codes = [t["code"] for t in types]
    assert "BGC" in codes
    assert "BFC" in codes


def test_get_available_coverage_areas():
    """Test that available coverage areas returns expected structure."""
    types = get_available_coverage_areas()

    assert len(types) > 0
    assert all("code" in t and "description" in t for t in types)
    codes = [t["code"] for t in types]
    assert "UK" in codes
    assert "EW" in codes


@mock.patch("uk_open_data.geo.api.requests.get")
def test_load_geodata_no_year_warns(mock_get, caplog):
    """Test that omitting year logs a warning with the resolved year."""
    mock_response = mock.MagicMock()
    mock_response.json.return_value = GEOJSON_RESPONSE
    mock_get.return_value = mock_response

    import logging

    with caplog.at_level(logging.WARNING, logger="uk_open_data.geo.api"):
        load_geodata(geography_type="LAD")

    assert "no year specified" in caplog.text.lower()


def test_geodata_to_properties_basic():
    """Test extracting normalised properties from GeoJSON."""
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "properties": {
                    "LAD24CD": "E06000001",
                    "LAD24NM": "Hartlepool",
                    "Shape__Area": 123.45,
                }
            },
            {
                "properties": {
                    "LAD24CD": "E08000003",
                    "LAD24NM": "Manchester",
                    "Shape__Area": 678.9,
                }
            },
        ],
    }

    rows = geodata_to_properties(geojson, "LAD", 2024)

    assert len(rows) == 2
    assert rows[0]["geography_code"] == "E06000001"
    assert rows[0]["geography_name"] == "Hartlepool"
    # Original properties are preserved
    assert rows[0]["LAD24CD"] == "E06000001"
    assert rows[0]["Shape__Area"] == 123.45
    assert rows[1]["geography_code"] == "E08000003"


def test_geodata_to_properties_empty():
    """Test with empty FeatureCollection."""
    geojson = {"type": "FeatureCollection", "features": []}

    rows = geodata_to_properties(geojson, "LAD", 2024)

    assert rows == []


def test_geodata_to_properties_with_enum():
    """Test that enum geography types work."""
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {"properties": {"LSOA21CD": "E01000001", "LSOA21NM": "City of London 001A"}}
        ],
    }

    rows = geodata_to_properties(geojson, GeographyType.LSOA, "2021")

    assert rows[0]["geography_code"] == "E01000001"
    assert rows[0]["geography_name"] == "City of London 001A"


def test_geodata_to_properties_wrong_year_warns():
    """Test that mismatched year triggers a warning."""
    geojson = {
        "type": "FeatureCollection",
        "features": [{"properties": {"LAD24CD": "E06000001", "LAD24NM": "Hartlepool"}}],
    }

    import warnings

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        rows = geodata_to_properties(geojson, "LAD", 2021)

    # Wrong year → LAD21CD not found → warning
    assert len(w) == 1
    assert "LAD21CD" in str(w[0].message)
    assert rows[0]["geography_code"] == ""


def test_list_tables_top_level_import():
    """Test that list_tables is importable from the top of the package."""
    from uk_open_data import list_tables

    result = list_tables()
    assert len(result) > 0
