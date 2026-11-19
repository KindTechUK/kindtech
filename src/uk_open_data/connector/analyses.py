"""Find an analysis and run one on counts, as totals only.

These are thin wrappers over :mod:`uk_open_data.analyses`. They add what a chat
assistant needs: a search over the analysis descriptions, a check that only
already-totalled input is accepted, and the privacy guard on what comes back.

    >>> from uk_open_data.connector import find_analysis, run_analysis_on_counts
    >>> find_analysis("deprived neighbourhoods")["analyses"][0]["id"]
    'reach-deprivation'
"""

import logging
import re
from typing import Any, Literal

import requests

import uk_open_data.analyses as engine
from uk_open_data.connector.privacy import ensure_totals_only, looks_like_postcode

logger = logging.getLogger(__name__)

MAX_COUNT_ROWS = 50_000
# "deprived" and "deprivation" should match, so words are compared by stem.
STEM_LENGTH = 6

HOW_TO_RUN = (
    "Run an analysis with run_analysis_on_counts, passing rows that are already totals "
    "for areas or for groups (the roles of an input mode marked 'aggregated'). "
    "Never pass rows about individual people."
)
NEEDS_ROWS = (
    "This analysis does not run on totals, so it cannot run in a chat. It needs "
    "a row for each thing it measures, such as one row per site that says "
    "where the site is, and this tool takes totals only. Run it on the "
    "Kindtech Evidence page or with the command line tool, where those rows "
    "are not passed through an assistant. Do not try other rows or another "
    "analysis in its place without saying so."
)
UNAVAILABLE = (
    "A data source this analysis needs could not be reached just now. Try again in "
    "a minute."
)
ROWS_LEFT_OUT = (
    "These tables are not empty. Each holds a row for every area, for a map or "
    "a download, so their rows are left out of an answer in a chat. The analysis "
    "page and the command line tool show them."
)
MAP_NEEDS_ROWS = (
    "The map in the result is drawn from one of them, so it cannot be drawn from "
    "this answer."
)
WOULD_HIDE = (
    "Nothing has been shown yet. With these rows, {hidden} of the figures and "
    "table rows in the answer would come back hidden. This analysis hides a count "
    "from 1 to {highest}, to protect the people behind it. Where it hides one "
    "count in a table it hides a second, so the first cannot be worked out "
    "from the total, and that second count can be a larger number the person "
    "has just given. Tell the person this before going on and ask which of "
    "the choices they want. Do not choose for them."
)
COMBINE_FIRST = (
    "Combine first. Add each count under {below} to the count of a "
    "neighbouring area, or of a broader group, and send the rows again. Fewer "
    "counts, or none, are then hidden. Say with the figures which rows were "
    "combined, because those figures then describe the two together."
)
RUN_AS_IT_IS = (
    "Run as it is. Call again with the same rows and hidden_counts set to "
    "'accept'. The answer comes back with those counts hidden."
)
# The door a run is counted under, one of the engine's fixed list.
CHAT = "chat"
OPEN_WITH_ANSWER = (
    "Open your reply with the sentence in result.answer, in its exact words. "
    "It is the analysis's own answer to the question, and the Kindtech "
    "Evidence page and the command line tool show the same words. Then give "
    "the figures named in result.key_figures before any others."
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


def find_analysis(query: str | None = None) -> dict[str, Any]:
    """Find the analyses that answer a question.

    Args:
        query: The question in the person's own words, or a few key words.
            Leave out to list every analysis.

    Returns:
        ``analyses`` holds each analysis description (see ``AnalysisInfo`` in
        the analysis contract), best match first. ``matched`` says how many
        matched the
        query; when none did, every analysis is listed and ``note`` says so.
        ``needs_rows`` names the listed analyses that cannot run on totals, and
        so not in a chat, and says where they can run.
    """
    analyses = [info.to_dict() for info in engine.list_analyses()]
    words = _words(query or "")
    scored = sorted(
        ((_score(analysis, words), analysis) for analysis in analyses),
        key=lambda pair: pair[0],
        reverse=True,
    )
    matched = [analysis for score, analysis in scored if score > 0]
    answer: dict[str, Any] = {
        "analyses": matched or analyses,
        "matched": len(matched),
        "available": len(analyses),
        "how_to_run": HOW_TO_RUN,
    }
    needs_rows = [
        analysis["id"] for analysis in answer["analyses"] if not _count_modes(analysis)
    ]
    if needs_rows:
        answer["needs_rows"] = {"analyses": needs_rows, "note": NEEDS_ROWS}
    if not analyses:
        answer["note"] = "No analyses are installed."
    elif words and not matched:
        answer["note"] = "No analysis matched those words, so every analysis is listed."
    return answer


def run_analysis_on_counts(
    analysis_id: str,
    counts: list[dict[str, Any]],
    options: dict[str, Any] | None = None,
    hidden_counts: Literal["ask", "accept"] = "ask",
) -> dict[str, Any]:
    """Run an analysis on data that is already totalled by area or by group.

    Args:
        analysis_id: The analysis to run, for example ``"reach-deprivation"``.
        counts: One dict per area or group, keyed by the role names of an
            input mode marked ``aggregated``, for example
            ``{"lsoa_code": "E01003189", "count": 12}``,
            ``{"group": "Black Caribbean", "count": 40}`` or
            ``{"local_authority": "Lewisham", "volume": 1200}``. Rows about
            individual people, or one row per site, are refused. A count
            given as text, such as ``"1,200"``, is read as a number.
        options: Analysis options to change. Most have a default; where an analysis
            needs one, such as the catchment, the answer says so.
        hidden_counts: What to do when the answer would hide counts.
            ``"ask"`` holds the answer back and says so, so the person can
            combine small counts first; ``"accept"`` returns it with those
            counts hidden.

    Returns:
        ``status`` is ``ok``, ``would_hide_counts`` (``would_hide`` says how
        many and ``choices`` what the person can do), ``input_problem``
        (``problems`` lists what to fix), ``needs_rows`` (the analysis takes no
        totals, so it cannot run here), ``unknown_analysis`` or ``unavailable``
        (a data source the analysis needs could not be reached). When ok,
        ``result`` is the analysis result as plain JSON types without the rows of
        detail tables, and ``rows_left_out`` names those tables and says why.
        It never repeats a
        value that was passed in, except in a role the analysis marks
        ``reported``: the name or code of a public place, such as a local
        authority, or one of the group names the role lists.
    """
    return run_and_keep_result(analysis_id, counts, options, hidden_counts)[0]


def run_and_keep_result(
    analysis_id: str,
    counts: list[dict[str, Any]],
    options: dict[str, Any] | None = None,
    hidden_counts: Literal["ask", "accept"] = "ask",
) -> tuple[dict[str, Any], engine.AnalysisResult | None, list[str]]:
    """Run an analysis as :func:`run_analysis_on_counts` does, and keep what it made.

    Returns:
        The answer, then the analysis result when the status is ``ok`` (``None``
        otherwise), then the input values the answer must not repeat. The
        server draws the map from the result, which holds the rows the answer
        leaves out, so the result itself must never be sent to an assistant.
    """
    try:
        info = engine.describe_analysis(analysis_id).to_dict()
    except KeyError:
        known = [analysis.id for analysis in engine.list_analyses()]
        unknown = {
            "status": "unknown_analysis",
            "message": "There is no analysis with that id.",
            "known_analyses": known,
        }
        return unknown, None, []
    if not _count_modes(info):
        return {"status": "needs_rows", "message": NEEDS_ROWS}, None, []
    problems = _count_problems(info, counts)
    if problems:
        return _input_problem(problems), None, []
    counts = _with_amounts_as_numbers(info, counts)
    guarded = _guarded_values(info, counts)
    try:
        result = engine.run_analysis(analysis_id, counts, options=options or {})
    except engine.AnalysisInputError as error:
        problem = _input_problem(error.problems, error.option, error.role)
        return ensure_totals_only(problem, guarded), None, []
    except requests.RequestException as error:
        # The error text can hold a web address, so only its kind is logged.
        logger.warning("A data source could not be reached: %s", type(error).__name__)
        return {"status": "unavailable", "message": UNAVAILABLE}, None, []
    payload = result.to_dict(include_detail=False)
    hidden = _hidden_in_answer(payload)
    if hidden and hidden_counts != "accept":
        held_back = _would_hide_counts(hidden, payload["privacy"]["suppress_below"])
        return held_back, None, []
    answer: dict[str, Any] = {
        "status": "ok",
        "result": ensure_totals_only(payload, guarded),
        "show_with_figures": SHOW_WITH_FIGURES,
    }
    if payload.get("answer"):
        answer["open_with"] = OPEN_WITH_ANSWER
    left_out = _rows_left_out(payload)
    if left_out:
        answer["rows_left_out"] = left_out
    return answer, result, guarded


def record_chat_run(result: engine.AnalysisResult) -> None:
    """Count one answer given in a chat, by its analysis and input mode only.

    Call it once for an answer that has passed the privacy guard and is about
    to go to the person. A run that was held back, refused or withheld is not
    an answer and is not counted. The record is one line on the
    ``uk_open_data.runs`` logger, written by the engine, and nothing is sent
    anywhere.
    """
    try:
        engine.record_run(result.analysis_id, result.input_mode, CHAT)
    except (KeyError, ValueError):
        # Counting must never cost the person their answer.
        logger.warning("An answer given in a chat could not be counted.")


def _hidden_in_answer(payload: dict[str, Any]) -> int:
    """How many figures and table rows in an answer have their count hidden.

    Rows of detail tables are not counted: they are left out of an answer.
    """
    rows = [row for table in payload.get("tables", []) for row in table["rows"]]
    shown = [*payload.get("figures", []), *rows]
    return sum(1 for item in shown if item.get("suppressed"))


def _would_hide_counts(hidden: int, below: int) -> dict[str, Any]:
    """The answer given in place of a result that would hide counts.

    It holds no figure from the run and nothing from the rows, only how many
    counts would be hidden and what the person can do about it.
    """
    return {
        "status": "would_hide_counts",
        "message": WOULD_HIDE.format(hidden=hidden, highest=below - 1),
        "would_hide": {"figures_and_rows": hidden, "counts_below": below},
        "choices": [COMBINE_FIRST.format(below=below), RUN_AS_IT_IS],
    }


def _rows_left_out(payload: dict[str, Any]) -> dict[str, Any]:
    """Which tables came back without their rows, and why, or nothing.

    A detail table holds a row for every area. It comes back with its columns
    and no rows, which reads like "nothing found" unless the answer says so.
    """
    tables = [table["id"] for table in payload.get("tables", []) if table.get("detail")]
    if not tables:
        return {}
    note = ROWS_LEFT_OUT
    if (payload.get("map") or {}).get("table") in tables:
        note = f"{note} {MAP_NEEDS_ROWS}"
    return {"tables": tables, "note": note}


def _count_problems(info: dict[str, Any], counts: object) -> list[str]:
    """What is wrong with ``counts`` for this analysis, without repeating values."""
    modes = _count_modes(info)
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
        f"Every row must have exactly these keys: {accepted}. Rows that are "
        "not totals, such as one postcode per person or per site, are not "
        "accepted here."
    ]


def _count_modes(info: dict[str, Any]) -> list[dict[str, Any]]:
    """The input modes of an analysis that take already-totalled data."""
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
    """The roles the analysis marks as holding an amount, such as a count."""
    return {role["name"] for role in info.get("roles", []) if role.get("amount")}


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

    Only a role the analysis marks ``reported`` holds names the result uses too.
    When the role lists ``reported_values``, such as the census ethnic groups,
    only those values may come back and a charity's own label is still
    guarded. When it lists none, such as for local authorities, every value
    is a public name. A value with the shape of a postcode is never one.
    """
    if not role.get("reported") or looks_like_postcode(value):
        return False
    listed = {str(item).strip().casefold() for item in role.get("reported_values", ())}
    return not listed or value.strip().casefold() in listed


def _input_problem(
    problems: list[str], option: str | None = None, role: str | None = None
) -> dict[str, Any]:
    """An answer that tells the person what to fix.

    The sentences name an option by the label a person reads. ``option`` and
    ``role`` are the code names an assistant passes, given when the analysis
    says which one the problem is about, so it need not match words.
    """
    answer: dict[str, Any] = {"status": "input_problem", "problems": problems}
    if option:
        answer["option"] = option
    if role:
        answer["role"] = role
    return answer


def _score(analysis: dict[str, Any], words: set[str]) -> int:
    """How many of ``words`` appear in an analysis description."""
    text = " ".join(
        str(analysis.get(field, ""))
        for field in ("id", "title", "question", "summary", "coverage")
    )
    return len(words & _words(text))


def _words(text: str) -> set[str]:
    """The meaningful words of ``text``, cut to a stem so word endings match."""
    words = set(re.findall(r"[a-z0-9]+", text.casefold())) - _STOP_WORDS
    return {word[:STEM_LENGTH] for word in words}
