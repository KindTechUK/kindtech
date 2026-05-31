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
    """The connector caches fetched data per URL — reset between tests."""
    imd_api._CACHE.clear()
    imd_api._BYTES.clear()
    yield
    imd_api._CACHE.clear()
    imd_api._BYTES.clear()


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


# Raw source rows (as the readers return them) for the three official indices.
# Two rows each, most-deprived first, so the derived decile is checkable.
_WALES_ROWS = [
    {
        "LSOA code": "W01000001",
        "LSOA name (Eng)": "Area 1",
        "WIMD 2019": 1,
        "Income": 5,
        "Employment": 6,
        "Health": 7,
        "Education": 8,
        "Access to Services": 9,
        "Housing": 10,
        "Community Safety": 11,
        "Physical Environment": 12,
    },
    {
        "LSOA code": "W01000002",
        "LSOA name (Eng)": "Area 2",
        "WIMD 2019": 2,
        "Income": 1,
        "Employment": 2,
        "Health": 3,
        "Education": 4,
        "Access to Services": 5,
        "Housing": 6,
        "Community Safety": 7,
        "Physical Environment": 8,
    },
]
_SCOTLAND_ROWS = [
    {
        "Data_Zone": "S01006506",
        "SIMD2020v2_Rank": 1,
        "SIMD2020v2_Income_Domain_Rank": 3,
        "SIMD2020_Employment_Domain_Rank": 4,
        "SIMD2020_Health_Domain_Rank": 5,
        "SIMD2020_Education_Domain_Rank": 6,
        "SIMD2020_Access_Domain_Rank": 7,
        "SIMD2020_Crime_Domain_Rank": 8,
        "SIMD2020_Housing_Domain_Rank": 9,
        "Total_population": 894,
    },
    {
        "Data_Zone": "S01006507",
        "SIMD2020v2_Rank": 2,
        "SIMD2020v2_Income_Domain_Rank": 30,
        "SIMD2020_Employment_Domain_Rank": 40,
        "SIMD2020_Health_Domain_Rank": 50,
        "SIMD2020_Education_Domain_Rank": 60,
        "SIMD2020_Access_Domain_Rank": 70,
        "SIMD2020_Crime_Domain_Rank": 80,
        "SIMD2020_Housing_Domain_Rank": 90,
        "Total_population": 600,
    },
]
_NI_ROWS = [
    {
        "SOA2001": "95AA01S1",
        "SOA2001name": "Aldergrove_1",
        "MDM_rank": 1,
        "D1_Income_rank": 2,
        "D2_Empl_rank": 3,
        "D3_Health_rank": 4,
        "P4_Education_rank": 5,
        "P5_Access_rank": 6,
        "D6_LivEnv_rank": 7,
        "D7_CD_rank": 8,
    },
    {
        "SOA2001": "95AA01S2",
        "SOA2001name": "Aldergrove_2",
        "MDM_rank": 2,
        "D1_Income_rank": 20,
        "D2_Empl_rank": 30,
        "D3_Health_rank": 40,
        "P4_Education_rank": 50,
        "P5_Access_rank": 60,
        "D6_LivEnv_rank": 70,
        "D7_CD_rank": 80,
    },
]


def test_decile_from_rank_boundaries():
    # Within-nation decile, 1 = most deprived 10%, over Scotland's 6976 zones.
    assert imd_api._decile_from_rank(1, 6976) == 1
    assert imd_api._decile_from_rank(698, 6976) == 1
    assert imd_api._decile_from_rank(699, 6976) == 2
    assert imd_api._decile_from_rank(6976, 6976) == 10


@mock.patch("kindtech.imd.api._national_source_rows")
def test_wales_official_domains(mock_rows):
    mock_rows.return_value = _WALES_ROWS

    by_name = load_imd(nation="Wales")
    by_code = load_imd(nation="W")

    assert list(by_name["geography_code"]) == list(by_code["geography_code"])
    assert by_name.loc[0, "geography_code"] == "W01000001"
    assert by_name.loc[0, "nation"] == "W"
    assert by_name.loc[0, "imd_rank"] == 1
    assert by_name.loc[0, "imd_decile"] == 1  # rank 1 (most deprived) -> decile 1
    # Wales-specific domains surface as <domain>_rank.
    for domain in ["community_safety", "physical_environment", "housing", "access"]:
        assert f"{domain}_rank" in by_name.columns
    # Within-nation only — no UK composite columns.
    assert "nation_decile" not in by_name.columns


@mock.patch("kindtech.imd.api._national_source_rows")
def test_scotland_official_domains_with_population(mock_rows):
    mock_rows.return_value = _SCOTLAND_ROWS

    scotland = load_imd(nation="Scotland")

    assert scotland.loc[0, "geography_code"] == "S01006506"  # Data Zone
    assert scotland.loc[0, "imd_rank"] == 1
    assert scotland.loc[0, "imd_decile"] == 1
    assert scotland.loc[0, "crime_rank"] == 8
    assert scotland.loc[0, "population"] == 894  # SIMD ships a denominator


@mock.patch("kindtech.imd.api._national_source_rows")
def test_ni_official_domains(mock_rows):
    mock_rows.return_value = _NI_ROWS

    ni = load_imd(nation="Northern Ireland")

    assert ni.loc[0, "geography_code"] == "95AA01S1"  # SOA
    assert ni.loc[0, "geography_name"] == "Aldergrove_1"
    assert ni.loc[0, "imd_decile"] == 1
    # NI-specific domains.
    assert ni.loc[0, "living_environment_rank"] == 7
    assert ni.loc[0, "crime_disorder_rank"] == 8


def test_unknown_nation_raises():
    with pytest.raises(ValueError, match="Unknown nation"):
        load_imd(nation="Narnia")


@mock.patch("kindtech.imd.api.requests.get")
def test_composite_cached_across_calls(mock_get):
    mock_get.return_value = _mock_get()

    load_imd()  # UK composite
    load_imd(nation="UK")

    # Fetched once despite two calls — the parsed composite frame is cached.
    mock_get.assert_called_once()


# --- year=2025 (latest national index) -------------------------------------

_RANK = "Rank (where 1 is most deprived)"
_DEC = "Decile (where 1 is most deprived 10% of LSOAs)"

_ENGLAND_2025_CSV = (
    "LSOA code (2021),LSOA name (2021),"
    "Local Authority District code (2024),Local Authority District name (2024),"
    f"Index of Multiple Deprivation (IMD) Score,"
    f"Index of Multiple Deprivation (IMD) {_RANK},"
    f"Index of Multiple Deprivation (IMD) {_DEC},"
    f"Income Score (rate),Income {_RANK},Income {_DEC},"
    f"Employment Score (rate),Employment {_RANK},Employment {_DEC},"
    f'"Education, Skills and Training Score",'
    f'"Education, Skills and Training {_RANK}",'
    f'"Education, Skills and Training {_DEC}",'
    f"Health Deprivation and Disability Score,"
    f"Health Deprivation and Disability {_RANK},"
    f"Health Deprivation and Disability {_DEC},"
    f"Crime Score,Crime {_RANK},Crime {_DEC},"
    f"Barriers to Housing and Services Score,"
    f"Barriers to Housing and Services {_RANK},"
    f"Barriers to Housing and Services {_DEC},"
    f"Living Environment Score,Living Environment {_RANK},Living Environment {_DEC},"
    "Total population: mid 2022\n"
    "E01000001,City of London 001A,E09000001,City of London,"
    "8.7,26525,8,"  # overall IMD: score, rank, decile
    "0.013,9001,9,"  # income
    "0.02,9002,8,"  # employment
    "0.1,9003,7,"  # education
    "0.2,9004,6,"  # health
    "0.3,9005,5,"  # crime
    "0.4,9006,4,"  # housing
    "0.5,9007,3,"  # living environment
    "1523\n"  # population
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
    assert df.loc[0, "imd_rank"] == 26525
    # All seven domains surfaced as score + rank + decile.
    for domain in [
        "income",
        "employment",
        "education",
        "health",
        "crime",
        "housing",
        "living_environment",
    ]:
        assert f"{domain}_score" in df.columns
        assert f"{domain}_rank" in df.columns
        assert f"{domain}_decile" in df.columns
    # Rank values land in the right columns.
    assert df.loc[0, "income_rank"] == 9001
    assert df.loc[0, "living_environment_rank"] == 9007
    # Population denominator surfaced for per-capita work.
    assert df.loc[0, "population"] == 1523


@mock.patch("kindtech.imd.api.requests.get")
def test_england_defaults_to_2025(mock_get):
    resp = mock.MagicMock()
    resp.raise_for_status = mock.MagicMock()
    resp.text = _ENGLAND_2025_CSV
    mock_get.return_value = resp

    # No year -> England resolves to the latest (2025), with domain columns.
    df = load_imd(nation="England")

    assert "income_decile" in df.columns  # 2025 schema, not the composite
    assert df.loc[0, "geography_code"] == "E01000001"


@mock.patch("kindtech.imd.api.requests.get")
def test_uk_defaults_to_composite(mock_get):
    mock_get.return_value = _mock_get()

    # No year, UK-wide -> composite (no UK 2025 exists).
    df = load_imd()

    assert "nation_decile" in df.columns  # composite schema
    assert len(df) == 4


def test_year_2025_uk_wide_raises():
    with pytest.raises(ValueError, match="composite"):
        load_imd(nation="UK", year=2025)


def test_year_2025_scotland_raises_no_release():
    with pytest.raises(ValueError, match="No 2025 deprivation index"):
        load_imd(nation="Scotland", year=2025)


def test_year_2025_wales_pending():
    with pytest.raises(ValueError, match="WIMD 2025"):
        load_imd(nation="Wales", year=2025)


def test_unknown_year_raises():
    with pytest.raises(ValueError, match="year=2019 or year=2025"):
        load_imd(nation="England", year=2024)


# England IoD 2019: official, on 2011 LSOAs.
_ENGLAND_2019_CSV = (
    "LSOA code (2011),LSOA name (2011),"
    "Local Authority District code (2019),Local Authority District name (2019),"
    f"Index of Multiple Deprivation (IMD) Score,"
    f"Index of Multiple Deprivation (IMD) {_RANK},"
    f"Index of Multiple Deprivation (IMD) {_DEC},"
    f"Income Score (rate),Income {_RANK},Income {_DEC},"
    f"Employment Score (rate),Employment {_RANK},Employment {_DEC},"
    f'"Education, Skills and Training Score",'
    f'"Education, Skills and Training {_RANK}",'
    f'"Education, Skills and Training {_DEC}",'
    f"Health Deprivation and Disability Score,"
    f"Health Deprivation and Disability {_RANK},"
    f"Health Deprivation and Disability {_DEC},"
    f"Crime Score,Crime {_RANK},Crime {_DEC},"
    f"Barriers to Housing and Services Score,"
    f"Barriers to Housing and Services {_RANK},"
    f"Barriers to Housing and Services {_DEC},"
    f"Living Environment Score,Living Environment {_RANK},Living Environment {_DEC},"
    "Total population: mid 2015 (excluding prisoners)\n"
    "E01000001,City of London 001A,E09000001,City of London,"
    "8.7,26525,8,"
    "0.013,9001,9,0.02,9002,8,0.1,9003,7,0.2,9004,6,"
    "0.3,9005,5,0.4,9006,4,0.5,9007,3,"
    "1500\n"
)


@mock.patch("kindtech.imd.api.requests.get")
def test_england_2019_official_on_2011_lsoas(mock_get):
    resp = mock.MagicMock()
    resp.raise_for_status = mock.MagicMock()
    resp.text = _ENGLAND_2019_CSV
    mock_get.return_value = resp

    df = load_imd(nation="England", year=2019)

    assert df.loc[0, "geography_code"] == "E01000001"  # 2011 LSOA
    assert df.loc[0, "nation"] == "E"
    assert df.loc[0, "imd_decile"] == 8
    assert df.loc[0, "income_rank"] == 9001  # domains + ranks present
    assert df.loc[0, "population"] == 1500  # mid-2015 denominator
