"""Kindtech connector: the analyses and open data as tools for a chat assistant.

The functions here are plain Python and need nothing extra. The server that
offers them to an assistant over the Model Context Protocol needs the
``connector`` extra::

    uv add "uk-open-data[connector]"
    uv run uk-open-data connector

Every tool is read-only and returns totals, never rows.
"""

from typing import Any

from uk_open_data.connector.analyses import find_analysis, run_analysis_on_counts
from uk_open_data.connector.command import main
from uk_open_data.connector.places import describe_place
from uk_open_data.connector.privacy import PrivacyError, ensure_totals_only

__all__ = [
    "PrivacyError",
    "build_server",
    "describe_place",
    "ensure_totals_only",
    "find_analysis",
    "main",
    "run_analysis_on_counts",
]

_MISSING_EXTRA = (
    "The connector server needs the 'connector' extra. Install it with "
    '`uv add "uk-open-data[connector]"` or '
    '`pip install "uk-open-data[connector]"`.'
)


def build_server(map_boundaries: Any = None) -> Any:
    """Build the connector's MCP server (needs the ``connector`` extra).

    Args:
        map_boundaries: A function that takes an analysis result and gives the
            outlines of the areas on its map, as GeoJSON. Left out, the
            outlines are fetched from the ONS Open Geography Portal each time
            a map is drawn. Pass one that reads outlines kept on your server
            when you host the connector.

    Raises:
        ImportError: If the ``mcp`` package is not installed.
    """
    try:
        from uk_open_data.connector.server import build_server as _build_server
    except ImportError as error:
        raise ImportError(_MISSING_EXTRA) from error
    return _build_server(map_boundaries)
