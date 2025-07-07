"""
ArcGIS REST Services ingestion module.

This module provides functions to load ArcGIS REST Services data from the web and save
it to a CSV file

The CSV file is later used as the main lookup table to find the relevant data
"""

import calendar
import logging
from pathlib import Path
from typing import Any

import polars as pl
import requests
from bs4 import BeautifulSoup

# Set up logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Constants
ARCGIS_BASE_URL = "https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services/"
DEFAULT_OUTPUT_PATH = Path(__file__).parent / "data" / "arcgis_services.csv"

# Lookup tables for parsing
MONTH = {}
for idx, name in enumerate(calendar.month_name):  # '' then 'January'…
    if name:
        MONTH[name.upper()[:3]] = idx  # JAN, FEB, …
        MONTH[name.upper()] = idx  # JANUARY, FEBRUARY …

REGION = {"UK", "GB", "EW"}
RES = {"BFC", "BFE", "BGC", "BSC"}
DROP = {
    "LOCAL",
    "AUTHORITY",
    "DISTRICT",
    "DISTRICTS",
    "BOUNDARY",
    "BOUNDARIES",
    "WITH",
    "AND",
    "IN",
}


def _load_arcgis_data(url: str = ARCGIS_BASE_URL) -> str:
    """
    Load ArcGIS REST Services catalog HTML from the given URL.

    Args:
        url: The URL of the ArcGIS REST Services catalog.

    Returns:
        The HTML content of the catalog page.

    Raises:
        requests.RequestException: If the request fails.
    """
    logger.info(f"Loading ArcGIS data from {url}")
    try:
        response = requests.get(url)
        response.raise_for_status()  # Raise exception for 4XX/5XX responses
        return response.text
    except requests.RequestException as e:
        logger.error(f"Failed to load ArcGIS data: {e}")
        raise


def _parse_html_for_services(html_content: str) -> list[dict[str, Any]]:
    """
    Parse the HTML content to extract FeatureServer services and their metadata

    Args:
        html_content: The HTML content to parse.

    Returns:
        List of dictionaries containing service metadata (year, month, region,
        resolution, raw name)
    """
    logger.info("Parsing HTML for services")
    kept = []

    soup = BeautifulSoup(html_content, "html.parser")
    services_list = soup.find("ul", id="servicesList")

    if not services_list:
        logger.warning("No services list found in HTML content")
        return kept

    for li in services_list.find_all("li"):
        link = li.find("a")
        if link and "FeatureServer" in link["href"]:
            service_name = link.text

            kept.append(service_name)

    logger.info(f"Total FeatureServer services found: {len(kept)}")

    return kept


def _process_and_save(services: list):
    df = pl.DataFrame({"arcgis_id": services})

    print(df.height)

    to_skip = [
        "LAD_Dec_1961_in_England_and_Wales_BFC_Boundaries_2022",
        "LAD_JUN_1921_EW_BGC",
        "LAD_PT_JUN_1921_EW_BGC",
        "LAD_DEC_2021_EW_BFE_RUC",
        "LAD_DEC_2024_EW_BFE_RUC",
    ]

    # case-insensitive, allow “noise” tokens between the key bits
    pattern = r"""(?ix)                             # i = ignore-case, x = verbose
    ^(?:LAD|LOCAL_AUTHORITY_DISTRICTS).*?_
    (?:                                             # ── optional month ────────────
    (?P<month>JAN(?:UARY)?|FEB(?:RUARY)?|MAR(?:CH)?|APR(?:IL)?|
                MAY|JUN(?:E)?|JUL(?:Y)?|AUG(?:UST)?|
                SEP(?:TEMBER)?|OCT(?:OBER)?|NOV(?:EMBER)?|DEC(?:EMBER)?)
    _
    )?                                              # ──────────────────────────────
    (?P<year>\d{2}(?:\d{2})?)_                      # 24  or  2024, 1961, …
    (?:[A-Z]+_)*?                                   # skip words like BOUNDARIES
    (?P<region>UK|GB|EW)_
    (?:[A-Z]+_)*?                                   # more noise
    (?P<res>BFC|BFE|BGC|BSC)                        # resolution code
    (?:_.*)?$                                       # allow V3_2022 etc. at the end
    """

    df = df.filter(
        (pl.col("arcgis_id").str.contains(pattern))
        & (~pl.col("arcgis_id").is_in(to_skip))
    ).with_columns(
        [
            pl.lit("LAD").alias("geography"),
            pl.col("arcgis_id")
            .str.extract(pattern, group_index=2)
            .cast(pl.Int16)
            .alias("year"),
            pl.col("arcgis_id").str.extract(pattern, group_index=1).alias("month"),
            pl.col("arcgis_id").str.extract(pattern, group_index=3).alias("region"),
            pl.col("arcgis_id").str.extract(pattern, group_index=4).alias("resolution"),
        ]
    )

    df.write_csv(DEFAULT_OUTPUT_PATH)

    print(df.height)
    return df.height


def ingest_arcgis_services(url: str = ARCGIS_BASE_URL) -> int:
    """
    Main function to ingest ArcGIS services from the web and save them to a CSV file.

    Args:
        url: The URL of the ArcGIS REST Services catalog.

    Returns:
        The number of services ingested.
    """
    try:
        html_content = _load_arcgis_data(url)
        services = _parse_html_for_services(html_content)
        nrows = _process_and_save(services)
        return nrows
    except Exception as e:
        logger.error(f"Error during ingestion: {e}")
        raise


if __name__ == "__main__":
    # Example usage
    try:
        count = ingest_arcgis_services()
        print(f"Successfully ingested {count} ArcGIS services to {DEFAULT_OUTPUT_PATH}")
    except Exception as e:
        print(f"Failed to ingest ArcGIS services: {e}")
