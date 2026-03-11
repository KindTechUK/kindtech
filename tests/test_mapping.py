"""
Unit tests for the geography crosswalk module.
"""

import unittest.mock as mock

import pytest

from kindtech._mapping import (
    geo_code_field,
    geo_name_field,
    list_geography_mappings,
    resolve_nomis_geography,
)


class TestResolveNomisGeography:
    """Tests for resolve_nomis_geography()."""

    def test_lad_latest(self):
        assert resolve_nomis_geography("LAD") == "TYPE424"

    def test_lad_2020(self):
        assert resolve_nomis_geography("LAD", year=2020) == "TYPE434"

    def test_lad_2021(self):
        assert resolve_nomis_geography("LAD", year=2021) == "TYPE431"

    def test_lad_2015(self):
        assert resolve_nomis_geography("LAD", year=2015) == "TYPE446"

    def test_lad_pre_2015(self):
        assert resolve_nomis_geography("LAD", year=2010) == "TYPE464"

    def test_lsoa_2021(self):
        assert resolve_nomis_geography("LSOA", year=2021) == "TYPE151"

    def test_lsoa_pre_2021(self):
        assert resolve_nomis_geography("LSOA", year=2019) == "TYPE304"

    def test_msoa_latest(self):
        assert resolve_nomis_geography("MSOA") == "TYPE152"

    def test_rgn(self):
        assert resolve_nomis_geography("RGN") == "TYPE480"

    def test_ctry(self):
        assert resolve_nomis_geography("CTRY") == "TYPE499"

    def test_case_insensitive(self):
        assert resolve_nomis_geography("lad") == "TYPE424"

    def test_unknown_type_raises(self):
        with pytest.raises(ValueError, match="No NOMIS mapping"):
            resolve_nomis_geography("UNKNOWN")

    def test_year_out_of_range_raises(self):
        """WD only has TYPE182 for 2025+."""
        with pytest.raises(ValueError, match="No NOMIS TYPE code"):
            resolve_nomis_geography("WD", year=2020)


class TestGeoFieldNames:
    """Tests for geo_code_field() and geo_name_field()."""

    def test_lad_2024_code(self):
        assert geo_code_field("LAD", 2024) == "LAD24CD"

    def test_lad_2024_name(self):
        assert geo_name_field("LAD", 2024) == "LAD24NM"

    def test_msoa_2021_code(self):
        assert geo_code_field("MSOA", 2021) == "MSOA21CD"

    def test_msoa_2021_name(self):
        assert geo_name_field("MSOA", 2021) == "MSOA21NM"

    def test_year_2000(self):
        assert geo_code_field("LAD", 2000) == "LAD00CD"

    def test_case_normalised(self):
        assert geo_code_field("lad", 2024) == "LAD24CD"


class TestListGeographyMappings:
    """Tests for list_geography_mappings()."""

    def test_returns_list_of_dicts(self):
        result = list_geography_mappings()
        assert isinstance(result, list)
        assert len(result) > 0
        assert all(isinstance(r, dict) for r in result)

    def test_dict_keys(self):
        result = list_geography_mappings()
        expected_keys = {
            "geography_type",
            "year_from",
            "year_to",
            "nomis_type",
        }
        assert set(result[0].keys()) == expected_keys

    def test_includes_lad(self):
        result = list_geography_mappings()
        lad_entries = [r for r in result if r["geography_type"] == "LAD"]
        assert len(lad_entries) >= 4


class TestLoadOnsGeographyType:
    """Tests for load_ons() with geography_type parameter."""

    @mock.patch("kindtech.ons.api.requests.get")
    def test_geography_type_resolves(self, mock_get):
        """geography_type='LAD' should resolve to TYPE424."""
        mock_response = mock.MagicMock()
        mock_response.text = "GEOGRAPHY_CODE,OBS_VALUE\nE06000001,100\n"
        mock_response.raise_for_status = mock.MagicMock()
        mock_get.return_value = mock_response

        from kindtech.ons import load_ons

        load_ons("NM_1_1", geography_type="LAD", time="latest")

        call_url = mock_get.call_args[0][0]
        assert "geography=TYPE424" in call_url

    @mock.patch("kindtech.ons.api.requests.get")
    def test_geography_type_with_year(self, mock_get):
        """geography_type='LAD' with time='2020' should use TYPE434."""
        mock_response = mock.MagicMock()
        mock_response.text = "GEOGRAPHY_CODE,OBS_VALUE\nE06000001,100\n"
        mock_response.raise_for_status = mock.MagicMock()
        mock_get.return_value = mock_response

        from kindtech.ons import load_ons

        load_ons("NM_1_1", geography_type="LAD", time="2020")

        call_url = mock_get.call_args[0][0]
        assert "geography=TYPE434" in call_url

    def test_both_geography_params_raises(self):
        """Cannot use geography_type and geography together."""
        from kindtech.ons import load_ons

        with pytest.raises(ValueError, match="Cannot specify both"):
            load_ons(
                "NM_1_1",
                geography_type="LAD",
                geography="TYPE480",
            )
