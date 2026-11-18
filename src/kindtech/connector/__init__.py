"""Kindtech connector: the lenses and open data as tools for a chat assistant.

The functions here are plain Python and need nothing extra. The server that
offers them to an assistant over the Model Context Protocol needs the
``connector`` extra::

    uv add "kindtech[connector]"
    uv run python -m kindtech.connector

Every tool is read-only and returns totals, never rows.
"""

from typing import Any

from kindtech.connector.command import main
from kindtech.connector.lenses import find_lens, run_lens_on_counts
from kindtech.connector.places import describe_place
from kindtech.connector.privacy import PrivacyError, ensure_totals_only

__all__ = [
    "PrivacyError",
    "build_server",
    "describe_place",
    "ensure_totals_only",
    "find_lens",
    "main",
    "run_lens_on_counts",
]

_MISSING_EXTRA = (
    "The connector server needs the 'connector' extra. "
    'Install it: `uv add "kindtech[connector]"`'
)


def build_server() -> Any:
    """Build the connector's MCP server (needs the ``connector`` extra).

    Raises:
        ImportError: If the ``mcp`` package is not installed.
    """
    try:
        from kindtech.connector.server import build_server as _build_server
    except ImportError as error:
        raise ImportError(_MISSING_EXTRA) from error
    return _build_server()
