"""
KindTech ONS API

Provides a simple interface for accessing ONS data via the NOMIS API.

Examples:
    >>> from kindtech.ons import load_ons
    >>>
    >>> # Load all data from a dataset
    >>> df = load_ons("NM_1_1")
    >>>
    >>> # Filter and select columns
    >>> df = load_ons(
    ...     "NM_1_1",
    ...     geography="TYPE480",
    ...     time="latest",
    ...     measures=20100,
    ...     select=["geography_name", "sex_name", "obs_value"],
    ... )
"""

import logging
from io import StringIO
from typing import Any
from urllib.parse import urlencode

import pandas as pd
import requests

from . import _catalog

NOMIS_BASE_URL = "https://www.nomisweb.co.uk/api/v01"

logger = logging.getLogger(__name__)


def load_ons(
    dataset_id: str,
    base_url: str = NOMIS_BASE_URL,
    **kwargs: Any,
) -> pd.DataFrame:
    """
    Load data from the ONS NOMIS API.

    Args:
        dataset_id: NOMIS dataset code (e.g., "NM_1_1").
        base_url: NOMIS API base URL.
        **kwargs: Query parameters passed to the NOMIS API
            (e.g., geography="TYPE480", time="latest", measures=20100).
            Lists are joined with commas. See https://www.nomisweb.co.uk/api/v01/help

    Returns:
        DataFrame with the requested data.

    Raises:
        ValueError: If the dataset ID doesn't exist or the response can't be parsed.
    """
    # Build query params
    params: dict[str, str] = {}
    for key, value in kwargs.items():
        if isinstance(value, list | tuple):
            params[key] = ",".join(str(v) for v in value)
        else:
            params[key] = str(value)

    url = f"{base_url}/dataset/{dataset_id}.data.csv"
    if params:
        url = f"{url}?{urlencode(params)}"

    logger.info("Querying NOMIS API: %s", url)

    response = requests.get(url, timeout=60)
    response.raise_for_status()

    # Check for HTML error page
    if response.text.strip().startswith("<!DOCTYPE html>"):
        msg = (
            f"NOMIS dataset '{dataset_id}' does not exist. "
            "Use list_tables() to browse available datasets."
        )
        raise ValueError(msg)

    try:
        df = pd.read_csv(StringIO(response.text))
    except Exception as e:
        msg = f"Failed to parse CSV response for '{dataset_id}': {e}"
        raise ValueError(msg) from e

    if len(df) == 25000:
        logger.warning(
            "Query may be truncated at 25,000 rows. "
            "Provide a NOMIS UID (uid='0x...') to retrieve the full table. "
            "See https://www.nomisweb.co.uk/api/v01/help"
        )

    return df


def list_tables(
    name: str | None = None,
    source: str | None = None,
) -> pd.DataFrame:
    """
    List available NOMIS datasets, optionally filtered.

    Args:
        name: Substring to filter dataset names (case-insensitive).
        source: Source name to filter by (e.g., "jsa", "aps").

    Returns:
        DataFrame with columns: id, name, sourceName.
    """
    if name or source:
        tables = _catalog.find_tables(name=name, source=source)
    else:
        tables = _catalog._tables

    return pd.DataFrame(tables)
