"""Office for National Statistics (ONS) data loading and processing module."""

from io import StringIO
from pathlib import Path

import pandas as pd
import requests

from kindtech.utils import get_logger

NOMIS_BASE_URL = "https://www.nomisweb.co.uk/api/v01"

logger = get_logger(__name__)


def build_url_query_string(**kwargs) -> str:
    """
    Build URL query string from keyword arguments.

    Args:
        **kwargs: Parameters to include in the query string

    Returns:
        Query string starting with "?" if parameters exist, empty string otherwise
    """
    if not kwargs:
        return ""

    # Convert parameters to query string format
    query_parts = []
    for key, value in kwargs.items():
        if isinstance(value, list | tuple):
            # Handle list/tuple parameters (like select, rows, cols)
            for item in value:
                query_parts.append(f"{key}={item}")
        else:
            query_parts.append(f"{key}={value}")

    return "?" + "&".join(query_parts)


def load_ons(
    dataset_id: str,
    base_url: str = NOMIS_BASE_URL,
    save_csv: bool = False,
    **kwargs,
) -> pd.DataFrame:
    """
    Retrieve data from the Office of National Statistics (ONS) via the NOMIS API
    for a given dataset.

    Args:
        dataset_id: A table ID recognised by NOMIS (e.g. "NM_1_1")
        base_url: NOMIS base URL to query
        save_csv: If True, save the CSV file to a local "downloads" folder
        **kwargs: Additional parameters used to filter and aggregate the data
                 retrieved from ONS. These are passed to build_url_query_string
                 to build everything in the URL after "?". See
                 "https://www.nomisweb.co.uk/api/v01/help" for information on
                 the options available

    Returns:
        A DataFrame containing the data downloaded from ONS' NOMIS API

    Examples:
        >>> # Pull all data from the "Jobseeker's Allowance" dataset
        >>> load_ons("NM_1_1")

        >>> # Filter "Jobseeker's Allowance" dataset and select columns to output
        >>> load_ons("NM_1_1", geography="TYPE480", time="latest",
        ...               measures=20100, item=1,
        ...               select=["geography_name", "sex_name", "obs_value"])

        >>> # Aggregate statistics using 'rows' and 'cols'
        >>> load_ons("NM_1_1", geography="TYPE480", time="latest",
        ...               measures=20100, item=1,
        ...               select=["geography_name", "sex_name", "obs_value"],
        ...               rows=["geography_name"], cols=["sex_name"])

        >>> # Save CSV to downloads folder
        >>> load_ons("NM_1_1", save_csv=True)
    """
    # Build query string from kwargs
    query_string = build_url_query_string(**kwargs)

    # Construct the full URL
    nomis_url = f"{base_url}/dataset/{dataset_id}.data.csv{query_string}"

    logger.info(f"Querying NOMIS API -> {nomis_url}")

    # Make the GET request
    response = requests.get(nomis_url)
    response.raise_for_status()

    # Check if response is HTML (error page)
    if response.text.strip().startswith("<!DOCTYPE html>"):
        raise ValueError(
            "NOMIS ID does not exist. Use list_tables() for full list of IDs"
        )

    # Parse CSV data
    try:
        nomis_table = pd.read_csv(StringIO(response.text))
    except Exception as e:
        raise ValueError(f"Failed to parse CSV data: {e}") from e

    # Check for truncation warning
    if len(nomis_table) == 25000:
        logger.warning(
            "Query has been truncated to 25,000 rows - providing a NOMIS UID "
            "(i.e. uid = '0x...') will return the full table. See 'API Key, your "
            "Unique ID and Signatures' section at "
            "https://www.nomisweb.co.uk/api/v01/help for further details"
        )

    # Save CSV file if requested
    if save_csv:
        downloads_dir = Path("downloads")
        downloads_dir.mkdir(exist_ok=True)
        csv_filename = downloads_dir / f"{dataset_id}.csv"
        nomis_table.to_csv(csv_filename, index=False)
        logger.info(f"CSV file saved to {csv_filename}")

    return nomis_table
