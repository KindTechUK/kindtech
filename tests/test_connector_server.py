"""Tests for the connector's server: the tools an assistant sees."""

import asyncio
import json
from typing import Any

import pytest

pytest.importorskip("mcp")

from mcp import Client  # noqa: E402

from kindtech.connector import PrivacyError, build_server, command  # noqa: E402

TOOLS = {"find_lens", "describe_place", "run_lens_on_counts"}


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

    assert tools["find_lens"]["annotations"]["openWorldHint"] is False
    assert tools["describe_place"]["annotations"]["openWorldHint"] is True
    assert tools["run_lens_on_counts"]["annotations"]["openWorldHint"] is True


def test_every_argument_is_described() -> None:
    for name, tool in _tools().items():
        for argument, schema in tool["inputSchema"]["properties"].items():
            assert schema.get("description"), f"{name}.{argument}"


@pytest.mark.usefixtures("england")
def test_describe_place_through_the_server() -> None:
    reply = _call("describe_place", {"place": "Lewisham"})

    assert reply["isError"] is False
    assert reply["structuredContent"]["place"]["code"] == "E09000023"
    assert json.loads(reply["content"][0]["text"]) == reply["structuredContent"]


def test_find_lens_through_the_server() -> None:
    reply = _call("find_lens", {"query": "deprived neighbourhoods"})

    assert reply["structuredContent"]["lenses"][0]["id"] == "reach-deprivation"


def test_argument_errors_name_the_argument_only() -> None:
    reply = _call("describe_place", {"place": ["Somewhere"]})

    assert reply["isError"] is True
    assert reply["content"][0]["text"] == (
        "The arguments for describe_place did not fit: place: string type."
    )


def test_missing_argument_is_named() -> None:
    reply = _call("run_lens_on_counts", {"counts": [{"lsoa_code": "E01000001"}]})

    assert reply["content"][0]["text"] == (
        "The arguments for run_lens_on_counts did not fit: lens_id: missing."
    )


# An error text of the kind a lens or a download can raise: it quotes a web
# address and a value from the rows.
CRASH_TEXT = "could not read https://example.invalid/?geography=ZZ999KC for 'Zebedee'"


@pytest.mark.parametrize(
    ("tool", "arguments", "target"),
    [
        (
            "run_lens_on_counts",
            {"lens_id": "reach-deprivation", "counts": [{"lsoa_code": "E01000001"}]},
            "kindtech.connector.server.run_lens_on_counts",
        ),
        (
            "describe_place",
            {"place": "Lewisham"},
            "kindtech.connector.server.describe_place",
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

    monkeypatch.setattr("kindtech.connector.server.describe_place", crash)

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

    monkeypatch.setattr("kindtech.connector.server.run_lens_on_counts", withheld)

    reply = _call("run_lens_on_counts", {"lens_id": "x", "counts": [{"a": 1}]})

    assert reply["content"][0]["text"] == "Error executing tool run_lens_on_counts"
    assert "stopped with PrivacyError: A value from the input rows" in caplog.text


def test_command_defaults_to_stdio(monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[tuple[Any, ...]] = []

    class Server:
        def run(self, *args: Any, **kwargs: Any) -> None:
            ran.append((args, kwargs))

    monkeypatch.setattr("kindtech.connector.build_server", Server)

    command.main([])
    command.main(["--transport", "streamable-http", "--port", "9000"])

    assert ran[0] == (("stdio",), {})
    assert ran[1][0] == ("streamable-http",)
    assert ran[1][1]["port"] == 9000
    assert ran[1][1]["stateless_http"] is True
