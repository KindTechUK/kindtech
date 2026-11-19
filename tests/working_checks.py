"""Checks every analysis result must pass for its working to be whole.

A result carries the code that runs it again and, for each share or rate, the
value before it was rounded. Each analysis's tests call :func:`check_working`
on a result of their own.
"""

import ast
from typing import Any

import numpy as np

from uk_open_data.analyses import AnalysisResult, describe_analysis

RATES = ("percent", "per_100", "per_1000")


def check_working(result: AnalysisResult) -> dict[str, Any]:
    """Check a result's exact figures and its code, and return the code's options."""
    for figure in result.figures:
        if figure.exact is None:
            # Every share or rate that is shown says what it was before rounding.
            assert figure.unit not in RATES or figure.value is None, figure.id
            continue
        assert not figure.suppressed, figure.id
        assert figure.value in (round(figure.exact, 1), round(figure.exact, 2))
    return _options_in(result)


def _options_in(result: AnalysisResult) -> dict[str, Any]:
    """Read the call in a result's code, and check it is the run that was made."""
    tree = ast.parse(result.code)
    call = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "run_analysis"
    )
    assert ast.literal_eval(call.args[0]) == result.analysis_id
    given = {keyword.arg: ast.literal_eval(keyword.value) for keyword in call.keywords}
    info = describe_analysis(result.analysis_id)
    mode = next(mode for mode in info.input_modes if mode.name == result.input_mode)
    # Each column the run used is there to fill in, and no name is written.
    assert given["columns"] == dict.fromkeys(mode.roles, "")
    assert set(given["options"]) <= {option.name for option in info.options}
    # Running it gives the answer and every figure, not one sentence.
    assert result.code.splitlines()[-3:] == [
        "print(result.answer)",
        "for figure in result.figures:",
        "    print(figure.label, figure.value)",
    ]
    return given["options"]


def worked_out(hidden: set[int], sums: list[set[int]]) -> list[int]:
    """List the hidden cells a reader could work out from sums given exactly.

    A reader knows every cell that is shown, so a sum of cells gives them the
    sum of the hidden cells among them. That is one equation for each sum. A
    hidden cell is worked out when the equations fix its value, which is when
    adding "this cell alone" to them does not add anything new.

    Args:
        hidden: The positions of the cells a table hides.
        sums: The positions each exactly known sum covers.
    """
    cells = sorted(hidden)
    known = [[float(cell in covered) for cell in cells] for covered in sums]
    known = [row for row in known if any(row)]
    rank = np.linalg.matrix_rank(np.array(known)) if known else 0
    found = []
    for index, cell in enumerate(cells):
        alone = [float(position == index) for position in range(len(cells))]
        if np.linalg.matrix_rank(np.array([*known, alone])) == rank:
            found.append(cell)
    return found
