"""
NOMIS tables ingestion module.

Fetches dataset metadata from the NOMIS API and saves it to CSV.
The CSV is used at runtime by `_catalog.py` for dataset lookup.

Usage:
    uv run python -m kindtech.ons._ingestion
"""

import logging
from pathlib import Path
from typing import Any

import pandas as pd
import requests

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

NOMIS_BASE_URL = "https://www.nomisweb.co.uk/api/v01"
DEFAULT_OUTPUT_PATH = Path(__file__).parent / "data" / "nomis_tables.csv"


def _fetch_tables(base_url: str = NOMIS_BASE_URL) -> pd.DataFrame:
    """Fetch all NOMIS dataset IDs and names."""
    url = f"{base_url}/dataset/def.sdmx.json"
    response = requests.get(url, timeout=60)
    response.raise_for_status()

    data = response.json()
    keyfamilies = data["structure"]["keyfamilies"]["keyfamily"]

    return pd.DataFrame(
        {
            "id": [kf["id"] for kf in keyfamilies],
            "name": [kf["name"]["value"] for kf in keyfamilies],
        }
    )


def _get_overview(dataset_id: str, base_url: str = NOMIS_BASE_URL) -> dict[str, Any]:
    """Get overview JSON for a dataset."""
    url = f"{base_url}/dataset/{dataset_id}/def.sdmx.json"
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    return response.json()


def _extract_source(overview: dict) -> str:
    """Extract source name from a dataset overview response."""
    try:
        keyfamily = overview["structure"]["keyfamilies"]["keyfamily"][0]
        for annotation in keyfamily.get("annotations", {}).get("annotation", []):
            if (
                isinstance(annotation, dict)
                and annotation.get("annotationtitle") == "contenttype/sources"
            ):
                return annotation.get("annotationtext", "")
    except (KeyError, IndexError, TypeError):
        pass
    return ""


def _fetch_sources(
    tables: pd.DataFrame, base_url: str = NOMIS_BASE_URL
) -> pd.DataFrame:
    """Fetch source names for all datasets."""
    skip = {"NM_45_1", "NM_2064_1"}
    sources = []

    for dataset_id in tables["id"]:
        if dataset_id in skip:
            sources.append({"id": dataset_id, "sourceName": ""})
            continue
        try:
            logger.info("Processing: %s", dataset_id)
            overview = _get_overview(dataset_id, base_url)
            sources.append({"id": dataset_id, "sourceName": _extract_source(overview)})
        except Exception:
            logger.exception("Error processing %s", dataset_id)
            sources.append({"id": dataset_id, "sourceName": ""})

    return pd.DataFrame(sources)


def ingest_nomis_tables(base_url: str = NOMIS_BASE_URL) -> int:
    """
    Fetch all NOMIS tables with sources and save to CSV.

    Returns:
        Number of tables saved.
    """
    tables = _fetch_tables(base_url)
    sources = _fetch_sources(tables, base_url)
    result = tables.merge(sources, on="id", how="left")
    result.to_csv(DEFAULT_OUTPUT_PATH, index=False)
    logger.info("Saved %d tables to %s", len(result), DEFAULT_OUTPUT_PATH)
    return len(result)


if __name__ == "__main__":
    try:
        count = ingest_nomis_tables()
        print(f"Successfully ingested {count} NOMIS tables to {DEFAULT_OUTPUT_PATH}")
    except Exception as e:
        print(f"Failed to ingest NOMIS tables: {e}")
