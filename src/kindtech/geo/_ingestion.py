"""
ArcGIS REST Services ingestion module.

Fetches the FeatureServer catalog from the ONS ArcGIS REST API and
extracts geography metadata (type, year, month, region, resolution)
into a CSV lookup table used at runtime by ``_catalog.py``.

Usage:
    uv run python -m kindtech.geo._ingestion
"""

import csv
import logging
import re
from pathlib import Path

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

ARCGIS_BASE_URL = "https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services"
DEFAULT_OUTPUT_PATH = Path(__file__).parent / "data" / "arcgis_services.csv"

# All geography codes from GeographyType enum (longest first)
_GEO_CODES = (
    "CTYUA|BUASD|NHSER|DCELLS|CAUTH|CTRY|LSOA|MSOA|TTWA"
    "|BUA|CAL|CCG|CED|CSP|CTY|EER|FRA|ICB|ITL|LAD"
    "|OA|RGN|WD|DZ|ED|IZ"
)

# Map long-form name prefixes to geography codes.
# Longer prefixes first to avoid false matches.
_LONG_NAME_TO_CODE: dict[str, str] = {
    "Counties_and_Unitary_Authorit": "CTYUA",
    "Lower_Layer_Super_Output_Area": "LSOA",
    "Middle_Layer_Super_Output_Area": "MSOA",
    "Lower_Super_Output_Area": "LSOA",
    "Middle_Super_Output_Area": "MSOA",
    "Local_Authority_District": "LAD",
    "County_Electoral_Division": "CED",
    "Community_Safety_Partnership": "CSP",
    "Clinical_Commissioning_Group": "CCG",
    "Combined_Authorit": "CAUTH",
    "Cancer_Alliance": "CAL",
    "Fire_and_Rescue_Authorit": "FRA",
    "European_Electoral_Region": "EER",
    "Integrated_Care_Board": "ICB",
    "NHS_England_Region": "NHSER",
    "Travel_to_Work_Area": "TTWA",
    "Built_up_Area_Sub": "BUASD",
    "Built_Up_Area_Sub": "BUASD",
    "Built_up_Area": "BUA",
    "Built_Up_Area": "BUA",
    "Output_Area": "OA",
    "Countries_": "CTRY",
    "Counties_": "CTY",
    "Regions_": "RGN",
    "Wards_": "WD",
}

_MONTHS = (
    "JAN(?:UARY)?|FEB(?:RUARY)?|MAR(?:CH)?|APR(?:IL)?|MAY"
    "|JUN(?:E)?|JUL(?:Y)?|AUG(?:UST)?|SEP(?:TEMBER)?"
    "|OCT(?:OBER)?|NOV(?:EMBER)?|DEC(?:EMBER)?"
)
_REGIONS = "UK|GB|EW|EN|WA|SC|NI"
_RESOLUTIONS = "BFC|BFE|BGC|BSC|BUC|NC"

# Old-style resolution codes used in long-form names
_RES_ALIASES: dict[str, str] = {
    "FCB": "BFC",
    "FEB": "BFE",
    "GCB": "BGC",
    "SGCB": "BSC",
    "UGCB": "BUC",
}

_SHORT_RE = re.compile(
    rf"(?i)^({_GEO_CODES})"
    rf"_(?:({_MONTHS})_)?"
    rf"(\d{{2,4}})"
    rf"_(?:[A-Za-z]+_)*?"
    rf"({_REGIONS})"
    rf"_(?:[A-Za-z0-9]+_)*?"
    rf"({_RESOLUTIONS})"
    rf"(?:_.*)?$"
)

_YEAR_RE = re.compile(r"(?:^|_)(\d{4})(?:_|$)")
_MONTH_RE = re.compile(rf"(?:^|_)({_MONTHS})(?:_|$)", re.IGNORECASE)
_REGION_RE = re.compile(rf"(?:^|_)({_REGIONS})(?:_|$)")
_RES_RE = re.compile(rf"(?:^|_)({_RESOLUTIONS}|FCB|FEB|GCB|SGCB|UGCB)(?:_|$)")


def _normalise_year(raw: str) -> int:
    """Convert 2- or 4-digit year string to a 4-digit int."""
    y = int(raw)
    if y < 100:
        return y + 2000 if y <= 30 else y + 1900
    return y


def _normalise_resolution(raw: str) -> str:
    """Map old resolution aliases to standard codes."""
    upper = raw.upper()
    return _RES_ALIASES.get(upper, upper)


def _normalise_month(raw: str) -> str:
    """Truncate full month names to 3-letter codes."""
    return raw.upper()[:3] if raw else ""


def _fetch_services(
    base_url: str = ARCGIS_BASE_URL,
) -> list[str]:
    """Fetch FeatureServer names from the ArcGIS REST JSON API."""
    logger.info("Fetching service catalog from %s", base_url)
    resp = requests.get(base_url, params={"f": "json"}, timeout=120)
    resp.raise_for_status()
    services = resp.json().get("services", [])
    names = [s["name"] for s in services if s.get("type") == "FeatureServer"]
    logger.info("Found %d FeatureServer services", len(names))
    return names


def _parse_short_form(name: str) -> dict[str, str] | None:
    """Parse CODE_[MONTH_]YEAR_REGION_RES style names."""
    m = _SHORT_RE.match(name)
    if not m:
        return None
    return {
        "arcgis_id": name,
        "geography": m.group(1).upper(),
        "year": str(_normalise_year(m.group(3))),
        "month": _normalise_month(m.group(2) or ""),
        "region": m.group(4).upper(),
        "resolution": m.group(5).upper(),
    }


def _parse_long_form(name: str) -> dict[str, str] | None:
    """Parse long-form names via prefix mapping."""
    geo_code = None
    for prefix, code in _LONG_NAME_TO_CODE.items():
        if name.startswith(prefix):
            geo_code = code
            break
    if not geo_code:
        return None

    year_m = _YEAR_RE.search(name)
    res_m = _RES_RE.search(name)
    region_m = _REGION_RE.search(name)
    if not (year_m and res_m and region_m):
        return None

    month_m = _MONTH_RE.search(name)
    return {
        "arcgis_id": name,
        "geography": geo_code,
        "year": str(_normalise_year(year_m.group(1))),
        "month": _normalise_month(month_m.group(1) if month_m else ""),
        "region": region_m.group(1).upper(),
        "resolution": _normalise_resolution(res_m.group(1)),
    }


def _parse_service(name: str) -> dict[str, str] | None:
    """Extract metadata from a service name."""
    return _parse_short_form(name) or _parse_long_form(name)


def ingest_arcgis_services(
    base_url: str = ARCGIS_BASE_URL,
    output_path: Path = DEFAULT_OUTPUT_PATH,
) -> int:
    """
    Fetch the ArcGIS catalog and write parsed metadata to CSV.

    Args:
        base_url: ArcGIS REST services endpoint.
        output_path: Where to write the CSV.

    Returns:
        Number of services written.
    """
    names = _fetch_services(base_url)
    rows: list[dict[str, str]] = []
    seen: set[str] = set()

    for name in names:
        parsed = _parse_service(name)
        if not parsed or parsed["arcgis_id"] in seen:
            continue
        seen.add(parsed["arcgis_id"])
        rows.append(parsed)

    rows.sort(
        key=lambda r: (
            r["geography"],
            -int(r["year"]),
            r["region"],
        ),
    )

    fieldnames = [
        "arcgis_id",
        "geography",
        "year",
        "month",
        "region",
        "resolution",
    ]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    logger.info("Saved %d services to %s", len(rows), output_path)
    return len(rows)


if __name__ == "__main__":
    try:
        count = ingest_arcgis_services()
        print(f"Successfully ingested {count} services to {DEFAULT_OUTPUT_PATH}")
    except Exception as e:
        print(f"Failed to ingest ArcGIS services: {e}")
