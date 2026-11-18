"""The list of lenses and the one function that runs any of them."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from kindtech.lenses._inputs import TabularData, resolve_columns
from kindtech.lenses._model import (
    InputMode,
    Lens,
    LensInfo,
    LensInput,
    LensInputError,
    LensResult,
)

_LENSES: dict[str, Lens] = {}


def register_lens(lens: Lens) -> Lens:
    """Add a lens to the list so it can be found and run by its id.

    Raises:
        ValueError: If a lens with the same id is already registered.
    """
    if lens.info.id in _LENSES:
        msg = f"A lens with the id '{lens.info.id}' is already registered."
        raise ValueError(msg)
    _LENSES[lens.info.id] = lens
    return lens


def list_lenses() -> list[LensInfo]:
    """Return a description of every lens, in the order they were added."""
    return [lens.info for lens in _LENSES.values()]


def describe_lens(lens_id: str) -> LensInfo:
    """Return the description of one lens.

    Raises:
        KeyError: If there is no lens with this id.
    """
    return _get(lens_id).info


def run_lens(
    lens_id: str,
    data: Any,
    columns: Mapping[str, str] | None = None,
    options: Mapping[str, Any] | None = None,
) -> LensResult:
    """Run a lens on a charity's own data.

    Args:
        lens_id: The id of the lens, as listed by :func:`list_lenses`.
        data: A pandas or polars DataFrame, or a list of row dictionaries.
        columns: Which column in ``data`` plays each role the lens needs, as
            role name to column name. A role can be left out when the data
            already has a column with the role's name.
        options: Settings to change, by name. Each has a default.

    Returns:
        Figures, tables of totals, a map description, the working, the choices
        made, checks for a person, sources and a privacy summary.

    Raises:
        KeyError: If there is no lens with this id.
        LensInputError: If the data, columns or options cannot be used. The
            message is safe to show: it never repeats a value from the data.
        requests.RequestException: If a public data source the lens needs
            cannot be reached. Its text holds the web address asked for, so
            show a message of your own rather than the text.
    """
    lens = _get(lens_id)
    info = lens.info
    resolved_options = _resolve_options(info, options)
    table = TabularData(data)
    role_names = [role.name for role in info.roles]
    matched = resolve_columns(table.columns, role_names, columns)
    mode = _choose_mode(info, matched)
    values = {role: table.values(matched[role]) for role in mode.roles}
    return lens.run(
        LensInput(
            mode=mode,
            values=values,
            options=resolved_options,
            n_rows=table.n_rows,
        )
    )


def _get(lens_id: str) -> Lens:
    """Return a registered lens or raise a KeyError that lists the known ids."""
    if lens_id not in _LENSES:
        known = ", ".join(_LENSES) or "none"
        msg = f"No lens called '{lens_id}'. Known lenses: {known}."
        raise KeyError(msg)
    return _LENSES[lens_id]


def _resolve_options(
    info: LensInfo, options: Mapping[str, Any] | None
) -> dict[str, Any]:
    """Fill in defaults and reject options the lens does not have."""
    given = dict(options or {})
    known = {option.name: option.default for option in info.options}
    unknown = [name for name in given if name not in known]
    if unknown:
        msg = (
            f"This lens has no option called {', '.join(sorted(unknown))}. "
            f"Its options are: {', '.join(known) or 'none'}."
        )
        raise LensInputError(msg)
    return {**known, **given}


def _choose_mode(info: LensInfo, matched: Mapping[str, str]) -> InputMode:
    """Pick the first input mode whose roles all have a column."""
    for mode in info.input_modes:
        if all(role in matched for role in mode.roles):
            return mode
    needs = " or ".join(
        " and ".join(f"'{role}'" for role in mode.roles) for mode in info.input_modes
    )
    msg = (
        f"The lens could not find the columns it needs. It needs {needs}. "
        "Say which of your columns to use with the columns argument."
    )
    raise LensInputError(msg)
