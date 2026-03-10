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


def test_get_available_geography_types():
    """Test that available geography types returns expected structure."""
    types = get_available_geography_types()

    assert len(types) > 0
    assert all("code" in t and "description" in t for t in types)
    codes = [t["code"] for t in types]
    assert "LAD" in codes
    assert "LSOA" in codes
