"""
Unit tests for the KindTech Postcodes API.

External web requests to postcodes.io are mocked so tests are isolated and
repeatable.
"""

import unittest.mock as mock

import pandas as pd
import pytest

from kindtech.postcodes import (
    lookup_outcodes,
    lookup_postcodes,
    outcode_to_geography,
    postcodes_to_geography,
)


def _codes(**overrides):
    """A representative postcodes.io ``codes`` dict."""
    base = {
        "admin_district": "E09000023",
        "admin_ward": "E05013727",
        "lsoa21": "E01034394",
        "msoa21": "E02007008",
        "oa21": "E00182613",
        "icb": "E54000030",
        "ttwa": "E30000234",
    }
    base.update(overrides)
    return base


def _bulk_result(query, *, lsoa="E01034394", district="Lewisham"):
    """One entry of a bulk /postcodes response."""
    return {
        "query": query,
        "result": {
            "postcode": query,
            "lsoa": "Lewisham 040C",
            "msoa": "Lewisham 040",
            "admin_district": district,
            "latitude": 51.45,
            "longitude": -0.0,
            "codes": _codes(lsoa21=lsoa),
        },
    }


def _mock_post(payload):
    """Build a mock response object for a bulk POST."""
    resp = mock.MagicMock()
    resp.status_code = 200
    resp.raise_for_status = mock.MagicMock()
    resp.json.return_value = payload
    return resp


@mock.patch("kindtech.postcodes.api.requests.post")
def test_lookup_postcodes_basic(mock_post):
    mock_post.return_value = _mock_post(
        {"result": [_bulk_result("SE13 7HX"), _bulk_result("M1 1AE")]}
    )

    df = lookup_postcodes(["SE13 7HX", "M1 1AE"])

    assert isinstance(df, pd.DataFrame)
    assert len(df) == 2
    assert list(df["postcode"]) == ["SE13 7HX", "M1 1AE"]
    assert df.loc[0, "lsoa_code"] == "E01034394"
    assert df.loc[0, "lad_code"] == "E09000023"
    assert bool(df["valid"].all())
    mock_post.assert_called_once()


@mock.patch("kindtech.postcodes.api.requests.post")
def test_lookup_postcodes_single_string(mock_post):
    mock_post.return_value = _mock_post({"result": [_bulk_result("SE13 7HX")]})

    df = lookup_postcodes("SE13 7HX")

    assert len(df) == 1
    # A single string must be sent as a one-element list.
    sent = mock_post.call_args.kwargs["json"]["postcodes"]
    assert sent == ["SE13 7HX"]


@mock.patch("kindtech.postcodes.api.requests.post")
def test_invalid_postcode_flagged_not_dropped(mock_post):
    mock_post.return_value = _mock_post(
        {"result": [_bulk_result("SE13 7HX"), {"query": "NOPE", "result": None}]}
    )

    df = lookup_postcodes(["SE13 7HX", "NOPE"])

    assert len(df) == 2  # invalid row preserved, not dropped
    invalid = df[df["postcode"] == "NOPE"].iloc[0]
    assert not bool(invalid["valid"])
    assert pd.isna(invalid["lsoa_code"])


@mock.patch("kindtech.postcodes.api.requests.post")
def test_bulk_batched_over_100(mock_post):
    # 250 postcodes -> 3 batches (100, 100, 50).
    def side_effect(url, json, timeout):
        return _mock_post({"result": [_bulk_result(p) for p in json["postcodes"]]})

    mock_post.side_effect = side_effect
    postcodes = [f"AA{i}" for i in range(250)]

    df = lookup_postcodes(postcodes)

    assert len(df) == 250
    assert mock_post.call_count == 3
    sizes = [len(c.kwargs["json"]["postcodes"]) for c in mock_post.call_args_list]
    assert sizes == [100, 100, 50]


@mock.patch("kindtech.postcodes.api.requests.post")
def test_postcodes_to_geography_lsoa(mock_post):
    mock_post.return_value = _mock_post(
        {"result": [_bulk_result("SE13 7HX", lsoa="E01034394")]}
    )

    df = postcodes_to_geography(["SE13 7HX"], "LSOA")

    assert list(df.columns) == ["postcode", "geography_code", "geography_name"]
    assert df.loc[0, "geography_code"] == "E01034394"
    assert df.loc[0, "geography_name"] == "Lewisham 040C"


@mock.patch("kindtech.postcodes.api.requests.post")
def test_postcodes_to_geography_lad(mock_post):
    mock_post.return_value = _mock_post({"result": [_bulk_result("SE13 7HX")]})

    df = postcodes_to_geography("SE13 7HX", "LAD")

    assert df.loc[0, "geography_code"] == "E09000023"
    assert df.loc[0, "geography_name"] == "Lewisham"


def test_postcodes_to_geography_rejects_unsupported_level():
    with pytest.raises(ValueError, match="Unsupported geography_type"):
        postcodes_to_geography(["SE13 7HX"], "CTRY")


@mock.patch("kindtech.postcodes.api.requests.get")
def test_lookup_outcodes_one_to_many(mock_get):
    resp = mock.MagicMock()
    resp.status_code = 200
    resp.raise_for_status = mock.MagicMock()
    resp.json.return_value = {
        "result": {
            "outcode": "SE13",
            "admin_district": ["Greenwich", "Lewisham"],
            "latitude": 51.46,
            "longitude": -0.01,
        }
    }
    mock_get.return_value = resp

    df = lookup_outcodes("SE13")

    assert df.loc[0, "outcode"] == "SE13"
    assert df.loc[0, "admin_districts"] == "Greenwich, Lewisham"
    assert bool(df.loc[0, "valid"])


@mock.patch("kindtech.postcodes.api.requests.get")
def test_lookup_outcodes_invalid(mock_get):
    resp = mock.MagicMock()
    resp.status_code = 404
    mock_get.return_value = resp

    df = lookup_outcodes("ZZ99")

    assert not bool(df.loc[0, "valid"])
    assert df.loc[0, "admin_districts"] is None


@mock.patch("kindtech.postcodes.api.requests.get")
def test_outcode_to_geography_centroid(mock_get):
    centroid_resp = mock.MagicMock()
    centroid_resp.status_code = 200
    centroid_resp.raise_for_status = mock.MagicMock()
    centroid_resp.json.return_value = {
        "result": {"outcode": "SE13", "latitude": 51.46, "longitude": -0.01}
    }
    nearest_resp = mock.MagicMock()
    nearest_resp.status_code = 200
    nearest_resp.raise_for_status = mock.MagicMock()
    nearest_resp.json.return_value = {
        "result": [
            {
                "postcode": "SE13 6BY",
                "lsoa": "Lewisham 041B",
                "admin_district": "Lewisham",
                "codes": _codes(lsoa21="E01033327"),
            }
        ]
    }
    # First GET = outcode centroid, second GET = reverse geocode.
    mock_get.side_effect = [centroid_resp, nearest_resp]

    df = outcode_to_geography("SE13", "LSOA")

    assert df.loc[0, "outcode"] == "SE13"
    assert df.loc[0, "geography_code"] == "E01033327"
    assert df.loc[0, "geography_name"] == "Lewisham 041B"
