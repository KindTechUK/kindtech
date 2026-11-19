"""The connector's privacy guard: totals reach a model, rows never do.

Every tool result passes through :func:`ensure_totals_only` before it leaves the
connector. The guard is deliberately simple and strict: if a value that came
from a person-level input (a postcode, a neighbourhood code attached to a small
count) turns up anywhere in a result, the result is withheld.
"""

import re
from collections.abc import Iterable, Iterator
from typing import Any

# Shorter values match by accident (a count of "12" inside a year), so they are
# not treated as identifying.
MIN_ROW_VALUE_LENGTH = 4
_POSTCODE = re.compile(r"^[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}$")


class PrivacyError(RuntimeError):
    """Raised when a tool result would carry a row-level value.

    The message never repeats the value; it only says where it was found.
    """


def ensure_totals_only(
    payload: dict[str, Any], row_values: Iterable[object] = ()
) -> dict[str, Any]:
    """Return ``payload`` unchanged, or raise if it is not totals only.

    Args:
        payload: A tool result made of plain JSON types.
        row_values: Values taken from person-level input that must not appear
            anywhere in the result, as keys or as values.

    Raises:
        PrivacyError: If the result says it holds row-level output, or if any
            of ``row_values`` appears in it.
    """
    privacy = payload.get("privacy")
    if isinstance(privacy, dict) and privacy.get("row_level_output"):
        msg = "The result is marked as row-level output, so it was withheld."
        raise PrivacyError(msg)
    leaks = find_row_values(payload, row_values)
    if leaks:
        places = ", ".join(leaks[:5])
        msg = f"A value from the input rows appeared in the result at: {places}."
        raise PrivacyError(msg)
    return payload


def looks_like_postcode(value: object) -> bool:
    """Whether ``value`` has the shape of a full UK postcode, such as ``SE13 7VC``."""
    return bool(_POSTCODE.match(" ".join(str(value).split()).upper()))


def find_row_values(payload: object, row_values: Iterable[object]) -> list[str]:
    """List the places in ``payload`` where any of ``row_values`` appears.

    Comparison ignores case and spacing, so ``"se13 7vc"`` is found inside
    ``"Postcode SE137VC was not found"``. Values shorter than
    :data:`MIN_ROW_VALUE_LENGTH` once normalised are skipped.

    Returns:
        Paths such as ``"warnings[0]"`` or ``"tables[1].rows[3].area"``.
    """
    needles = {_normalise(value) for value in row_values}
    needles = {needle for needle in needles if len(needle) >= MIN_ROW_VALUE_LENGTH}
    if not needles:
        return []
    return [
        path
        for path, text in _walk_text(payload, "result", needles)
        if _holds(text, needles)
    ]


def _walk_text(node: object, path: str, needles: set[str]) -> Iterator[tuple[str, str]]:
    """Yield ``(path, text)`` for every key and scalar value under ``node``.

    A key that holds a row value is written as ``<hidden>`` in the path, so the
    path is safe to show.
    """
    if isinstance(node, dict):
        for key, value in node.items():
            name = "<hidden>" if _holds(str(key), needles) else str(key)
            yield f"{path}.{name} (key)", str(key)
            yield from _walk_text(value, f"{path}.{name}", needles)
    elif isinstance(node, list | tuple):
        for index, value in enumerate(node):
            yield from _walk_text(value, f"{path}[{index}]", needles)
    elif node is not None and not isinstance(node, bool):
        yield path, str(node)


def _holds(text: str, needles: set[str]) -> bool:
    """Whether any of ``needles`` appears in ``text``, ignoring case and spaces."""
    squashed = _normalise(text)
    return any(needle in squashed for needle in needles)


def _normalise(value: object) -> str:
    """Lower-case ``value`` and drop all whitespace."""
    return "".join(str(value).split()).casefold()
