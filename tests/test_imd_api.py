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


# --- year=2025 (latest national index) -------------------------------------

_ENGLAND_2025_CSV = (
    "LSOA code (2021),LSOA name (2021),"
    "Local Authority District code (2024),Local Authority District name (2024),"
    "Index of Multiple Deprivation (IMD) Score,"
    "Index of Multiple Deprivation (IMD) Rank (where 1 is most deprived),"
    "Index of Multiple Deprivation (IMD) Decile "
    "(where 1 is most deprived 10% of LSOAs),"
    "Income Score (rate),"
    "Income Decile (where 1 is most deprived 10% of LSOAs),"
    "Employment Score (rate),"
    "Employment Decile (where 1 is most deprived 10% of LSOAs),"
    '"Education, Skills and Training Score",'
    '"Education, Skills and Training Decile (where 1 is most deprived 10% of LSOAs)",'
    "Health Deprivation and Disability Score,"
    "Health Deprivation and Disability Decile (where 1 is most deprived 10% of LSOAs),"
    "Crime Score,"
    "Crime Decile (where 1 is most deprived 10% of LSOAs),"
    "Barriers to Housing and Services Score,"
    "Barriers to Housing and Services Decile (where 1 is most deprived 10% of LSOAs),"
    "Living Environment Score,"
    "Living Environment Decile (where 1 is most deprived 10% of LSOAs)\n"
    "E01000001,City of London 001A,E09000001,City of London,"
    "8.7,26525,8,0.013,9,0.02,8,0.1,7,0.2,6,0.3,5,0.4,4,0.5,3\n"
)


@mock.patch("kindtech.imd.api.requests.get")
def test_england_2025_on_2021_lsoas_with_domains(mock_get):
    resp = mock.MagicMock()
    resp.raise_for_status = mock.MagicMock()
    resp.text = _ENGLAND_2025_CSV
    mock_get.return_value = resp

    df = load_imd(nation="England", year=2025)

    assert df.loc[0, "geography_code"] == "E01000001"  # 2021 LSOA
    assert df.loc[0, "nation"] == "E"
    assert df.loc[0, "imd_decile"] == 8
    # All seven domains surfaced as score + decile.
    for domain in [
        "income",
        "employment",
        "education",
        "health",
        "crime",
        "housing",
        "living_environment",
    ]:
        assert f"{domain}_decile" in df.columns
        assert f"{domain}_score" in df.columns


def test_year_2025_uk_wide_raises():
    with pytest.raises(ValueError, match="per-nation"):
        load_imd(nation="UK", year=2025)


def test_year_2025_scotland_raises_no_release():
    with pytest.raises(ValueError, match="No 2025 deprivation index"):
        load_imd(nation="Scotland", year=2025)


def test_year_2025_wales_pending():
    with pytest.raises(ValueError, match="WIMD 2025"):
        load_imd(nation="Wales", year=2025)


def test_unknown_year_raises():
    with pytest.raises(ValueError, match="year must be"):
        load_imd(nation="England", year=2024)
