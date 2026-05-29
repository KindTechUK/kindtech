"""
Unit tests for the KindTech IMD API.

The composite dataset fetch is mocked so tests are isolated and repeatable.
"""

import unittest.mock as mock

import pandas as pd
import pytest

from kindtech.imd import api as imd_api
from kindtech.imd import load_imd

# Minimal composite CSV: the real columns, two rows per nation.
_CSV = (
    "nation,lsoa,overall_local_score,income_score,employment_score,"
    "UK_IMD_E_score,original_decile,E_expanded_decile,UK_IMD_E_rank,"
    "UK_IMD_E_pop_decile,UK_IMD_E_pop_quintile\n"
    "E,E01021988,92.7,56.9,53.4,92.7,1,1.0,1.0,1,1\n"
    "W,W01000240,86.6,61.0,43.0,90.3,1,1.0,2.0,1,1\n"
    "S,S01007101,70.0,40.0,30.0,71.2,2,2.0,5000.0,4,2\n"
    "N,N00000001,60.0,35.0,25.0,61.0,3,3.0,9000.0,7,4\n"
)


@pytest.fixture(autouse=True)
def _clear_cache():
    """The connector caches the parsed dataset per URL — reset between tests."""
    imd_api._CACHE.clear()
    yield
    imd_api._CACHE.clear()


def _mock_get():
    resp = mock.MagicMock()
    resp.raise_for_status = mock.MagicMock()
    resp.text = _CSV
    return resp


@mock.patch("kindtech.imd.api.requests.get")
def test_load_imd_uk_all_nations(mock_get):
    mock_get.return_value = _mock_get()

    df = load_imd()

    assert isinstance(df, pd.DataFrame)
    assert len(df) == 4
    assert set(df["nation"]) == {"E", "W", "S", "N"}
    # Columns are renamed to KindTech names.
    assert "geography_code" in df.columns
    assert "imd_decile" in df.columns
    assert "UK_IMD_E_rank" not in df.columns


@mock.patch("kindtech.imd.api.requests.get")
def test_geography_code_and_rank_mapping(mock_get):
    mock_get.return_value = _mock_get()

    df = load_imd().sort_values("imd_rank").reset_index(drop=True)

    # UK-wide rank interleaves nations: England rank 1, Wales rank 2.
    assert df.loc[0, "geography_code"] == "E01021988"
    assert df.loc[1, "geography_code"] == "W01000240"
    assert df.loc[1, "nation"] == "W"


@mock.patch("kindtech.imd.api.requests.get")
def test_nation_filter_by_name_and_code(mock_get):
    mock_get.return_value = _mock_get()

    by_name = load_imd(nation="England")
    by_code = load_imd(nation="E")

    assert list(by_name["geography_code"]) == ["E01021988"]
    assert list(by_code["geography_code"]) == ["E01021988"]


@mock.patch("kindtech.imd.api.requests.get")
def test_nation_filter_scotland_uses_data_zones(mock_get):
    mock_get.return_value = _mock_get()

    scotland = load_imd(nation="Scotland")

    assert len(scotland) == 1
    assert scotland.iloc[0]["geography_code"].startswith("S")


def test_unknown_nation_raises():
    with pytest.raises(ValueError, match="Unknown nation"):
        load_imd(nation="Narnia")


@mock.patch("kindtech.imd.api.requests.get")
def test_dataset_cached_across_calls(mock_get):
    mock_get.return_value = _mock_get()

    load_imd()
    load_imd(nation="Wales")
    load_imd(nation="S")

    # Fetched once despite three calls — the parsed frame is cached.
    mock_get.assert_called_once()
