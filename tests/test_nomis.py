#!/usr/bin/env python3
"""
Test script for NOMIS API functionality using modern pytest methodology.
"""

from unittest.mock import patch

import pandas as pd
import pytest
import requests
import responses
from kindtech.ons import load_ons
from kindtech.ons._ingestion import (
    create_nomis_tables_dataset,
    extract_data_source,
    get_overview,
    list_data_sources,
    list_tables,
    save_nomis_tables_dataset,
)


@pytest.fixture
def mock_nomis_tables_response():
    """Mock response for list_tables API call."""
    return {
        "structure": {
            "keyfamilies": {
                "keyfamily": [
                    {"id": "NM_1_1", "name": {"value": "Labour Market Statistics"}},
                    {"id": "NM_2_1", "name": {"value": "Population Estimates"}},
                    {"id": "NM_3_1", "name": {"value": "Economic Activity"}},
                ]
            }
        }
    }


@pytest.fixture
def mock_data_sources_response():
    """Mock response for list_data_sources API call."""
    return {
        "contenttype": {
            "item": [
                {
                    "id": "labour",
                    "name": "Labour Market",
                    "description": "Labour market statistics",
                },
                {
                    "id": "census",
                    "item": [
                        {
                            "id": "census_2011",
                            "name": "Census 2011",
                            "description": "2011 Census data",
                        },
                        {
                            "id": "census_2021",
                            "name": "Census 2021",
                            "description": "2021 Census data",
                        },
                    ],
                },
            ]
        }
    }


@pytest.fixture
def mock_overview_response():
    """Mock response for get_overview API call."""
    return {
        "structure": {
            "keyfamilies": {
                "keyfamily": [
                    {
                        "annotations": {
                            "annotation": [
                                {
                                    "annotationtitle": "contenttype/sources",
                                    "annotationtext": "Office for National Statistics",
                                }
                            ]
                        }
                    }
                ]
            },
            "header": {"sender": {"contact": {"name": "ONS Contact"}}},
        }
    }


@pytest.fixture
def mock_csv_response():
    """Mock CSV response for get_ons_table API call."""
    return """geography_name,obs_value,date
England,5000,2023-01-01
Wales,2000,2023-01-01
Scotland,3000,2023-01-01"""


@pytest.fixture
def sample_tables_df():
    """Sample DataFrame for testing."""
    return pd.DataFrame(
        {
            "id": ["NM_1_1", "NM_2_1", "NM_3_1"],
            "name": [
                "Labour Market Statistics",
                "Population Estimates",
                "Economic Activity",
            ],
        }
    )


class TestListTables:
    """Test suite for list_tables function."""

    @responses.activate
    def test_list_tables_success(self, mock_nomis_tables_response):
        """Test successful list_tables call."""
        responses.add(
            responses.GET,
            "https://www.nomisweb.co.uk/api/v01/dataset/def.sdmx.json",
            json=mock_nomis_tables_response,
            status=200,
        )

        result = list_tables()

        assert isinstance(result, pd.DataFrame)
        assert len(result) == 3
        assert list(result.columns) == ["id", "name"]
        assert result.iloc[0]["id"] == "NM_1_1"
        assert result.iloc[0]["name"] == "Labour Market Statistics"

    @responses.activate
    def test_list_tables_api_error(self):
        """Test list_tables with API error."""
        responses.add(
            responses.GET,
            "https://www.nomisweb.co.uk/api/v01/dataset/def.sdmx.json",
            status=500,
        )

        with pytest.raises(requests.exceptions.HTTPError):
            list_tables()


class TestListDataSources:
    """Test suite for list_data_sources function."""

    @responses.activate
    def test_list_data_sources_success(self, mock_data_sources_response):
        """Test successful list_data_sources call."""
        responses.add(
            responses.GET,
            "https://www.nomisweb.co.uk/api/v01/contenttype/sources.json",
            json=mock_data_sources_response,
            status=200,
        )

        result = list_data_sources()

        assert isinstance(result, pd.DataFrame)
        assert len(result) == 3  # 1 regular + 2 census items
        assert list(result.columns) == [
            "source_name",
            "source_id",
            "source_description",
        ]
        assert "Labour Market" in result["source_name"].values
        assert "Census 2011" in result["source_name"].values

    @responses.activate
    def test_list_data_sources_api_error(self):
        """Test list_data_sources with API error."""
        responses.add(
            responses.GET,
            "https://www.nomisweb.co.uk/api/v01/contenttype/sources.json",
            status=500,
        )

        with pytest.raises(requests.exceptions.HTTPError):
            list_data_sources()


class TestGetOverview:
    """Test suite for get_overview function."""

    @responses.activate
    def test_get_overview_success(self, mock_overview_response):
        """Test successful get_overview call."""
        responses.add(
            responses.GET,
            "https://www.nomisweb.co.uk/api/v01/dataset/NM_1_1/def.sdmx.json",
            json=mock_overview_response,
            status=200,
        )

        result = get_overview("NM_1_1")

        assert isinstance(result, dict)
        assert "structure" in result
        assert "keyfamilies" in result["structure"]

    @responses.activate
    def test_get_overview_invalid_id(self):
        """Test get_overview with invalid dataset ID."""
        responses.add(
            responses.GET,
            "https://www.nomisweb.co.uk/api/v01/dataset/INVALID_ID/def.sdmx.json",
            status=404,
        )

        with pytest.raises(requests.exceptions.HTTPError):
            get_overview("INVALID_ID")


class TestLoadOns:
    """Test suite for load_ons function."""

    @responses.activate
    def test_load_ons_success(self, mock_csv_response):
        """Test successful get_ons_table call."""
        responses.add(
            responses.GET,
            "https://www.nomisweb.co.uk/api/v01/dataset/NM_1_1.data.csv?geography=TYPE480&time=latest&measures=20100&item=1",
            body=mock_csv_response,
            status=200,
            content_type="text/csv",
        )

        result = load_ons(
            "NM_1_1", geography="TYPE480", time="latest", measures=20100, item=1
        )

        assert isinstance(result, pd.DataFrame)
        assert len(result) == 3
        assert list(result.columns) == ["geography_name", "obs_value", "date"]
        assert "England" in result["geography_name"].values

    @responses.activate
    def test_load_ons_with_select(self, mock_csv_response):
        """Test get_ons_table with select parameter."""
        responses.add(
            responses.GET,
            "https://www.nomisweb.co.uk/api/v01/dataset/NM_1_1.data.csv?geography=TYPE480&time=latest&measures=20100&item=1&select=geography_name&select=obs_value",
            body=mock_csv_response,
            status=200,
            content_type="text/csv",
        )

        result = load_ons(
            "NM_1_1",
            geography="TYPE480",
            time="latest",
            measures=20100,
            item=1,
            select=["geography_name", "obs_value"],
        )

        assert isinstance(result, pd.DataFrame)
        assert "geography_name" in result.columns
        assert "obs_value" in result.columns

    @responses.activate
    def test_load_ons_invalid_id(self):
        """Test get_ons_table with invalid dataset ID."""
        responses.add(
            responses.GET,
            "https://www.nomisweb.co.uk/api/v01/dataset/INVALID_ID.data.csv",
            body="<!DOCTYPE html><html>Error</html>",
            status=200,
            content_type="text/html",
        )

        with pytest.raises(ValueError, match="NOMIS ID does not exist"):
            load_ons("INVALID_ID")

    @responses.activate
    def test_load_ons_truncation_warning(self):
        """Test get_ons_table with truncation warning."""
        # Create a CSV with exactly 25000 rows
        csv_data = "geography_name,obs_value\n"
        for i in range(25000):
            csv_data += f"Region_{i},{i}\n"

        responses.add(
            responses.GET,
            "https://www.nomisweb.co.uk/api/v01/dataset/NM_1_1.data.csv",
            body=csv_data,
            status=200,
            content_type="text/csv",
        )

        # Should not raise an exception, but should print a warning
        result = load_ons("NM_1_1")
        assert len(result) == 25000


class TestExtractDataSource:
    """Test suite for extract_data_source function."""

    @patch("kindtech.ons._ingestion.list_tables")
    @patch("kindtech.ons._ingestion.get_overview")
    def test_extract_data_source_success(
        self,
        mock_get_overview,
        mock_list_tables,
        sample_tables_df,
        mock_overview_response,
    ):
        """Test successful extract_data_source call."""
        mock_list_tables.return_value = sample_tables_df
        mock_get_overview.return_value = mock_overview_response

        result = extract_data_source()

        assert isinstance(result, pd.DataFrame)
        assert len(result) == 3
        assert "sourceName" in result.columns
        assert "id" in result.columns
        assert result.iloc[0]["sourceName"] == "Office for National Statistics"

    @patch("kindtech.ons._ingestion.list_tables")
    @patch("kindtech.ons._ingestion.get_overview")
    def test_extract_data_source_with_error(
        self, mock_get_overview, mock_list_tables, sample_tables_df
    ):
        """Test extract_data_source with API error."""
        mock_list_tables.return_value = sample_tables_df
        mock_get_overview.side_effect = Exception("API Error")

        result = extract_data_source()

        assert isinstance(result, pd.DataFrame)
        assert len(result) == 3
        assert all(
            result["sourceName"] == ""
        )  # Should have empty source names due to errors


class TestCreateNomisTablesDataset:
    """Test suite for create_nomis_tables_dataset function."""

    @patch("kindtech.ons._ingestion.list_tables")
    @patch("kindtech.ons._ingestion.extract_data_source")
    def test_create_nomis_tables_dataset_success(
        self, mock_extract_data_source, mock_list_tables, sample_tables_df
    ):
        """Test successful create_nomis_tables_dataset call."""
        mock_list_tables.return_value = sample_tables_df

        sources_df = pd.DataFrame(
            {"sourceName": ["ONS", "ONS", "ONS"], "id": ["NM_1_1", "NM_2_1", "NM_3_1"]}
        )
        mock_extract_data_source.return_value = sources_df

        result = create_nomis_tables_dataset()

        assert isinstance(result, pd.DataFrame)
        assert len(result) == 3
        assert list(result.columns) == ["id", "name", "sourceName"]
        assert all(result["sourceName"] == "ONS")


class TestSaveNomisTablesDataset:
    """Test suite for save_nomis_tables_dataset function."""

    @patch("kindtech.ons._ingestion.create_nomis_tables_dataset")
    @patch("pandas.DataFrame.to_csv")
    def test_save_nomis_tables_dataset_success(
        self, mock_to_csv, mock_create_dataset, sample_tables_df
    ):
        """Test successful save_nomis_tables_dataset call."""
        mock_create_dataset.return_value = sample_tables_df

        result = save_nomis_tables_dataset("test_output.csv")

        mock_to_csv.assert_called_once_with("test_output.csv", index=False)
        assert result.equals(sample_tables_df)


# Integration tests (marked as slow)
@pytest.mark.slow
class TestIntegration:
    """Integration tests that actually call the NOMIS API."""

    def test_list_tables_integration(self):
        """Integration test for list_tables."""
        result = list_tables()
        assert isinstance(result, pd.DataFrame)
        assert len(result) > 0
        assert "id" in result.columns
        assert "name" in result.columns

    def test_list_data_sources_integration(self):
        """Integration test for list_data_sources."""
        result = list_data_sources()
        assert isinstance(result, pd.DataFrame)
        assert len(result) > 0
        assert "source_name" in result.columns
        assert "source_id" in result.columns
        assert "source_description" in result.columns

    def test_load_ons_integration(self):
        """Integration test for load_ons."""
        result = load_ons(
            "NM_1_1", geography="TYPE480", time="latest", measures=20100, item=1
        )
        assert isinstance(result, pd.DataFrame)
        assert len(result) > 0
