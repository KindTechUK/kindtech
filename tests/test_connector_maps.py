"""Tests for the map a chat can show with an analysis result.

The outlines are invented squares, so nothing is fetched. The map is drawn by
the real first analysis on the small England.
"""

import asyncio
import json
import logging
import threading
from typing import Any

import connector_fakes as fakes
import pytest
import requests

pytest.importorskip("mcp")

from mcp import Client  # noqa: E402

from uk_open_data import cli  # noqa: E402
from uk_open_data.analyses import need_reach, run_analysis  # noqa: E402
from uk_open_data.connector import build_server, command, maps  # noqa: E402
from uk_open_data.connector.maps import (  # noqa: E402
    MAP_META_KEY,
    MAP_VIEW,
    MAP_VIEW_URI,
    picture_for,
)

pytestmark = pytest.mark.usefixtures("england")


COUNTS = [
    {"lsoa_code": "E01000001", "count": 12},
    {"lsoa_code": "E01000002", "count": 30},
]
RUN = {"analysis_id": "reach-deprivation", "counts": COUNTS}
APP_MIME_TYPE = "text/html;profile=mcp-app"


def _call(arguments: dict[str, Any], **server: Any) -> dict[str, Any]:
    """Run an analysis through the server as an app would; return the whole reply."""

    async def call() -> dict[str, Any]:
        async with Client(build_server(**server)) as client:
            reply = await client.call_tool("run_analysis_on_counts", arguments)
        return reply.model_dump(mode="json", by_alias=True)

    return asyncio.run(call())


def _for_the_model(reply: dict[str, Any]) -> str:
    """Everything in a reply that a model is given: its text and its structure."""
    return json.dumps([reply["content"], reply["structuredContent"]])


class TestThePicture:
    def test_every_layer_is_drawn_as_a_picture(self) -> None:
        result = run_analysis("reach-deprivation", COUNTS)

        picture, note = picture_for(result, boundaries=fakes.square_outlines)

        assert picture is not None
        assert picture["title"] == result.map.title
        assert [layer["id"] for layer in picture["layers"]] == [
            layer.id for layer in result.map.layers
        ]
        assert all(layer["svg"].startswith("<svg") for layer in picture["layers"])
        assert "was drawn for the person" in note
        assert "do not describe what it shows" in note

    def test_an_analysis_without_a_map_has_no_picture_and_no_note(self) -> None:
        result = run_analysis(
            "reach-deprivation", COUNTS, options={"catchment": "England"}
        )

        assert picture_for(result, boundaries=fakes.square_outlines) == (None, "")

    def test_outlines_that_cannot_be_fetched_leave_the_figures_alone(self) -> None:
        result = run_analysis("reach-deprivation", COUNTS)

        picture, note = picture_for(result)

        assert picture is None
        assert note == maps.NO_OUTLINES

    def test_outlines_that_match_no_area_are_treated_the_same(self) -> None:
        result = run_analysis("reach-deprivation", COUNTS)
        empty = {"type": "FeatureCollection", "features": []}

        assert picture_for(result, boundaries=lambda _: empty) == (
            None,
            maps.NO_OUTLINES,
        )

    def test_outlines_that_give_nothing_are_treated_the_same(self) -> None:
        result = run_analysis("reach-deprivation", COUNTS)

        assert picture_for(result, boundaries=lambda _: None) == (
            None,
            maps.NO_OUTLINES,
        )

    def test_slow_outlines_do_not_keep_the_figures_waiting(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result = run_analysis("reach-deprivation", COUNTS)
        let_go = threading.Event()
        fetched: list[str] = []

        def slow(result: Any) -> dict[str, Any]:
            let_go.wait(timeout=5)
            fetched.append("done")
            return fakes.square_outlines(result)

        monkeypatch.setattr(maps, "MAP_SECONDS", 0.05)

        picture, note = picture_for(result, boundaries=slow)

        assert picture is None
        assert note == maps.TOO_SLOW
        # The fetch is left to finish and not stopped when the answer goes out.
        assert fetched == []
        let_go.set()

    def test_outlines_that_arrive_in_time_are_drawn(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result = run_analysis("reach-deprivation", COUNTS)
        monkeypatch.setattr(maps, "MAP_SECONDS", 5)

        picture, note = picture_for(result, boundaries=fakes.square_outlines)

        assert picture is not None
        assert note.startswith("A map of this result was drawn")

    def test_a_chat_asks_for_the_quick_outlines(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result = run_analysis("reach-deprivation", COUNTS)
        asked: list[dict[str, Any]] = []

        def loader(result: Any, **how: Any) -> dict[str, Any]:
            asked.append(how)
            return fakes.square_outlines(result)

        monkeypatch.setattr(maps, "load_map_boundaries", loader)

        picture, _ = picture_for(result)

        assert picture is not None
        assert asked == [{"fine": False}]

    def test_outlines_passed_in_are_asked_for_as_they_are(self) -> None:
        result = run_analysis("reach-deprivation", COUNTS)
        asked: list[tuple[Any, ...]] = []

        def kept(*given: Any) -> dict[str, Any]:
            asked.append(given)
            return fakes.square_outlines(result)

        picture_for(result, boundaries=kept)

        assert asked == [(result,)]

    def test_a_picture_that_repeats_an_input_value_is_withheld(self) -> None:
        result = run_analysis("reach-deprivation", COUNTS)

        # The picture names each neighbourhood, so a name stands in for a value
        # from the rows.
        picture, note = picture_for(
            result, guarded=["Lewisham 001A"], boundaries=fakes.square_outlines
        )

        assert picture is None
        assert note == maps.WITHHELD

    def test_layers_past_the_size_limit_are_left_out(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result = run_analysis("reach-deprivation", COUNTS)
        whole, _ = picture_for(result, boundaries=fakes.square_outlines)
        assert whole is not None
        first = len(whole["layers"][0]["svg"].encode())

        monkeypatch.setattr(maps, "MAX_PICTURE_BYTES", first)
        one, _ = picture_for(result, boundaries=fakes.square_outlines)
        monkeypatch.setattr(maps, "MAX_PICTURE_BYTES", first - 1)
        none, note = picture_for(result, boundaries=fakes.square_outlines)

        assert one is not None
        assert len(one["layers"]) == 1
        assert none is None
        assert note == maps.TOO_LARGE


class TestThroughTheServer:
    def test_the_run_tool_points_an_app_at_the_map_view(self) -> None:
        async def listed() -> dict[str, Any]:
            async with Client(build_server()) as client:
                tools = (await client.list_tools()).tools
            return {
                tool.name: tool.model_dump(mode="json", by_alias=True) for tool in tools
            }

        tools = asyncio.run(listed())

        assert tools["run_analysis_on_counts"]["_meta"]["ui"] == {
            "resourceUri": MAP_VIEW_URI
        }
        assert (
            "_meta" not in tools["find_analysis"] or not tools["find_analysis"]["_meta"]
        )

    def test_the_map_view_is_served_as_an_app_page(self) -> None:
        async def read() -> dict[str, Any]:
            async with Client(build_server()) as client:
                reply = await client.read_resource(MAP_VIEW_URI)
            return reply.model_dump(mode="json", by_alias=True)

        (page,) = asyncio.run(read())["contents"]

        assert page["mimeType"] == APP_MIME_TYPE
        assert page["text"] == MAP_VIEW

    def test_the_picture_travels_beside_the_answer_and_not_in_it(self) -> None:
        reply = _call(RUN, map_boundaries=fakes.square_outlines)

        picture = reply["_meta"][MAP_META_KEY]
        answer = reply["structuredContent"]
        assert [layer["id"] for layer in picture["layers"]] == ["deprivation", "people"]
        assert answer["status"] == "ok"
        assert answer["map"]["drawn"] is True
        assert "<svg" not in _for_the_model(reply)
        assert "<path" not in _for_the_model(reply)
        assert json.loads(reply["content"][0]["text"]) == answer

    def test_the_model_is_given_no_row_of_the_table_the_map_is_drawn_from(self) -> None:
        reply = _call(RUN, map_boundaries=fakes.square_outlines)

        # The picture names every neighbourhood. The answer names none.
        assert "Lewisham 001A" in json.dumps(reply["_meta"])
        assert "Lewisham 001A" not in _for_the_model(reply)

    def test_no_outlines_means_no_picture_and_the_answer_says_so(self) -> None:
        reply = _call(RUN)

        assert MAP_META_KEY not in (reply.get("_meta") or {})
        assert reply["structuredContent"]["status"] == "ok"
        assert reply["structuredContent"]["map"] == {
            "drawn": False,
            "note": maps.NO_OUTLINES,
        }

    def test_slow_outlines_mean_the_answer_goes_out_and_says_why(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        let_go = threading.Event()

        def slow(result: Any) -> dict[str, Any]:
            let_go.wait(timeout=5)
            return fakes.square_outlines(result)

        monkeypatch.setattr(maps, "MAP_SECONDS", 0.05)

        reply = _call(RUN, map_boundaries=slow)
        let_go.set()

        answer = reply["structuredContent"]
        assert answer["status"] == "ok"
        assert answer["result"]["figures"]
        assert answer["map"] == {"drawn": False, "note": maps.TOO_SLOW}
        assert MAP_META_KEY not in (reply.get("_meta") or {})

    def test_an_unreachable_boundary_service_is_not_named_in_the_log(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        def down(result: object) -> dict[str, Any]:
            raise requests.ConnectionError("https://example.invalid/E01000001")

        with caplog.at_level("WARNING"):
            _call(RUN, map_boundaries=down)

        assert "ConnectionError" in caplog.text
        assert "example.invalid" not in caplog.text

    def test_the_boundary_codes_own_error_lines_are_said_plainly(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        asking = logging.getLogger(f"{maps.OUTLINES_LOGGER}.api")
        address = "https://example.invalid/query?where=LSOA21CD IN ('E01000001')"

        maps.keep_addresses_out_of_the_log()
        maps.keep_addresses_out_of_the_log()
        with caplog.at_level("WARNING"):
            asking.error("Error querying ArcGIS service: %s", address)

        assert [record.getMessage() for record in caplog.records] == [
            maps.LINE_LEFT_OUT
        ]
        assert caplog.records[0].levelname == "ERROR"
        assert "example.invalid" not in caplog.text
        assert "E01000001" not in caplog.text

    def test_the_command_guards_its_log_before_it_serves(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        outlines_log = logging.getLogger(maps.OUTLINES_LOGGER)

        class Server:
            def run(self, *args: Any, **kwargs: Any) -> None:
                with caplog.at_level("WARNING"):
                    outlines_log.error("asked %s", "https://example.invalid/E01000001")

        monkeypatch.setattr("uk_open_data.connector.build_server", Server)

        command.main([])

        assert "example.invalid" not in caplog.text
        assert maps.LINE_LEFT_OUT in caplog.text

    def test_the_logger_guarded_is_the_one_the_command_line_quiets(self) -> None:
        assert maps.OUTLINES_LOGGER == cli.OUTLINES_LOGGER

    def test_a_result_held_back_has_no_map(self) -> None:
        small = [{"lsoa_code": "E01000001", "count": 3}, *COUNTS[1:]]

        reply = _call({**RUN, "counts": small}, map_boundaries=fakes.square_outlines)

        assert reply["structuredContent"]["status"] == "would_hide_counts"
        assert "map" not in reply["structuredContent"]
        assert MAP_META_KEY not in (reply.get("_meta") or {})

    def test_an_analysis_without_a_map_says_nothing_of_one(self) -> None:
        need_reach.keep_need_figures("residents", fakes.NEED, "invented for a test.")
        whole_country = {**RUN, "options": {"catchment": "England"}}

        reply = _call(whole_country, map_boundaries=fakes.square_outlines)

        assert reply["structuredContent"]["status"] == "ok"
        assert "map" not in reply["structuredContent"]
        assert MAP_META_KEY not in (reply.get("_meta") or {})


class TestTheMapView:
    """The page is checked as text here; a browser runs it in the design review."""

    def test_it_fetches_nothing(self) -> None:
        assert "http://" not in MAP_VIEW
        assert "https://" not in MAP_VIEW
        assert "fetch(" not in MAP_VIEW

    def test_it_speaks_the_app_protocol(self) -> None:
        for message in (
            "ui/initialize",
            "ui/notifications/initialized",
            "ui/notifications/tool-result",
            "ui/notifications/size-changed",
        ):
            assert message in MAP_VIEW

    def test_it_reads_the_picture_from_where_the_server_puts_it(self) -> None:
        assert f'const KEY = "{MAP_META_KEY}";' in MAP_VIEW
