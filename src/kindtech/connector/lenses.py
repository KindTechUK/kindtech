"""Find a lens and run one on counts, as totals only.

These are thin wrappers over :mod:`kindtech.lenses`. They add what a chat
assistant needs: a search over the lens descriptions, a check that only
already-totalled input is accepted, and the privacy guard on what comes back.

    >>> from kindtech.connector import find_lens, run_lens_on_counts
    >>> find_lens("deprived neighbourhoods")["lenses"][0]["id"]
    'reach-deprivation'
"""

import logging
import re
from typing import Any

import requests

import kindtech.lenses as engine
from kindtech.connector.privacy import ensure_totals_only, looks_like_postcode

logger = logging.getLogger(__name__)

MAX_COUNT_ROWS = 50_000
# "deprived" and "deprivation" should match, so words are compared by stem.
STEM_LENGTH = 6

HOW_TO_RUN = (
    "Run a lens with run_lens_on_counts, passing rows that are already totals "
    "for areas or for groups (the roles of an input mode marked 'aggregated'). "
    "Never pass rows about individual people."
)
UNAVAILABLE = (
    "A data source this lens needs could not be reached just now. Try again in "
    "a minute."
)
SHOW_WITH_FIGURES = (
    "Show the checks and caveats next to the figures. The checks are for the "
    "person to answer, not for an assistant."
)

# "1200", "1,200" and "12.5". A leading zero marks a code or a phone number, not
# an amount, so "0123" is left as text.
_PLAIN_NUMBER = re.compile(r"^(0|[1-9]\d*|[1-9]\d{0,2}(,\d{3})+)(\.\d+)?$")

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
    """Run a lens on data that is already totalled by area or by group.

    Args:
        lens_id: The lens to run, for example ``"reach-deprivation"``.
        counts: One dict per area or group, keyed by the role names of an
            input mode marked ``aggregated``, for example
            ``{"lsoa_code": "E01003189", "count": 12}`` or
            ``{"group": "Black Caribbean", "count": 40}``. Rows about
            individual people are refused. A count given as text, such as
            ``"1,200"``, is read as a number.
        options: Lens options to change. Most have a default; where a lens
            needs one, such as the catchment, the answer says so.

    Returns:
        ``status`` is ``ok``, ``input_problem`` (``problems`` lists what to
        fix), ``unknown_lens`` or ``unavailable`` (a data source the lens
        needs could not be reached). When ok, ``result`` is the lens result as
        plain JSON types without the rows of detail tables. It never repeats a
        value that was passed in, except in a role the lens marks
        ``reported``: the name or code of a public place, such as a local
        authority, or one of the group names the role lists.
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
    counts = _with_amounts_as_numbers(info, counts)
    guarded = _guarded_values(info, counts)
    try:
        result = engine.run_lens(lens_id, counts, options=options or {})
    except engine.LensInputError as error:
        return ensure_totals_only(_input_problem(error.problems), guarded)
    except requests.RequestException as error:
        # The error text can hold a web address, so only its kind is logged.
        logger.warning("A data source could not be reached: %s", type(error).__name__)
        return {"status": "unavailable", "message": UNAVAILABLE}
    payload = result.to_dict(include_detail=False)
    return {
        "status": "ok",
        "result": ensure_totals_only(payload, guarded),
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


def _with_amounts_as_numbers(
    info: dict[str, Any], counts: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """The rows, with an amount that was given as text turned into a number.

    An assistant often sends ``"1200"`` for ``1200``. As text it would be
    guarded like a name, and the result would be withheld for repeating a
    total, which it does by design. Only a role that holds an amount is
    changed, and only text that is nothing but a number.
    """
    amounts = _amount_roles(info)
    return [
        {
            name: _number(value)
            if name in amounts and isinstance(value, str)
            else value
            for name, value in row.items()
        }
        for row in counts
    ]


def _amount_roles(info: dict[str, Any]) -> set[str]:
    """The roles that hold an amount, such as a count: their example is a number."""
    return {
        role["name"]
        for role in info.get("roles", [])
        if not isinstance(_number(str(role.get("example", ""))), str)
    }


def _number(text: str) -> int | float | str:
    """``text`` as a number when it is nothing but one, and unchanged otherwise."""
    cleaned = text.strip()
    if not _PLAIN_NUMBER.match(cleaned):
        return text
    cleaned = cleaned.replace(",", "")
    return float(cleaned) if "." in cleaned else int(cleaned)


def _guarded_values(info: dict[str, Any], counts: list[dict[str, Any]]) -> list[str]:
    """The text values in the rows that the result must not repeat."""
    roles = {role["name"]: role for role in info.get("roles", [])}
    return [
        value
        for row in counts
        for name, value in row.items()
        if isinstance(value, str) and not _may_come_back(roles.get(name, {}), value)
    ]


def _may_come_back(role: dict[str, Any], value: str) -> bool:
    """Whether a result may repeat ``value``, given in a column with this role.

    Only a role the lens marks ``reported`` holds names the result uses too.
    When the role lists ``reported_values``, such as the census ethnic groups,
    only those values may come back and a charity's own label is still
    guarded. When it lists none, such as for local authorities, every value
    is a public name. A value with the shape of a postcode is never one.
    """
    if not role.get("reported") or looks_like_postcode(value):
        return False
    listed = {str(item).strip().casefold() for item in role.get("reported_values", ())}
    return not listed or value.strip().casefold() in listed


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
