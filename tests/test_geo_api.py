"""
Unit tests for the KindTech Geo API.

These tests focus on how users interact with the public API methods.
External web requests are mocked to ensure tests are isolated and repeatable.
The catalog (CSV-based) is not mocked — it loads real service metadata.
"""

import unittest.mock as mock

import requests

from kindtech.geo import (
    BoundaryType,
    CoverageArea,
    GeographyType,
    geodata_to_properties,
    get_available_boundary_types,
    get_available_coverage_areas,
    get_available_geography_types,
    get_field_info,
    load_geodata,
)

GEOJSON_RESPONSE = {
    "type": "FeatureCollection",
    "features": [{"properties": {"LAD21NM": "Manchester"}}],
}


@mock.patch("kindtech.geo.api.requests.get")
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


@mock.patch("kindtech.geo.api.requests.get")
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


@mock.patch("kindtech.geo.api.requests.get")
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


@mock.patch("kindtech.geo.api.requests.get")
def test_load_geodata_with_request_error(mock_get):
    """Test loading geodata when request raises an exception."""
    mock_get.side_effect = requests.exceptions.RequestException("Connection error")

    result = load_geodata(geography_type="LAD")

    assert result["type"] == "FeatureCollection"
    assert len(result["features"]) == 0


@mock.patch("kindtech.geo.api.requests.get")
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


@mock.patch("kindtech.geo.api.requests.get")
def test_load_geodata_with_year(mock_get):
    """Test loading geodata with a specific year."""
    mock_response = mock.MagicMock()
    mock_response.json.return_value = GEOJSON_RESPONSE
    mock_get.return_value = mock_response

    result = load_geodata(geography_type="LAD", year="2021", boundary_type="BGC")

    assert result["type"] == "FeatureCollection"
    mock_get.assert_called_once()


@mock.patch("kindtech.geo.api.requests.get")
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


@mock.patch("kindtech.geo.api.requests.get")
def test_load_geodata_with_numeric_filter(mock_get):
    """Test filter clause with numeric value."""
    mock_response = mock.MagicMock()
    mock_response.json.return_value = GEOJSON_RESPONSE
    mock_get.return_value = mock_response

    load_geodata(geography_type="LAD", OBJECTID=42)

    call_params = mock_get.call_args[1]["params"]
    assert call_params["where"] == "OBJECTID = 42"


@mock.patch("kindtech.geo.api.requests.get")
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


@mock.patch("kindtech.geo.api.requests.get")
def test_get_field_info_no_matching_service(mock_get):
    """Test get_field_info returns empty list when no service matches."""
    result = get_field_info(geography_type="NONEXISTENT")

    assert result == []
    mock_get.assert_not_called()


@mock.patch("kindtech.geo.api.requests.get")
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
