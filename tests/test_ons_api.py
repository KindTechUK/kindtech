"""
Unit tests for the KindTech ONS API.

External web requests are mocked to ensure tests are isolated and repeatable.
The catalog (CSV-based) is not mocked — it loads real dataset metadata.
"""

import unittest.mock as mock

import pandas as pd
import pytest
import requests

from kindtech.ons import list_tables, load_ons

CSV_RESPONSE = "DATE,GEOGRAPHY_NAME,OBS_VALUE\n2023,England,12345\n2023,Wales,6789\n"


@mock.patch("kindtech.ons.api.requests.get")
def test_load_ons_basic(mock_get):
    """Test loading ONS data returns a DataFrame."""
    mock_response = mock.MagicMock()
    mock_response.text = CSV_RESPONSE
    mock_response.raise_for_status = mock.MagicMock()
    mock_get.return_value = mock_response

    result = load_ons("NM_1_1")

    assert isinstance(result, pd.DataFrame)
    assert len(result) == 2
    assert "obs_value" in result.columns
    mock_get.assert_called_once()
    call_url = mock_get.call_args[0][0]
    assert "NM_1_1" in call_url
    assert ".data.csv" in call_url


@mock.patch("kindtech.ons.api.requests.get")
def test_load_ons_with_params(mock_get):
    """Test that query parameters are passed to the URL."""
    mock_response = mock.MagicMock()
    mock_response.text = CSV_RESPONSE
    mock_response.raise_for_status = mock.MagicMock()
    mock_get.return_value = mock_response

    load_ons("NM_1_1", geography="TYPE480", time="latest")

    call_url = mock_get.call_args[0][0]
    assert "geography=TYPE480" in call_url
    assert "time=latest" in call_url


@mock.patch("kindtech.ons.api.requests.get")
def test_load_ons_list_params(mock_get):
    """Test that list parameters are joined with commas."""
    mock_response = mock.MagicMock()
    mock_response.text = CSV_RESPONSE
    mock_response.raise_for_status = mock.MagicMock()
    mock_get.return_value = mock_response

    load_ons("NM_1_1", measures=[20100, 20201])

    call_url = mock_get.call_args[0][0]
    assert "measures=20100%2C20201" in call_url


@mock.patch("kindtech.ons.api.requests.get")
def test_load_ons_html_error(mock_get):
    """Test that an HTML error page raises ValueError."""
    mock_response = mock.MagicMock()
    mock_response.text = "<!DOCTYPE html><html><body>Error</body></html>"
    mock_response.raise_for_status = mock.MagicMock()
    mock_get.return_value = mock_response

    with pytest.raises(ValueError, match="does not exist"):
        load_ons("NM_INVALID_999")


@mock.patch("kindtech.ons.api.requests.get")
def test_load_ons_request_error(mock_get):
    """Test that a request error propagates."""
    mock_get.side_effect = requests.exceptions.RequestException("Connection error")

    with pytest.raises(requests.exceptions.RequestException):
        load_ons("NM_1_1")


def test_list_tables_returns_dataframe():
    """Test that list_tables returns a DataFrame with expected columns."""
    result = list_tables()

    assert isinstance(result, pd.DataFrame)
    assert len(result) > 0
    assert "id" in result.columns
    assert "name" in result.columns


def test_list_tables_filter_by_name():
    """Test filtering tables by name substring."""
    result = list_tables(name="population")

    assert isinstance(result, pd.DataFrame)
    assert len(result) > 0
    assert all("population" in row.lower() for row in result["name"])


@mock.patch("kindtech.ons.api.requests.get")
def test_load_ons_truncation_warning(mock_get, caplog):
    """Test that a warning is logged when exactly 25,000 rows are returned."""
    # Build a CSV with exactly 25,000 data rows using a fixed-width
    # row to avoid slow f-string interpolation for each row.
    row = "1,v\n"
    rows = row * 25000
    header = "A,B\n"
    mock_response = mock.MagicMock()
    mock_response.text = header + rows
    mock_response.raise_for_status = mock.MagicMock()
    mock_get.return_value = mock_response

    import logging

    with caplog.at_level(logging.WARNING, logger="kindtech.ons.api"):
        result = load_ons("NM_1_1")

    assert len(result) == 25000
    assert "truncated" in caplog.text.lower()


@mock.patch("kindtech.ons.api.requests.get")
def test_load_ons_csv_parse_error(mock_get):
    """Test that unparseable CSV raises ValueError."""
    mock_response = mock.MagicMock()
    # Empty text triggers an EmptyDataError from pandas, which gets
    # wrapped as a ValueError by load_ons.
    mock_response.text = ""
    mock_response.raise_for_status = mock.MagicMock()
    mock_get.return_value = mock_response

    with pytest.raises(ValueError, match="Failed to parse"):
        load_ons("NM_1_1")


def test_list_tables_filter_by_source():
    """Test filtering tables by source name."""
    result = list_tables(source="nomis")

    assert isinstance(result, pd.DataFrame)


@mock.patch("kindtech.ons.api.requests.get")
def test_load_ons_normalize_false(mock_get):
    """Test that normalize=False preserves original UPPER_CASE columns."""
    mock_response = mock.MagicMock()
    mock_response.text = CSV_RESPONSE
    mock_response.raise_for_status = mock.MagicMock()
    mock_get.return_value = mock_response

    result = load_ons("NM_1_1", normalize=False)

    assert "OBS_VALUE" in result.columns
    assert "GEOGRAPHY_NAME" in result.columns


@mock.patch("kindtech.ons.api.requests.get")
def test_load_ons_normalize_default(mock_get):
    """Test that columns are lowercased by default."""
    mock_response = mock.MagicMock()
    mock_response.text = CSV_RESPONSE
    mock_response.raise_for_status = mock.MagicMock()
    mock_get.return_value = mock_response

    result = load_ons("NM_1_1")

    assert "obs_value" in result.columns
    assert "geography_name" in result.columns
    assert "OBS_VALUE" not in result.columns


def test_is_valid_dataset():
    """Test the is_valid_dataset catalog function."""
    from kindtech.ons._catalog import is_valid_dataset

    assert is_valid_dataset("NM_1_1") is True
    assert is_valid_dataset("TOTALLY_FAKE_999") is False
