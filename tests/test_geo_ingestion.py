"""Tests for kindtech.geo._ingestion parsing helpers."""

import pytest

from kindtech.geo._ingestion import (
    _normalise_month,
    _normalise_resolution,
    _normalise_year,
    _parse_long_form,
    _parse_service,
    _parse_short_form,
    ingest_arcgis_services,
)

# -- _normalise_year ---------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2021", 2021),
        ("21", 2021),
        ("99", 1999),
        ("30", 2030),
        ("31", 1931),
        ("00", 2000),
    ],
)
def test_normalise_year(raw: str, expected: int) -> None:
    assert _normalise_year(raw) == expected


# -- _normalise_resolution ---------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("BFC", "BFC"),
        ("FCB", "BFC"),
        ("FEB", "BFE"),
        ("GCB", "BGC"),
        ("SGCB", "BSC"),
        ("UGCB", "BUC"),
        ("NC", "NC"),
        ("bfc", "BFC"),
        ("fcb", "BFC"),
    ],
)
def test_normalise_resolution(raw: str, expected: str) -> None:
    assert _normalise_resolution(raw) == expected


# -- _normalise_month --------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", ""),
        ("DEC", "DEC"),
        ("December", "DEC"),
        ("JANUARY", "JAN"),
    ],
)
def test_normalise_month(raw: str, expected: str) -> None:
    assert _normalise_month(raw) == expected


# -- _parse_short_form -------------------------------------------------------


def test_parse_short_form_basic() -> None:
    result = _parse_short_form("LAD_DEC_2021_UK_BFC")
    assert result == {
        "arcgis_id": "LAD_DEC_2021_UK_BFC",
        "geography": "LAD",
        "year": "2021",
        "month": "DEC",
        "region": "UK",
        "resolution": "BFC",
    }


def test_parse_short_form_no_month() -> None:
    result = _parse_short_form("LSOA_2021_EW_BSC")
    assert result is not None
    assert result["geography"] == "LSOA"
    assert result["month"] == ""


def test_parse_short_form_two_digit_year() -> None:
    result = _parse_short_form("WD_MAY_21_EN_BFC")
    assert result is not None
    assert result["year"] == "2021"


def test_parse_short_form_no_match() -> None:
    assert _parse_short_form("not_a_service_name") is None


# -- _parse_long_form --------------------------------------------------------


def test_parse_long_form_basic() -> None:
    name = "Local_Authority_District_December_2021_UK_BFC"
    result = _parse_long_form(name)
    assert result is not None
    assert result["geography"] == "LAD"
    assert result["year"] == "2021"
    assert result["region"] == "UK"
    assert result["resolution"] == "BFC"


def test_parse_long_form_legacy_resolution() -> None:
    name = "Counties_and_Unitary_Authorit_2020_UK_FCB"
    result = _parse_long_form(name)
    assert result is not None
    assert result["resolution"] == "BFC"


def test_parse_long_form_buasd_before_bua() -> None:
    """BUASD prefix must match before BUA (insertion-order dependency)."""
    buasd = "Built_up_Area_Sub_2021_EW_BFC"
    bua = "Built_up_Area_2021_EW_BFC"
    r_buasd = _parse_long_form(buasd)
    r_bua = _parse_long_form(bua)
    assert r_buasd is not None and r_buasd["geography"] == "BUASD"
    assert r_bua is not None and r_bua["geography"] == "BUA"


def test_parse_long_form_no_match() -> None:
    assert _parse_long_form("Unknown_Geo_2021_UK_BFC") is None


def test_parse_long_form_missing_fields() -> None:
    """If year/region/resolution are missing, return None."""
    assert _parse_long_form("Local_Authority_District_only") is None


# -- _parse_service -----------------------------------------------------------


def test_parse_service_short_form() -> None:
    result = _parse_service("LAD_DEC_2021_UK_BFC")
    assert result is not None
    assert result["geography"] == "LAD"


def test_parse_service_long_form() -> None:
    result = _parse_service("Local_Authority_District_December_2021_UK_BFC")
    assert result is not None
    assert result["geography"] == "LAD"


def test_parse_service_unparseable() -> None:
    assert _parse_service("random_string") is None


# -- ingest_arcgis_services guard --------------------------------------------


def test_ingest_raises_on_empty_catalog(tmp_path, monkeypatch) -> None:
    """ingest_arcgis_services raises when the API returns no services."""
    monkeypatch.setattr(
        "kindtech.geo._ingestion._fetch_services",
        lambda base_url: [],
    )
    with pytest.raises(RuntimeError, match="No services parsed"):
        ingest_arcgis_services(
            output_path=tmp_path / "empty.csv",
        )
