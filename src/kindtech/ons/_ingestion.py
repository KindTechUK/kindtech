"""
Nomis tables ingestion module

This module provides functions to load NOMIS tables from the nomis API and save
it to a CSV file

The CSV file is later used as the main lookup table to find the relevant data

More information on the NOMIS API can be found here:
https://www.nomisweb.co.uk/api/v01/home.html
"""

import logging
from pathlib import Path
from typing import Any

import pandas as pd
import requests

# Set up logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Constants
NOMIS_BASE_URL = "https://www.nomisweb.co.uk/api/v01"
DEFAULT_OUTPUT_PATH = Path(__file__).parent / "data" / "nomis_tables.csv"


def list_tables(base_url: str = NOMIS_BASE_URL) -> pd.DataFrame:
    """
    Fetch available NOMIS datasets and return them as a DataFrame.

    Args:
        base_url: Base URL for the NOMIS API

    Returns:
        DataFrame containing dataset IDs and names

    Example:
        >>> tables = list_tables()
        >>> print(tables.head())
    """
    # Construct the full URL for dataset definitions
    url = f"{base_url}/dataset/def.sdmx.json"

    # Make the GET request
    response = requests.get(url)
    response.raise_for_status()  # Raise an exception for bad status codes

    # Parse the JSON response
    data = response.json()

    # Extract keyfamily information
    keyfamilies = data["structure"]["keyfamilies"]["keyfamily"]

    # Extract IDs and names
    nomis_ids = [keyfamily["id"] for keyfamily in keyfamilies]
    nomis_names = [keyfamily["name"]["value"] for keyfamily in keyfamilies]

    # Create and return DataFrame
    return pd.DataFrame({"id": nomis_ids, "name": nomis_names})


def list_data_sources(
    base_url: str = NOMIS_BASE_URL,
) -> pd.DataFrame:
    """
    List NOMIS data sources.

    Return a list of the data sources available on NOMIS.

    Args:
        base_url: Base NOMIS URL to query

    Returns:
        A tidy DataFrame of all available data sources accessible through the
        NOMIS API system.

    Example:
        >>> sources = list_data_sources()
        >>> print(sources.head())
    """
    # Construct the URL for content type sources
    url = f"{base_url}/contenttype/sources.json"

    # Make the GET request
    response = requests.get(url)
    response.raise_for_status()

    # Parse the JSON response
    data = response.json()

    sources_list = []

    # Iterate through content type items
    for item in data["contenttype"]["item"]:
        if item["id"] != "census":
            # Regular data source
            source = {
                "source_name": item["name"],
                "source_id": item["id"],
                "source_description": item.get("description", ""),
            }
            sources_list.append(source)
        else:
            # Special handling for census data sources
            for census_item in item["item"]:
                source = {
                    "source_name": census_item["name"],
                    "source_id": census_item["id"],
                    "source_description": census_item.get(
                        "description", "No Description"
                    ),
                }
                sources_list.append(source)

    return pd.DataFrame(sources_list)


def get_overview(dataset_id: str, base_url: str = NOMIS_BASE_URL) -> dict[str, Any]:
    """
    Get overview information for a specific NOMIS dataset.

    Args:
        dataset_id: The NOMIS dataset ID
        base_url: Base URL for the NOMIS API

    Returns:
        Dictionary containing the overview data

    Example:
        >>> overview = get_overview("NM_1_1")
        >>> print(overview.keys())
    """
    url = f"{base_url}/dataset/{dataset_id}/def.sdmx.json"

    response = requests.get(url)
    response.raise_for_status()

    return response.json()


def is_nested(lst: list) -> bool:
    """
    Check if a list contains nested lists.

    Args:
        lst: List to check

    Returns:
        True if the list contains nested lists, False otherwise
    """
    if not isinstance(lst, list):
        return False

    return any(isinstance(item, list) for item in lst)


def extract_data_source(
    base_url: str = NOMIS_BASE_URL,
) -> pd.DataFrame:
    """
    Extract data sources for all NOMIS tables (excluding specific ones).

    Args:
        base_url: Base URL for the NOMIS API

    Returns:
        DataFrame containing source names and dataset IDs
    """
    # Get all tables first
    nomis_tables = list_tables(base_url)

    # Filter out specific datasets as in the R code
    filtered_tables = nomis_tables[
        (nomis_tables["id"] != "NM_45_1") & (nomis_tables["id"] != "NM_2064_1")
    ]

    sources_list = []

    for dataset_id in filtered_tables["id"]:
        try:
            print(f"Processing dataset: {dataset_id}")
            x = get_overview(dataset_id, base_url)

            # Extract source from annotations
            source_name = ""

            # Check if structure and keyfamilies exist
            if (
                "structure" in x
                and "keyfamilies" in x["structure"]
                and "keyfamily" in x["structure"]["keyfamilies"]
                and isinstance(x["structure"]["keyfamilies"]["keyfamily"], list)
            ):
                keyfamily = x["structure"]["keyfamilies"]["keyfamily"][
                    0
                ]  # Get first keyfamily

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

            # If no source found in annotations, try fallback to contact name
            if not source_name and (
                "structure" in x
                and "header" in x["structure"]
                and "sender" in x["structure"]["header"]
                and "contact" in x["structure"]["header"]["sender"]
                and "name" in x["structure"]["header"]["sender"]["contact"]
            ):
                source_name = x["structure"]["header"]["sender"]["contact"]["name"]

            source = {"sourceName": source_name, "id": dataset_id}
            sources_list.append(source)

        except Exception as e:
            print(f"Error processing dataset {dataset_id}: {e}")
            # Add empty source for failed datasets
            source = {"sourceName": "", "id": dataset_id}
            sources_list.append(source)

    return pd.DataFrame(sources_list)


def create_nomis_tables_dataset(
    base_url: str = NOMIS_BASE_URL,
) -> pd.DataFrame:
    """
    Create a comprehensive NOMIS tables dataset with sources.

    Args:
        base_url: Base URL for the NOMIS API

    Returns:
        DataFrame containing all NOMIS tables with their sources
    """
    # Get all tables
    nomis_tables = list_tables(base_url)

    # Extract data sources
    sources = extract_data_source(base_url)

    # Left join tables with sources
    nomis_tables_with_sources = nomis_tables.merge(sources, on="id", how="left")

    return nomis_tables_with_sources


def save_nomis_tables_dataset(
    filepath: str = "nomis_tables.csv",
    base_url: str = NOMIS_BASE_URL,
) -> None:
    """
    Create and save the NOMIS tables dataset to a file.

    Args:
        filepath: Path where to save the dataset
        base_url: Base URL for the NOMIS API
    """
    nomis_tables = create_nomis_tables_dataset(base_url)
    nomis_tables.to_csv(filepath, index=False)
    print(f"NOMIS tables dataset saved to {filepath}")
    return nomis_tables
