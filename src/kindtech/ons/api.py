"""
KindTech ONS API

Provides a simple interface for accessing ONS data via the NOMIS API.
Returns DataFrames in whatever backend you have installed (pandas or polars).

Examples:
    >>> from kindtech.ons import load_ons
    >>>
    >>> # Using a friendly alias
    >>> df = load_ons("population", geography_type="LAD", time="latest")
    >>>
    >>> # Using geography_type (no NOMIS TYPE codes needed)
    >>> df = load_ons("NM_1_1", geography_type="LAD", time="latest")
    >>>
    >>> # Using raw NOMIS TYPE code (still works)
    >>> df = load_ons("NM_1_1", geography="TYPE480", time="latest")
    >>>
    >>> # With filters and column selection
    >>> df = load_ons(
    ...     "NM_1_1",
    ...     geography_type="LAD",
    ...     time="latest",
    ...     measures=20100,
    ...     select=["geography_name", "sex_name", "obs_value"],
    ... )
"""

import logging
from io import StringIO
from typing import Any

import narwhals.stable.v2 as nw
import requests

from . import _catalog

NOMIS_BASE_URL = "https://www.nomisweb.co.uk/api/v01"

logger = logging.getLogger(__name__)


def _get_native_namespace() -> Any:
    """Detect the best available DataFrame backend."""
    try:
        import polars

        return polars
    except ImportError:
        pass
    try:
        import pandas

        return pandas
    except ImportError:
        pass
    msg = (
        "No DataFrame backend found. "
        "Install pandas or polars: `uv add pandas` "
        "or `uv add polars`"
    )
    raise ImportError(msg)


def _csv_text_to_frame(text: str) -> nw.DataFrame:
    """Parse CSV text into a narwhals DataFrame using the available backend."""
    native_ns = _get_native_namespace()

    if native_ns.__name__ == "polars":
        native_df = native_ns.read_csv(StringIO(text))
    else:
        native_df = native_ns.read_csv(StringIO(text))

    return nw.from_native(native_df, eager_only=True)


def _dicts_to_frame(data: list[dict]) -> nw.DataFrame:
    """Convert a list of dicts to a narwhals DataFrame."""
    if not data:
        return nw.from_native(_get_native_namespace().DataFrame(), eager_only=True)

    columns = {key: [row[key] for row in data] for key in data[0]}
    native_ns = _get_native_namespace()

    if native_ns.__name__ == "polars":
        native_df = native_ns.DataFrame(columns)
    else:
        native_df = native_ns.DataFrame(columns)

    return nw.from_native(native_df, eager_only=True)


def _extract_code(value: Any) -> str | None:
    """Extract string code from an enum or pass through a string."""
    if value is None:
        return None
    return value.code if hasattr(value, "code") else value


def _extract_year_from_time(time_value: Any) -> int | None:
    """Try to extract a year from a NOMIS time parameter."""
    if time_value is None:
        return None
    s = str(time_value).strip()
    if s.isdigit() and len(s) == 4:
        return int(s)
    return None


def load_ons(
    dataset_id: str,
    geography_type: Any | None = None,
    base_url: str = NOMIS_BASE_URL,
    **kwargs: Any,
) -> Any:
    """
    Load data from the ONS NOMIS API.

    Args:
        dataset_id: NOMIS dataset code (e.g., ``"NM_1_1"``) or
            a friendly alias (e.g., ``"population"``).
        geography_type: Geography type code (e.g., ``"LAD"``) or
            ``GeographyType`` enum. Resolved to a NOMIS TYPE code
            automatically. Cannot be used with ``geography=``.
        base_url: NOMIS API base URL.
        **kwargs: Query parameters passed to the NOMIS API
            (e.g., geography="TYPE480", time="latest", measures=20100).
            Lists are joined with commas.
            See https://www.nomisweb.co.uk/api/v01/help

    Returns:
        DataFrame (pandas or polars, depending on what's installed).

    Raises:
        ValueError: If the dataset ID doesn't exist, the response
            can't be parsed, or conflicting geography params are given.
        ImportError: If neither pandas nor polars is installed.
    """
    # Resolve dataset alias
    from kindtech._mapping import resolve_dataset_id

    dataset_id = resolve_dataset_id(dataset_id)

    # Resolve geography_type to NOMIS TYPE code
    if geography_type is not None:
        if "geography" in kwargs:
            msg = (
                "Cannot specify both 'geography_type' and "
                "'geography'. Use one or the other."
            )
            raise ValueError(msg)
        from kindtech._mapping import resolve_nomis_geography

        geo_code = _extract_code(geography_type)
        year = _extract_year_from_time(kwargs.get("time"))
        kwargs["geography"] = resolve_nomis_geography(geo_code, year)

    # Build query params
    params: dict[str, str] = {}
    for key, value in kwargs.items():
        if isinstance(value, list | tuple):
            params[key] = ",".join(str(v) for v in value)
        else:
            params[key] = str(value)

    url = f"{base_url}/dataset/{dataset_id}.data.csv"
    if params:
        from urllib.parse import urlencode

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
        df = _csv_text_to_frame(response.text)
    except Exception as e:
        msg = f"Failed to parse CSV response for '{dataset_id}': {e}"
        raise ValueError(msg) from e

    if len(df) == 25000:
        logger.warning(
            "Query may be truncated at 25,000 rows. "
            "Provide a NOMIS UID (uid='0x...') to retrieve the full table. "
            "See https://www.nomisweb.co.uk/api/v01/help"
        )

    return nw.to_native(df)


def list_tables(
    name: str | None = None,
    source: str | None = None,
) -> Any:
    """
    List available NOMIS datasets, optionally filtered.

    Args:
        name: Substring to filter dataset names (case-insensitive).
        source: Source name to filter by (e.g., "jsa", "aps").

    Returns:
        DataFrame (pandas or polars) with columns: id, name, sourceName.

    Raises:
        ImportError: If neither pandas nor polars is installed.
    """
    if name or source:
        tables = _catalog.find_tables(name=name, source=source)
    else:
        tables = _catalog._tables

    return nw.to_native(_dicts_to_frame(tables))
