"""
NOMIS tables ingestion module.

Fetches dataset metadata from the NOMIS API and saves it to CSV.
The CSV is used at runtime by `_catalog.py` for dataset lookup.

All metadata (id, name, source) comes from the single bulk endpoint
``dataset/def.sdmx.json`` — no per-dataset requests needed.

Usage:
    uv run python -m kindtech.ons._ingestion
"""

import csv
import logging
from pathlib import Path

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

NOMIS_BASE_URL = "https://www.nomisweb.co.uk/api/v01"
DEFAULT_OUTPUT_PATH = Path(__file__).parent / "data" / "nomis_tables.csv"


def _extract_source(keyfamily: dict) -> str:
    """Extract source name from a keyfamily's annotations."""
    for annotation in keyfamily.get("annotations", {}).get("annotation", []):
        if (
            isinstance(annotation, dict)
            and annotation.get("annotationtitle") == "contenttype/sources"
        ):
            return annotation.get("annotationtext", "")
    return ""


def _fetch_all(
    base_url: str = NOMIS_BASE_URL,
) -> list[dict[str, str]]:
    """Fetch all NOMIS datasets with source info in one request."""
    url = f"{base_url}/dataset/def.sdmx.json"
    logger.info("Fetching dataset catalog from %s", url)
    response = requests.get(url, timeout=120)
    response.raise_for_status()

    try:
        keyfamilies = response.json()["structure"]["keyfamilies"]["keyfamily"]
    except (KeyError, TypeError) as exc:
        raise RuntimeError(
            "Unexpected NOMIS API response structure: missing "
            "structure.keyfamilies.keyfamily"
        ) from exc
    logger.info("Found %d datasets", len(keyfamilies))

    return [
        {
            "id": kf["id"],
            "name": kf["name"]["value"],
            "sourceName": _extract_source(kf),
        }
        for kf in keyfamilies
    ]


def ingest_nomis_tables(base_url: str = NOMIS_BASE_URL) -> int:
    """
    Fetch all NOMIS tables with sources and save to CSV.

    Returns:
        Number of tables saved.
    """
    tables = _fetch_all(base_url)

    if not tables:
        raise RuntimeError(
            "No datasets returned from NOMIS API; refusing to "
            "overwrite existing CSV with empty data"
        )

    fieldnames = ["id", "name", "sourceName"]
    DEFAULT_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(DEFAULT_OUTPUT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(tables)

    logger.info("Saved %d tables to %s", len(tables), DEFAULT_OUTPUT_PATH)
    return len(tables)


if __name__ == "__main__":
    try:
        count = ingest_nomis_tables()
        print(f"Successfully ingested {count} NOMIS tables to {DEFAULT_OUTPUT_PATH}")
    except Exception as e:
        print(f"Failed to ingest NOMIS tables: {e}")
