"""Data model shared by every lens.

A lens takes a charity's own data and returns figures a person can check and
reuse. Everything a lens returns is a total: nothing in a
:class:`LensResult` describes one person.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, fields, is_dataclass
from typing import Any

from kindtech._frames import dicts_to_frame


class LensInputError(ValueError):
    """The data, column mapping or options given to a lens cannot be used.

    The message is written for a person and never repeats a value from the
    data. ``problems`` holds each problem as its own sentence.
    """

    def __init__(self, problems: list[str] | str) -> None:
        self.problems: list[str] = (
            [problems] if isinstance(problems, str) else list(problems)
        )
        super().__init__(" ".join(self.problems))


def _plain(value: Any) -> Any:
    """Convert dataclasses, tuples and mappings to plain JSON types."""
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: _plain(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(item) for item in value]
    return value


@dataclass(frozen=True)
class Role:
    """A column a lens can use, named by what it holds.

    ``reported`` is True when the column holds names that the result uses too,
    such as local authorities, so the same names can appear in its figures and
    tables. It is False for anything about a person, and a lens never repeats
    those.

    ``reported_values`` narrows that to the exact values the result uses, for
    a column that also holds a person's own words, such as their ethnic group.
    A caller that checks a result for values repeated from the input should
    leave out only the listed values, compared without case, and check every
    other value in the column. When no values are listed, every value of a
    reported column is a public name, and the caller leaves the column out.
    """

    name: str
    description: str
    example: str = ""
    reported: bool = False
    reported_values: tuple[str, ...] = ()


@dataclass(frozen=True)
class InputMode:
    """One accepted shape of input: the set of roles it needs.

    ``aggregated`` is True when the mode takes data that is already totalled,
    so no row about one person is needed to use it.
    """

    name: str
    description: str
    roles: tuple[str, ...]
    aggregated: bool = False


@dataclass(frozen=True)
class Option:
    """A setting a person may change, with the value used when they do not."""

    name: str
    description: str
    default: Any = None


@dataclass(frozen=True)
class LensInfo:
    """What a lens is for and what it needs."""

    id: str
    title: str
    question: str
    summary: str
    version: str
    roles: tuple[Role, ...]
    input_modes: tuple[InputMode, ...]
    options: tuple[Option, ...] = ()
    coverage: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Return this description as plain JSON types."""
        return _plain(self)


@dataclass(frozen=True)
class Figure:
    """One headline number.

    ``value`` is ``None`` when the figure is hidden to protect small counts
    (``suppressed`` is then ``True``) or cannot be worked out (see ``note``).
    """

    id: str
    label: str
    value: float | int | None
    unit: str
    note: str = ""
    suppressed: bool = False


@dataclass(frozen=True)
class Table:
    """A table of totals.

    ``detail`` marks long tables, such as the rows behind a map, that a caller
    may leave out of a summary.
    """

    id: str
    title: str
    columns: tuple[str, ...]
    rows: list[dict[str, Any]]
    detail: bool = False

    def to_frame(self) -> Any:
        """Return the table as a pandas or polars DataFrame."""
        ordered = [
            {column: row.get(column) for column in self.columns} for row in self.rows
        ]
        return dicts_to_frame(ordered)


@dataclass(frozen=True)
class MapLayer:
    """One thing a map can colour areas by.

    ``categories`` lists every value the column can hold, lowest first, so a
    map can give each a colour and a legend entry. ``emphasis`` says which end
    of that list gets the strongest colour: ``"high"`` or ``"low"``.
    """

    id: str
    label: str
    value_column: str
    kind: str
    note: str = ""
    categories: tuple[Any, ...] = ()
    emphasis: str = "high"


@dataclass(frozen=True)
class MapSpec:
    """A description of a map. Drawing it is a separate step."""

    title: str
    geography_type: str
    geography_year: int
    table: str
    code_column: str
    layers: tuple[MapLayer, ...]


@dataclass(frozen=True)
class ChartSeries:
    """One set of bars in a chart: a column of a table, with its label and unit."""

    column: str
    label: str
    unit: str


@dataclass(frozen=True)
class Chart:
    """A chart that can be drawn from one of the result's tables.

    There is one group of bars for each row of the table, named by
    ``category_column``, and one bar in the group for each entry of ``series``.
    Every series in a chart has the same unit, so one axis serves them all. A
    value hidden to protect a small count is ``None`` in the table, and no bar
    is drawn for it.
    """

    id: str
    title: str
    table: str
    category_column: str
    series: tuple[ChartSeries, ...]
    kind: str = "bar"
    note: str = ""


@dataclass(frozen=True)
class Step:
    """One step of the working, in the order it happened."""

    title: str
    detail: str
    rows_in: int | None = None
    rows_out: int | None = None


@dataclass(frozen=True)
class Choice:
    """A choice the lens made for the person, and how to change it."""

    id: str
    label: str
    value: Any
    reason: str
    option: str | None = None


@dataclass(frozen=True)
class Check:
    """Something a person must confirm before using the figures."""

    id: str
    question: str
    why: str


@dataclass(frozen=True)
class Source:
    """A published source a figure rests on.

    ``attribution`` holds any statements the licence asks users to show.
    """

    id: str
    name: str
    publisher: str
    url: str
    licence: str
    edition: str
    used_for: str
    attribution: tuple[str, ...] = ()


@dataclass(frozen=True)
class Privacy:
    """How the result protects the people in the data."""

    suppress_below: int
    cells_suppressed: int
    row_level_output: bool = False
    sent_to_third_parties: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class LensResult:
    """Everything a lens returns."""

    lens_id: str
    lens_version: str
    package_version: str
    run_on: str
    input_mode: str
    figures: tuple[Figure, ...]
    tables: tuple[Table, ...]
    map: MapSpec | None
    working: tuple[Step, ...]
    choices: tuple[Choice, ...]
    checks: tuple[Check, ...]
    caveats: tuple[str, ...]
    warnings: tuple[str, ...]
    sources: tuple[Source, ...]
    privacy: Privacy
    charts: tuple[Chart, ...] = ()

    def figure(self, figure_id: str) -> Figure:
        """Return the figure with this id.

        Raises:
            KeyError: If the result has no such figure.
        """
        for item in self.figures:
            if item.id == figure_id:
                return item
        raise KeyError(figure_id)

    def table(self, table_id: str) -> Table:
        """Return the table with this id.

        Raises:
            KeyError: If the result has no such table.
        """
        for item in self.tables:
            if item.id == table_id:
                return item
        raise KeyError(table_id)

    def to_dict(self, include_detail: bool = True) -> dict[str, Any]:
        """Return the result as plain JSON types.

        Args:
            include_detail: When ``False``, tables marked ``detail`` keep their
                title and columns but lose their rows. Use this when the result
                is handed to a language model.
        """
        payload = _plain(self)
        if not include_detail:
            for table in payload["tables"]:
                if table["detail"]:
                    table["rows"] = []
        return payload


@dataclass(frozen=True)
class LensInput:
    """The input a lens receives once columns and options are resolved."""

    mode: InputMode
    values: dict[str, list[Any]]
    options: dict[str, Any]
    n_rows: int


@dataclass(frozen=True)
class Lens:
    """A lens: its description and the function that runs it."""

    info: LensInfo
    run: Callable[[LensInput], LensResult] = field(repr=False)
