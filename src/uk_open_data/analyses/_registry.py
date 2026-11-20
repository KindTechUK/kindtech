"""The list of analyses and the one function that runs any of them."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from uk_open_data.analyses._inputs import TabularData, resolve_columns
from uk_open_data.analyses._model import (
    Analysis,
    AnalysisInfo,
    AnalysisInput,
    AnalysisInputError,
    AnalysisResult,
    InputMode,
)

_ANALYSES: dict[str, Analysis] = {}

# Completed runs are counted from this logger's records, by a host that keeps
# its own logs. The package sends nothing anywhere.
RUNS_LOGGER = "uk_open_data.runs"
DOORS = ("cli", "page", "chat")


def register_analysis(analysis: Analysis) -> Analysis:
    """Add an analysis to the list so it can be found and run by its id.

    Raises:
        ValueError: If an analysis with the same id is already registered.
    """
    if analysis.info.id in _ANALYSES:
        msg = f"An analysis with the id '{analysis.info.id}' is already registered."
        raise ValueError(msg)
    _ANALYSES[analysis.info.id] = analysis
    return analysis


def list_analyses() -> list[AnalysisInfo]:
    """Return a description of every analysis, in the order they were added."""
    return [analysis.info for analysis in _ANALYSES.values()]


def describe_analysis(analysis_id: str) -> AnalysisInfo:
    """Return the description of one analysis.

    Raises:
        KeyError: If there is no analysis with this id.
    """
    return _get(analysis_id).info


def run_analysis(
    analysis_id: str,
    data: Any,
    columns: Mapping[str, str] | None = None,
    options: Mapping[str, Any] | None = None,
) -> AnalysisResult:
    """Run an analysis on a charity's own data.

    Args:
        analysis_id: The id of the analysis, as listed by :func:`list_analyses`.
        data: A pandas or polars DataFrame, or a list of row dictionaries.
        columns: Which column in ``data`` plays each role the analysis needs, as
            role name to column name. A role can be left out when the data
            already has a column with the role's name.
        options: Settings to change, by name. Each has a default.

    Returns:
        Figures, tables of totals, a map description, the working, the choices
        made, checks for a person, sources and a privacy summary.

    Raises:
        KeyError: If there is no analysis with this id.
        AnalysisInputError: If the data, columns or options cannot be used. The
            message is safe to show: it never repeats a value from the data.
        requests.RequestException: If a public data source the analysis needs
            cannot be reached. Its text holds the web address asked for, so
            show a message of your own rather than the text.
    """
    analysis = _get(analysis_id)
    info = analysis.info
    resolved_options = _resolve_options(info, options)
    table = TabularData(data)
    role_names = [role.name for role in info.roles]
    matched = resolve_columns(table.columns, role_names, columns)
    mode = _choose_mode(info, matched)
    values = {role: table.values(matched[role]) for role in mode.roles}
    result = analysis.run(
        AnalysisInput(
            mode=mode,
            values=values,
            options=resolved_options,
            n_rows=table.n_rows,
        )
    )
    return replace(result, code=_code(info, mode, resolved_options, result))


def _code(
    info: AnalysisInfo,
    mode: InputMode,
    options: Mapping[str, Any],
    result: AnalysisResult,
) -> str:
    """Write the Python that runs an analysis again with the same settings.

    Nothing from the person's table is written. The names of their columns
    are left empty for them to fill in, and so is any setting that holds
    their own words. Every other setting that has a value is written out,
    the ones left alone too, so the code gives the same result if a default
    changes later. A setting with no value is one the analysis works out, and
    is left out. A place the person named in a setting is written as they
    gave it: it is their choice, not a row of their table.

    The code prints the answer and every figure, so that running it gives
    figures to set beside the ones in the result.

    The words are few and fixed, because a caller may search a result for
    words repeated from the person's data: the code names the analysis by its
    id, not its title.
    """
    private = {option.name for option in info.options if option.private}
    columns = [
        f'        "{role}": "",  # the name of your column' for role in mode.roles
    ]
    settings = [
        _setting(name, value, name in private)
        for name, value in options.items()
        if value is not None
    ]
    return "\n".join(
        [
            f"# Version {result.analysis_version} of this analysis, run with",
            f"# uk-open-data {result.package_version}. This runs it again with",
            "# the same settings. No row or heading of your table is written",
            "# here: put the name of your own column beside each role.",
            "import pandas as pd",
            "",
            "from uk_open_data.analyses import run_analysis",
            "",
            'data = pd.read_csv("your-table.csv")',
            "result = run_analysis(",
            f'    "{info.id}",',
            "    data,",
            "    columns={",
            *columns,
            "    },",
            "    options={",
            *settings,
            "    },",
            ")",
            "print(result.answer)",
            "for figure in result.figures:",
            "    print(figure.label, figure.value)",
        ]
    )


def _setting(name: str, value: Any, private: bool) -> str:
    """Write one option as a line of Python, or leave it to be filled in."""
    if private:
        return f'        "{name}": {{}},  # fill in: your own words are not repeated'
    # Through JSON and back, so that only plain values are written.
    plain = json.loads(json.dumps(value, default=str))
    return f'        "{name}": {_literal(plain)},'


def _literal(value: Any) -> str:
    """Write a plain value as Python, with text in double quotes."""
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return f"[{', '.join(_literal(item) for item in value)}]"
    if isinstance(value, dict):
        pairs = (f"{_literal(key)}: {_literal(item)}" for key, item in value.items())
        return f"{{{', '.join(pairs)}}}"
    return repr(value)


def record_run(analysis_id: str, input_mode: str, door: str) -> None:
    """Record that a run has given a person an answer.

    Call it once for each answer a person receives, from the place that gave
    it: the command line, a page or a chat assistant. It writes one record at
    INFO level to the ``uk_open_data.runs`` logger, and that is all it does.
    A host that keeps its logs can count the records; on a person's own
    machine nobody collects them. Nothing is sent anywhere.

    The record holds the three arguments and nothing else, and each must be
    one of a fixed list, so no word from a person's data can reach a log. A
    value that is not on its list is refused without being repeated.

    Args:
        analysis_id: The id of the analysis that ran.
        input_mode: The input mode it ran in, as ``result.input_mode`` gives it.
        door: Where the answer was given: ``"cli"``, ``"page"`` or ``"chat"``.

    Raises:
        KeyError: If there is no analysis with this id.
        ValueError: If the analysis has no such input mode, or the door is not
            one of the three.
    """
    if analysis_id not in _ANALYSES:
        known = ", ".join(_ANALYSES) or "none"
        raise KeyError(f"No analysis has that id. Known analyses: {known}.")
    modes = [mode.name for mode in _ANALYSES[analysis_id].info.input_modes]
    if input_mode not in modes:
        msg = f"This analysis has no input mode of that name. Its modes: {modes}."
        raise ValueError(msg)
    if door not in DOORS:
        raise ValueError(f"The door must be one of: {', '.join(DOORS)}.")
    logging.getLogger(RUNS_LOGGER).info(
        "run analysis=%s mode=%s door=%s",
        analysis_id,
        input_mode,
        door,
        extra={"analysis_id": analysis_id, "input_mode": input_mode, "door": door},
    )


def _get(analysis_id: str) -> Analysis:
    """Return a registered analysis or raise a KeyError that lists the known ids."""
    if analysis_id not in _ANALYSES:
        known = ", ".join(_ANALYSES) or "none"
        msg = f"No analysis called '{analysis_id}'. Known analyses: {known}."
        raise KeyError(msg)
    return _ANALYSES[analysis_id]


def _resolve_options(
    info: AnalysisInfo, options: Mapping[str, Any] | None
) -> dict[str, Any]:
    """Fill in defaults and reject options the analysis does not have."""
    given = dict(options or {})
    known = {option.name: option.default for option in info.options}
    unknown = [name for name in given if name not in known]
    if unknown:
        # Each option by the name that is typed and the name a page shows.
        listed = ", ".join(
            f"{option.name} ('{option.label}')" if option.label else option.name
            for option in info.options
        )
        msg = (
            f"This analysis has no option called {', '.join(sorted(unknown))}. "
            f"Its options are: {listed or 'none'}."
        )
        raise AnalysisInputError(msg)
    return {**known, **given}


def _choose_mode(info: AnalysisInfo, matched: Mapping[str, str]) -> InputMode:
    """Pick the first input mode whose roles all have a column."""
    for mode in info.input_modes:
        if all(role in matched for role in mode.roles):
            return mode
    needs = " or ".join(
        " and ".join(f"'{role}'" for role in mode.roles) for mode in info.input_modes
    )
    msg = (
        f"The analysis could not find the columns it needs. It needs {needs}. "
        "Say which of your columns holds each one."
    )
    raise AnalysisInputError(msg, role=_first_missing(info, matched))


def _first_missing(info: AnalysisInfo, matched: Mapping[str, str]) -> str | None:
    """The first column still to be named, so a door can point at it.

    It is taken from the way of giving data that has most of its columns
    named already, which is the one the person is most likely to be using.
    """
    nearest = max(
        info.input_modes,
        key=lambda mode: sum(role in matched for role in mode.roles),
        default=None,
    )
    if nearest is None:
        return None
    return next((role for role in nearest.roles if role not in matched), None)
