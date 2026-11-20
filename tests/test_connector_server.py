"""Tests for the connector's server: the tools an assistant sees."""

import asyncio
import json
import logging
import sys
from typing import Any

import pytest

pytest.importorskip("mcp")

from mcp import Client  # noqa: E402

from uk_open_data.analyses import DOORS, RUNS_LOGGER  # noqa: E402
from uk_open_data.connector import (  # noqa: E402
    PrivacyError,
    analyses,
    build_server,
    command,
)

TOOLS = {"find_analysis", "describe_place", "run_analysis_on_counts"}


def _tools() -> dict[str, dict[str, Any]]:
    """Each tool as listed to an assistant, by name."""

    async def listed() -> dict[str, dict[str, Any]]:
        async with Client(build_server()) as client:
            tools = (await client.list_tools()).tools
        return {
            tool.name: tool.model_dump(mode="json", by_alias=True) for tool in tools
        }

    return asyncio.run(listed())


def _call(tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Call a tool as an assistant would."""

    async def call() -> dict[str, Any]:
        async with Client(build_server()) as client:
            reply = await client.call_tool(tool, arguments)
        return reply.model_dump(mode="json", by_alias=True)

    return asyncio.run(call())


def test_tools_offered() -> None:
    assert set(_tools()) == TOOLS


def test_every_tool_is_marked_read_only() -> None:
    for name, tool in _tools().items():
        annotations = tool["annotations"]
        assert annotations["readOnlyHint"] is True, name
        assert annotations["destructiveHint"] is False, name
        assert annotations["idempotentHint"] is True, name
        assert tool["title"], name
        assert len(tool["description"]) > 80, name


def test_only_tools_that_read_open_data_are_open_world() -> None:
    tools = _tools()

    assert tools["find_analysis"]["annotations"]["openWorldHint"] is False
    assert tools["describe_place"]["annotations"]["openWorldHint"] is True
    assert tools["run_analysis_on_counts"]["annotations"]["openWorldHint"] is True


def test_every_argument_is_described() -> None:
    for name, tool in _tools().items():
        for argument, schema in tool["inputSchema"]["properties"].items():
            assert schema.get("description"), f"{name}.{argument}"


def test_the_run_tool_asks_before_hiding_counts_unless_told_to_accept() -> None:
    hidden_counts = _tools()["run_analysis_on_counts"]["inputSchema"]["properties"][
        "hidden_counts"
    ]

    assert hidden_counts["enum"] == ["ask", "accept"]
    assert hidden_counts["default"] == "ask"


@pytest.mark.usefixtures("england")
def test_a_run_that_would_hide_counts_is_held_back_through_the_server() -> None:
    counts = [
        {"lsoa_code": "E01000001", "count": 3},
        {"lsoa_code": "E01000002", "count": 30},
    ]
    arguments = {"analysis_id": "reach-deprivation", "counts": counts}

    asked = _call("run_analysis_on_counts", arguments)
    accepted = _call("run_analysis_on_counts", {**arguments, "hidden_counts": "accept"})

    assert asked["isError"] is False
    assert asked["structuredContent"]["status"] == "would_hide_counts"
    assert "result" not in asked["structuredContent"]
    assert accepted["structuredContent"]["status"] == "ok"


def test_the_assistant_is_told_to_open_with_the_answer() -> None:
    description = " ".join(_tools()["run_analysis_on_counts"]["description"].split())

    assert "Open with the answer" in (build_server().instructions or "")
    assert "Open your reply with result.answer in its exact words" in description


def test_an_assistant_is_told_when_to_show_the_code_and_exact_values() -> None:
    description = " ".join(_tools()["run_analysis_on_counts"]["description"].split())
    instructions = build_server().instructions or ""

    assert "'exact' value and result.code" in description
    assert "asks for the code" in description
    assert "Quote each figure as it is shown, rounded." in instructions
    assert "asks for the code" in instructions


@pytest.mark.usefixtures("england")
def test_describe_place_through_the_server() -> None:
    reply = _call("describe_place", {"place": "Lewisham"})

    assert reply["isError"] is False
    assert reply["structuredContent"]["place"]["code"] == "E09000023"
    assert json.loads(reply["content"][0]["text"]) == reply["structuredContent"]


def test_find_analysis_through_the_server() -> None:
    reply = _call("find_analysis", {"query": "deprived neighbourhoods"})

    assert reply["structuredContent"]["analyses"][0]["id"] == "reach-deprivation"


def test_argument_errors_name_the_argument_only() -> None:
    reply = _call("describe_place", {"place": ["Somewhere"]})

    assert reply["isError"] is True
    assert reply["content"][0]["text"] == (
        "The arguments for describe_place did not fit: place: string type."
    )


def test_missing_argument_is_named() -> None:
    reply = _call("run_analysis_on_counts", {"counts": [{"lsoa_code": "E01000001"}]})

    assert reply["content"][0]["text"] == (
        "The arguments for run_analysis_on_counts did not fit: analysis_id: missing."
    )


# An error text of the kind an analysis or a download can raise: it quotes a web
# address and a value from the rows.
CRASH_TEXT = "could not read https://example.invalid/?geography=ZZ999KC for 'Zebedee'"


@pytest.mark.parametrize(
    ("tool", "arguments", "target"),
    [
        (
            "run_analysis_on_counts",
            {
                "analysis_id": "reach-deprivation",
                "counts": [{"lsoa_code": "E01000001"}],
            },
            "uk_open_data.connector.server.run_and_keep_result",
        ),
        (
            "describe_place",
            {"place": "Lewisham"},
            "uk_open_data.connector.server.describe_place",
        ),
    ],
)
def test_a_crash_keeps_its_text_from_the_assistant_and_the_log(
    tool: str,
    arguments: dict[str, Any],
    target: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def crash(*args: object, **kwargs: object) -> None:
        raise RuntimeError(CRASH_TEXT)

    monkeypatch.setattr(target, crash)
    caplog.set_level("DEBUG")

    reply = _call(tool, arguments)

    assert reply["isError"] is True
    assert reply["content"][0]["text"] == f"Error executing tool {tool}"
    seen = json.dumps(reply) + caplog.text
    assert "ZZ999KC" not in seen
    assert "Zebedee" not in seen
    # The log still says which tool stopped, with what, and where.
    assert f"Tool {tool} stopped with RuntimeError" in caplog.text
    assert "in crash" in caplog.text


def test_a_crash_is_not_linked_to_the_error_that_is_logged(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A log formatter that follows an error's links must not reach the crash."""

    def crash(*args: object, **kwargs: object) -> None:
        raise RuntimeError(CRASH_TEXT)

    monkeypatch.setattr("uk_open_data.connector.server.describe_place", crash)

    _call("describe_place", {"place": "Lewisham"})

    logged = [record.exc_info[1] for record in caplog.records if record.exc_info]
    assert logged
    for error in logged:
        assert error.__cause__ is None
        assert error.__context__ is None


def test_the_guards_own_message_is_kept_in_the_log(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def withheld(*args: object, **kwargs: object) -> None:
        raise PrivacyError("A value from the input rows appeared at: warnings[0].")

    monkeypatch.setattr("uk_open_data.connector.server.run_and_keep_result", withheld)

    reply = _call("run_analysis_on_counts", {"analysis_id": "x", "counts": [{"a": 1}]})

    assert reply["content"][0]["text"] == "Error executing tool run_analysis_on_counts"
    assert "stopped with PrivacyError: A value from the input rows" in caplog.text


REACH_COUNTS = [
    {"lsoa_code": "E01000001", "count": 12},
    {"lsoa_code": "E01000002", "count": 30},
]
SMALL_REACH_COUNTS = [
    {"lsoa_code": "E01000001", "count": 3},
    {"lsoa_code": "E01000002", "count": 30},
    {"lsoa_code": "E01000003", "count": 40},
]


def _runs_counted(caplog: pytest.LogCaptureFixture) -> list[str]:
    """The lines written to the logger a host counts answers from."""
    return [
        record.getMessage() for record in caplog.records if record.name == RUNS_LOGGER
    ]


@pytest.mark.usefixtures("england")
class TestAnswersGivenAreCounted:
    """One line for each answer that reaches the person, and for nothing else."""

    def test_an_answer_is_counted_once_with_no_word_from_the_rows(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level("INFO")

        reply = _call(
            "run_analysis_on_counts",
            {"analysis_id": "reach-deprivation", "counts": REACH_COUNTS},
        )

        assert reply["structuredContent"]["status"] == "ok"
        assert _runs_counted(caplog) == [
            "run analysis=reach-deprivation mode=neighbourhood_counts door=chat"
        ]

    def test_an_answer_held_back_is_not_counted_until_it_is_given(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level("INFO")
        arguments = {"analysis_id": "reach-deprivation", "counts": SMALL_REACH_COUNTS}

        held_back = _call("run_analysis_on_counts", arguments)

        assert held_back["structuredContent"]["status"] == "would_hide_counts"
        assert _runs_counted(caplog) == []

        _call("run_analysis_on_counts", {**arguments, "hidden_counts": "accept"})

        assert len(_runs_counted(caplog)) == 1

    def test_a_refused_run_is_not_counted(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level("INFO")

        reply = _call(
            "run_analysis_on_counts",
            {"analysis_id": "reach-deprivation", "counts": [{"postcode": "ZZ99 9KC"}]},
        )

        assert reply["structuredContent"]["status"] == "input_problem"
        assert _runs_counted(caplog) == []

    def test_an_answer_still_goes_out_when_it_cannot_be_counted(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        def refuse(*args: object) -> None:
            raise ValueError("This analysis has no input mode of that name.")

        monkeypatch.setattr("uk_open_data.analyses.record_run", refuse)

        reply = _call(
            "run_analysis_on_counts",
            {"analysis_id": "reach-deprivation", "counts": REACH_COUNTS},
        )

        assert reply["isError"] is False
        assert reply["structuredContent"]["status"] == "ok"
        assert "could not be counted" in caplog.text


@pytest.mark.usefixtures("leaky_analysis_engine")
def test_an_answer_the_guard_withholds_is_not_counted() -> None:
    reply = _call(
        "run_analysis_on_counts",
        {"analysis_id": "reach-deprivation", "counts": REACH_COUNTS},
    )

    assert reply["isError"] is True
    assert analyses.engine.runs == []


@pytest.mark.usefixtures("analysis_engine")
def test_the_count_takes_its_words_from_the_result() -> None:
    _call(
        "run_analysis_on_counts",
        {"analysis_id": "reach-deprivation", "counts": REACH_COUNTS},
    )

    assert analyses.engine.runs == [
        ("reach-deprivation", "neighbourhood_counts", "chat")
    ]


def test_chat_is_a_door_the_engine_counts() -> None:
    assert analyses.CHAT in DOORS


def test_the_command_keeps_the_count_whatever_the_log_level(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Server:
        def run(self, *args: Any, **kwargs: Any) -> None:
            return None

    monkeypatch.setattr("uk_open_data.connector.build_server", Server)
    runs = logging.getLogger(RUNS_LOGGER)
    before = runs.level
    runs.setLevel(logging.WARNING)

    command.main(["--log-level", "ERROR"])

    try:
        assert runs.isEnabledFor(logging.INFO)
    finally:
        runs.setLevel(before)


@pytest.mark.parametrize(
    ("prog", "shown"),
    [
        ({}, "usage: python -m uk_open_data.connector"),
        ({"prog": "uk-open-data connector"}, "usage: uk-open-data connector"),
    ],
)
def test_help_names_the_command_that_started_it(
    prog: dict[str, str], shown: str, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit):
        command.main(["--help"], **prog)

    assert capsys.readouterr().out.startswith(shown)


def test_a_missing_extra_ends_the_command_with_one_sentence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # As when the mcp package is not installed.
    monkeypatch.setitem(sys.modules, "uk_open_data.connector.server", None)
    monkeypatch.setattr(sys, "argv", ["python -m uk_open_data.connector"])

    with pytest.raises(SystemExit) as stopped:
        command.start()

    said = str(stopped.value)
    assert said.startswith("The connector server needs the 'connector' extra.")
    assert 'uv add "uk-open-data[connector]"' in said
    assert 'pip install "uk-open-data[connector]"' in said
    # No traceback is chained to it for Python to print.
    assert stopped.value.__cause__ is None
    assert stopped.value.__suppress_context__ is True


def test_command_defaults_to_stdio(monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[tuple[Any, ...]] = []

    class Server:
        def run(self, *args: Any, **kwargs: Any) -> None:
            ran.append((args, kwargs))

    monkeypatch.setattr("uk_open_data.connector.build_server", Server)

    command.main([])
    command.main(["--transport", "streamable-http", "--port", "9000"])

    assert ran[0] == (("stdio",), {})
    assert ran[1][0] == ("streamable-http",)
    assert ran[1][1]["port"] == 9000
    assert ran[1][1]["stateless_http"] is True
