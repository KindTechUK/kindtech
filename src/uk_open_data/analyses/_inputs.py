"""Reading and checking the data a person gives to an analysis.

Nothing here keeps or reports a value from the data: problems are described by
how many rows they affect, never by what the rows hold.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from typing import Any

import narwhals as nw

from uk_open_data.analyses._model import AnalysisInputError

# Outward code, optional space, inward code. Checked after tidying.
_POSTCODE = re.compile(r"^[A-Z]{1,2}[0-9][A-Z0-9]?[0-9][A-Z]{2}$")


def is_blank(value: Any) -> bool:
    """Return True for None, NaN and empty or whitespace-only text."""
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    return isinstance(value, str) and not value.strip()


def tidy_postcode(value: Any) -> str | None:
    """Return a postcode as ``SE13 7VC``, or None if it is not shaped like one.

    Only the shape is checked. Whether the postcode exists is found out when it
    is looked up.
    """
    if is_blank(value):
        return None
    compact = re.sub(r"\s+", "", str(value)).upper()
    if not _POSTCODE.match(compact):
        return None
    return f"{compact[:-3]} {compact[-3:]}"


def to_count(value: Any) -> int | None:
    """Return a whole, non-negative count, or None if the value is not one."""
    if is_blank(value) or isinstance(value, bool):
        return None
    try:
        number = float(str(value).replace(",", "").strip())
    except ValueError:
        return None
    if math.isnan(number) or number < 0 or number != int(number):
        return None
    return int(number)


class TabularData:
    """A uniform view of a DataFrame or a list of row dictionaries."""

    def __init__(self, data: Any) -> None:
        self._rows: list[Mapping[str, Any]] | None = None
        self._frame: Any = None
        if isinstance(data, list) and all(isinstance(row, Mapping) for row in data):
            self._rows = data
            self.columns = list(dict.fromkeys(key for row in data for key in row))
            self.n_rows = len(data)
            return
        try:
            self._frame = nw.from_native(data, eager_only=True)
        except TypeError as exc:
            msg = (
                "The data must be a pandas or polars DataFrame, or a list of "
                "row dictionaries."
            )
            raise AnalysisInputError(msg) from exc
        self.columns = list(self._frame.columns)
        self.n_rows = len(self._frame)

    def values(self, column: str) -> list[Any]:
        """Return one column as a list, in row order."""
        if self._rows is not None:
            return [row.get(column) for row in self._rows]
        return self._frame[column].to_list()


def resolve_columns(
    available: list[str],
    roles: list[str],
    columns: Mapping[str, str] | None,
) -> dict[str, str]:
    """Match each role to a column in the data.

    A role is matched to the column named for it in ``columns``. A role left out
    of ``columns`` is matched to a column that has the role's own name, if the
    data has one.

    Returns:
        Role name to column name, for every role that could be matched.

    Raises:
        AnalysisInputError: If ``columns`` names a role the analysis does not have, or a
            column the data does not have.
    """
    mapping = dict(columns or {})
    problems = [
        f"This analysis has no column role called '{role}'. Its roles are: "
        f"{', '.join(roles)}."
        for role in mapping
        if role not in roles
    ]
    problems += [
        f"The column '{column}' given for '{role}' is not in the data. "
        f"Columns found: {', '.join(available) or 'none'}."
        for role, column in mapping.items()
        if role in roles and column not in available
    ]
    if problems:
        wrong = [
            role
            for role, column in mapping.items()
            if role not in roles or column not in available
        ]
        raise AnalysisInputError(problems, role=wrong[0])
    return {
        role: mapping.get(role, role)
        for role in roles
        if mapping.get(role, role) in available
    }
