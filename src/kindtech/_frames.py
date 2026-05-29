"""Shared helpers for building native DataFrames (pandas or polars).

KindTech is backend-agnostic (Bring Your Own DataFrame): it returns whatever
backend the user has installed. These helpers centralise backend detection and
construction so the ``ons`` and ``postcodes`` modules don't each reimplement it.
"""

from io import StringIO
from typing import Any


def get_native_namespace() -> Any:
    """Return the best available DataFrame backend module (polars or pandas)."""
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
        "Install pandas or polars: `uv add pandas` or `uv add polars`"
    )
    raise ImportError(msg)


def dicts_to_frame(rows: list[dict]) -> Any:
    """Build a native DataFrame from a list of row dicts.

    Column order follows the keys of the first row. Missing keys in later rows
    are filled with ``None``.
    """
    native_ns = get_native_namespace()
    if not rows:
        return native_ns.DataFrame()
    columns = {key: [row.get(key) for row in rows] for key in rows[0]}
    return native_ns.DataFrame(columns)


def csv_to_frame(text: str) -> Any:
    """Parse CSV text into a native DataFrame using the available backend."""
    return get_native_namespace().read_csv(StringIO(text))
