"""Shared helpers for building native DataFrames (pandas or polars).

KindTech is backend-agnostic (Bring Your Own DataFrame): it returns whatever
backend the user has installed. These helpers centralise backend detection and
construction so the ``ons`` and ``postcodes`` modules don't each reimplement it.
"""

from io import BytesIO, StringIO
from typing import Any


def get_native_namespace() -> Any:
    """Return the DataFrame backend module to build native frames with.

    KindTech depends only on ``narwhals`` (plus ``requests``), not on pandas or
    polars — users bring whichever they already use. This detects what's
    installed rather than forcing one: polars is tried first (faster, and the
    narwhals-native backend) and pandas second. The order only matters when
    *both* are installed; if neither is, a clear ImportError tells the user to
    install one.
    """
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


def read_spreadsheet_rows(
    content: bytes, sheet_name: str, header_row: int = 0
) -> list[dict[str, Any]]:
    """Read one sheet of an XLSX/ODS workbook into a list of row dicts.

    Uses ``python-calamine`` (one fast reader for both formats). ``header_row``
    is the 0-based index of the header line; rows above it are ignored. Header
    cells are stringified and stripped; fully empty rows are dropped.
    """
    try:
        from python_calamine import CalamineWorkbook
    except ImportError as exc:
        msg = (
            "Reading XLSX/ODS sources needs python-calamine. "
            "Install it: `uv add python-calamine`"
        )
        raise ImportError(msg) from exc

    rows = (
        CalamineWorkbook.from_filelike(BytesIO(content))
        .get_sheet_by_name(sheet_name)
        .to_python()
    )
    header = [str(cell).strip() for cell in rows[header_row]]
    return [
        dict(zip(header, row, strict=False))
        for row in rows[header_row + 1 :]
        if any(cell not in (None, "") for cell in row)
    ]
