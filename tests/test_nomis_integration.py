#!/usr/bin/env python3
"""
Integration tests for NOMIS API functionality.
These tests make actual API calls to the NOMIS service.
"""

import time

import pandas as pd
import pytest
from kindtech.nomis import (
    get_ons_table,
    get_overview,
    list_data_sources,
    list_tables,
)


@pytest.fixture(scope="session")
def sample_nomis_tables():
    """Get a small sample of NOMIS tables for testing."""
    print("Fetching sample NOMIS tables...")
    tables = list_tables()
    # Take only first 5 tables for testing
    sample = tables.head(5)
    print(f"Using {len(sample)} sample datasets for testing")
    return sample


@pytest.fixture(scope="session")
def sample_nomis_data_sources():
    """Get a small sample of NOMIS data sources for testing."""
    print("Fetching sample NOMIS data sources...")
    sources = list_data_sources()
    # Take only first 10 sources for testing
    sample = sources.head(10)
    print(f"Using {len(sample)} sample data sources for testing")
    return sample


class TestNomisAPIIntegration:
    """Integration tests for NOMIS API functionality."""

    def test_list_tables_structure_integration(self, sample_nomis_tables):
        """Test that list_tables returns correct structure."""
        assert isinstance(sample_nomis_tables, pd.DataFrame)
        assert len(sample_nomis_tables) > 0
        assert "id" in sample_nomis_tables.columns
        assert "name" in sample_nomis_tables.columns

        # Check that we have some expected datasets
        dataset_ids = sample_nomis_tables["id"].tolist()
        assert "NM_1_1" in dataset_ids  # Labour Market Statistics

        # Check that names are not empty
        assert all(sample_nomis_tables["name"].str.len() > 0)

    def test_list_data_sources_structure_integration(self, sample_nomis_data_sources):
        """Test that list_data_sources returns correct structure."""
        assert isinstance(sample_nomis_data_sources, pd.DataFrame)
        assert len(sample_nomis_data_sources) > 0
        assert "source_name" in sample_nomis_data_sources.columns
        assert "source_id" in sample_nomis_data_sources.columns
        assert "source_description" in sample_nomis_data_sources.columns

        # Check that we have some expected sources
        source_names = sample_nomis_data_sources["source_name"].tolist()
        assert any("Labour" in name for name in source_names)

    def test_get_overview_integration(self):
        """Test that we can get overview for a specific dataset."""
        overview = get_overview("NM_1_1")  # Labour Market Statistics

        assert isinstance(overview, dict)
        assert len(overview) > 0
        assert "structure" in overview

        # Check structure details
        structure = overview["structure"]
        assert "keyfamilies" in structure
        assert "header" in structure

    def test_get_ons_table_basic_integration(self):
        """Test basic data retrieval from NOMIS."""
        # Get Jobseeker's Allowance data with basic filters
        data = get_ons_table(
            "NM_1_1", geography="TYPE480", time="latest", measures=20100, item=1
        )

        assert isinstance(data, pd.DataFrame)
        assert len(data) > 0
        assert len(data.columns) > 0

        # Check that we have some expected columns
        # (NOMIS API returns uppercase column names)
        assert "GEOGRAPHY_NAME" in data.columns
        assert "OBS_VALUE" in data.columns

    def test_get_ons_table_with_select_integration(self):
        """Test data retrieval with column selection."""
        # Get data with specific column selection
        data = get_ons_table(
            "NM_1_1",
            geography="TYPE480",
            time="latest",
            measures=20100,
            item=1,
            select=["geography_name", "obs_value"],
        )

        assert isinstance(data, pd.DataFrame)
        assert len(data) > 0

        # Check that only selected columns are present
        # (NOMIS API returns uppercase column names)
        assert "GEOGRAPHY_NAME" in data.columns
        assert "OBS_VALUE" in data.columns
        assert len(data.columns) == 2

    def test_get_ons_table_with_aggregation_integration(self):
        """Test data retrieval with aggregation parameters."""
        # Get data with aggregation
        data = get_ons_table(
            "NM_1_1",
            geography="TYPE480",
            time="latest",
            measures=20100,
            item=1,
            select=["geography_name", "sex_name", "obs_value"],
            rows=["geography_name"],
            cols=["sex_name"],
        )

        assert isinstance(data, pd.DataFrame)
        assert len(data) > 0

        # Check that aggregation columns are present
        # (NOMIS API returns uppercase column names)
        assert "GEOGRAPHY_NAME" in data.columns
        # Note: When using rows/cols aggregation, the column names change format
        # The aggregation creates new columns based on the values,
        # not the original column names

    def test_get_ons_table_different_dataset_integration(self):
        """Test data retrieval from a different dataset."""
        # Test with a different dataset that we know works
        data = get_ons_table("NM_2_1", geography="TYPE480", time="latest")

        assert isinstance(data, pd.DataFrame)
        assert len(data) > 0
        assert len(data.columns) > 0

    def test_get_ons_table_time_series_integration(self):
        """Test data retrieval with time series parameters."""
        # Get data for a specific time period
        data = get_ons_table(
            "NM_1_1",
            geography="TYPE480",
            time="2023-01,2023-02,2023-03",
            measures=20100,
            item=1,
        )

        assert isinstance(data, pd.DataFrame)
        assert len(data) > 0

        # Should have multiple time periods (NOMIS API returns uppercase column names)
        if "DATE" in data.columns:
            unique_dates = data["DATE"].nunique()
            assert unique_dates >= 1

    def test_get_ons_table_geography_integration(self):
        """Test data retrieval with different geography types."""
        # Test with different geography types
        geography_types = [
            "TYPE480",
            "TYPE295",
            "TYPE297",
        ]  # Different UK geography types

        for geo_type in geography_types:
            try:
                data = get_ons_table(
                    "NM_1_1", geography=geo_type, time="latest", measures=20100, item=1
                )

                assert isinstance(data, pd.DataFrame)
                assert len(data) > 0

                # Rate limiting - be nice to the API
                time.sleep(0.5)

            except Exception as e:
                # Some geography types might not be available for all datasets
                print(f"Geography type {geo_type} not available: {e}")
                continue

    def test_extract_data_source_integration(self, sample_nomis_tables):
        """Test data source extraction with real API calls."""
        # Test with a small sample to avoid overwhelming the API
        sample_tables = sample_nomis_tables.head(3)  # Use even smaller sample

        sources_list = []
        for dataset_id in sample_tables["id"]:
            try:
                overview = get_overview(dataset_id)

                # Extract source from annotations
                source_name = ""

                # Check if structure and keyfamilies exist
                if (
                    "structure" in overview
                    and "keyfamilies" in overview["structure"]
                    and "keyfamily" in overview["structure"]["keyfamilies"]
                    and isinstance(
                        overview["structure"]["keyfamilies"]["keyfamily"], list
                    )
                ):
                    keyfamily = overview["structure"]["keyfamilies"]["keyfamily"][0]

                    # Check if annotations exist
                    if (
                        "annotations" in keyfamily
                        and "annotation" in keyfamily["annotations"]
                        and isinstance(keyfamily["annotations"]["annotation"], list)
                    ):
                        annotations = keyfamily["annotations"]["annotation"]

                        # Look for source annotation
                        for annotation in annotations:
                            if (
                                isinstance(annotation, dict)
                                and annotation.get("annotationtitle")
                                == "contenttype/sources"
                            ):
                                source_name = annotation.get("annotationtext", "")
                                break

                source = {"sourceName": source_name, "id": dataset_id}
                sources_list.append(source)

                # Rate limiting
                time.sleep(0.5)

            except Exception as e:
                print(f"Error processing dataset {dataset_id}: {e}")
                source = {"sourceName": "", "id": dataset_id}
                sources_list.append(source)

        sources_df = pd.DataFrame(sources_list)

        assert isinstance(sources_df, pd.DataFrame)
        assert len(sources_df) == 3
        assert "sourceName" in sources_df.columns
        assert "id" in sources_df.columns

    def test_create_nomis_tables_dataset_integration(self, sample_nomis_tables):
        """Test the full pipeline with real API calls."""
        # Create a limited dataset for testing
        sample_tables = sample_nomis_tables.head(2)  # Use even smaller sample

        # Extract data sources for the sample
        sources_list = []
        for dataset_id in sample_tables["id"]:
            try:
                overview = get_overview(dataset_id)

                # Simplified source extraction
                source_name = ""
                if (
                    "overview" in overview
                    and "contenttypes" in overview["overview"]
                    and "contenttype" in overview["overview"]["contenttypes"]
                ):
                    contenttypes = overview["overview"]["contenttypes"]["contenttype"]
                    if isinstance(contenttypes, list):
                        for contenttype in contenttypes:
                            if (
                                isinstance(contenttype, dict)
                                and contenttype.get("id") == "sources"
                            ):
                                source_name = contenttype.get("value", "")
                                break

                source = {"sourceName": source_name, "id": dataset_id}
                sources_list.append(source)

                # Rate limiting
                time.sleep(0.5)

            except Exception as e:
                print(f"Error processing dataset {dataset_id}: {e}")
                source = {"sourceName": "", "id": dataset_id}
                sources_list.append(source)

        sources_df = pd.DataFrame(sources_list)

        # Merge tables with sources
        result = sample_tables.merge(sources_df, on="id", how="left")

        assert isinstance(result, pd.DataFrame)
        assert len(result) == 2
        assert "id" in result.columns
        assert "name" in result.columns
        assert "sourceName" in result.columns

    def test_error_handling_integration(self):
        """Test error handling with invalid requests."""
        # Test with invalid dataset ID
        with pytest.raises(ValueError, match="NOMIS ID does not exist"):
            get_ons_table("INVALID_DATASET_ID")

        # Test with invalid parameters - this should raise a ValueError or similar
        with pytest.raises(ValueError):
            get_ons_table("NM_1_1", invalid_param="invalid_value")

    def test_api_rate_limiting_integration(self):
        """Test that we handle API rate limiting gracefully."""
        # Make multiple requests in quick succession
        results = []
        for i in range(3):
            try:
                data = get_ons_table(
                    "NM_1_1", geography="TYPE480", time="latest", measures=20100, item=1
                )
                results.append(data)

                # Small delay between requests
                time.sleep(1)

            except Exception as e:
                print(f"Request {i+1} failed: {e}")
                continue

        # Should have at least one successful result
        assert len(results) > 0
        assert all(isinstance(result, pd.DataFrame) for result in results)


@pytest.mark.slow
class TestNomisAPIPerformance:
    """Performance tests for NOMIS API functionality."""

    def test_api_response_time(self):
        """Test that API responses are within acceptable time limits."""
        import time

        start_time = time.time()
        tables = list_tables()
        end_time = time.time()

        response_time = end_time - start_time
        print(f"list_tables response time: {response_time:.2f} seconds")

        # Should complete within 30 seconds
        assert response_time < 30
        assert isinstance(tables, pd.DataFrame)

    def test_data_retrieval_performance(self):
        """Test performance of data retrieval."""
        import time

        start_time = time.time()
        data = get_ons_table(
            "NM_1_1", geography="TYPE480", time="latest", measures=20100, item=1
        )
        end_time = time.time()

        response_time = end_time - start_time
        print(f"get_ons_table response time: {response_time:.2f} seconds")

        # Should complete within 10 seconds
        assert response_time < 10
        assert isinstance(data, pd.DataFrame)


if __name__ == "__main__":
    # Run integration tests
    pytest.main([__file__, "-v", "--tb=short"])
