"""Find a lens and run one on counts, as totals only.

These are thin wrappers over :mod:`kindtech.lenses`. They add what a chat
assistant needs: a search over the lens descriptions, a check that only
already-totalled input is accepted, and the privacy guard on what comes back.

    >>> from kindtech.connector import find_lens, run_lens_on_counts
    >>> find_lens("deprived neighbourhoods")["lenses"][0]["id"]
    'reach-deprivation'
"""

import re
from typing import Any

import kindtech.lenses as engine
from kindtech.connector.privacy import ensure_totals_only

MAX_COUNT_ROWS = 50_000
# "deprived" and "deprivation" should match, so words are compared by stem.
STEM_LENGTH = 6

HOW_TO_RUN = (
    "Run a lens with run_lens_on_counts, passing rows that are already totals "
    "for areas (the roles of an input mode marked 'aggregated'). Never pass "
    "rows about individual people."
)
SHOW_WITH_FIGURES = (
    "Show the checks and caveats next to the figures. The checks are for the "
    "person to answer, not for an assistant."
)

_STOP_WORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "do",
        "for",
        "how",
        "in",
        "is",
        "of",
        "on",
        "our",
        "the",
        "to",
        "we",
        "what",
        "where",
        "which",
        "who",
        "with",
    ]
)


def find_lens(query: str | None = None) -> dict[str, Any]:
    """Find the lenses that answer a question.

    Args:
        query: The question in the person's own words, or a few key words.
            Leave out to list every lens.

    Returns:
        ``lenses`` holds each lens description (see ``LensInfo`` in the lens
        contract), best match first. ``matched`` says how many matched the
        query; when none did, every lens is listed and ``note`` says so.
    """
    lenses = [info.to_dict() for info in engine.list_lenses()]
    words = _words(query or "")
    scored = sorted(
        ((_score(lens, words), lens) for lens in lenses),
        key=lambda pair: pair[0],
        reverse=True,
    )
    matched = [lens for score, lens in scored if score > 0]
    answer: dict[str, Any] = {
        "lenses": matched or lenses,
        "matched": len(matched),
        "available": len(lenses),
        "how_to_run": HOW_TO_RUN,
    }
    if not lenses:
        answer["note"] = "No lenses are installed."
    elif words and not matched:
        answer["note"] = "No lens matched those words, so every lens is listed."
    return answer


def run_lens_on_counts(
    lens_id: str,
    counts: list[dict[str, Any]],
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run a lens on data that is already totalled by area.

    Args:
        lens_id: The lens to run, for example ``"reach-deprivation"``.
        counts: One dict per area, keyed by the role names of an input mode
            marked ``aggregated``, for example
            ``{"lsoa_code": "E01003189", "count": 12}``. Rows about individual
            people are refused.
        options: Lens options to change; each has a default.

    Returns:
        ``status`` is ``ok``, ``input_problem`` (``problems`` lists what to
        fix) or ``unknown_lens``. When ok, ``result`` is the lens result as
        plain JSON types without the rows of detail tables, and it never
        repeats an area code that was passed in.
    """
    try:
        info = engine.describe_lens(lens_id).to_dict()
    except KeyError:
        known = [lens.id for lens in engine.list_lenses()]
        return {
            "status": "unknown_lens",
            "message": "There is no lens with that id.",
            "known_lenses": known,
        }
    problems = _count_problems(info, counts)
    if problems:
        return _input_problem(problems)
    try:
        result = engine.run_lens(lens_id, counts, options=options or {})
    except engine.LensInputError as error:
        return _input_problem(error.problems)
    payload = result.to_dict(include_detail=False)
    return {
        "status": "ok",
        "result": ensure_totals_only(payload, _area_values(counts)),
        "show_with_figures": SHOW_WITH_FIGURES,
    }


def _count_problems(info: dict[str, Any], counts: object) -> list[str]:
    """What is wrong with ``counts`` for this lens, without repeating values."""
    modes = _count_modes(info)
    if not modes:
        return ["This lens cannot run on counts yet."]
    if not isinstance(counts, list) or not counts:
        return ["Pass at least one row of counts."]
    if len(counts) > MAX_COUNT_ROWS:
        return [f"Pass at most {MAX_COUNT_ROWS:,} rows of counts."]
    keys = {frozenset(row) for row in counts if isinstance(row, dict)}
    if not all(isinstance(row, dict) for row in counts):
        return ["Every row of counts must be an object keyed by role name."]
    if any(keys == {frozenset(mode["roles"])} for mode in modes):
        return []
    accepted = " or ".join("(" + ", ".join(mode["roles"]) + ")" for mode in modes)
    return [
        f"Every row must have exactly these keys: {accepted}. Rows about "
        "individual people, such as one postcode per person, are not accepted "
        "here."
    ]


def _count_modes(info: dict[str, Any]) -> list[dict[str, Any]]:
    """The input modes of a lens that take already-totalled data."""
    return [mode for mode in info.get("input_modes", []) if mode.get("aggregated")]


def _area_values(counts: list[dict[str, Any]]) -> list[str]:
    """Every text value in the rows, such as area codes, for the privacy guard."""
    return [value for row in counts for value in row.values() if isinstance(value, str)]


def _input_problem(problems: list[str]) -> dict[str, Any]:
    """An answer that tells the person what to fix."""
    return {"status": "input_problem", "problems": problems}


def _score(lens: dict[str, Any], words: set[str]) -> int:
    """How many of ``words`` appear in a lens description."""
    text = " ".join(
        str(lens.get(field, ""))
        for field in ("id", "title", "question", "summary", "coverage")
    )
    return len(words & _words(text))


def _words(text: str) -> set[str]:
    """The meaningful words of ``text``, cut to a stem so word endings match."""
    words = set(re.findall(r"[a-z0-9]+", text.casefold())) - _STOP_WORDS
    return {word[:STEM_LENGTH] for word in words}
