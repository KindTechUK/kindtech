"""The privacy test: no row-level value may reach a tool result.

Every tool is called through the Model Context Protocol, the way an assistant
calls it, with arguments that hold values standing in for rows about people.
The whole reply, errors included, is searched for those values. A tool added
without a case here fails the first test.
"""

import asyncio
import json
from typing import Any

import connector_fakes as fakes
import pytest

pytest.importorskip("mcp")

from mcp import Client  # noqa: E402

from kindtech.connector import (  # noqa: E402
    PrivacyError,
    build_server,
    ensure_totals_only,
    places,
)
from kindtech.connector.privacy import find_row_values  # noqa: E402

POSTCODE = fakes.SECRET_POSTCODE
PERSON = "Zebedee Quillfeather"
AREA = "E01000001"

# tool name -> cases of (arguments, values that must not come back)
CASES: dict[str, list[tuple[dict[str, Any], list[str]]]] = {
    "find_lens": [
        ({"query": f"deprived areas for {PERSON} at {POSTCODE}"}, [PERSON, POSTCODE]),
        ({"query": [POSTCODE]}, [POSTCODE]),
    ],
    "describe_place": [
        ({"place": POSTCODE}, [POSTCODE]),
        ({"place": POSTCODE.lower().replace(" ", "")}, [POSTCODE]),
        ({"place": [POSTCODE]}, [POSTCODE]),
        ({"place": PERSON}, [PERSON]),
        ({}, []),
    ],
    "run_lens_on_counts": [
        (
            {
                "lens_id": "reach-deprivation",
                "counts": [{"lsoa_code": AREA, "count": 12}],
            },
            [AREA],
        ),
        (
            # Too few people for the lens to give figures at all.
            {
                "lens_id": "reach-deprivation",
                "counts": [{"lsoa_code": AREA, "count": 3}],
            },
            [AREA],
        ),
        (
            {"lens_id": "reach-deprivation", "counts": [{"postcode": POSTCODE}]},
            [POSTCODE],
        ),
        (
            {
                "lens_id": "reach-deprivation",
                "counts": [{"lsoa_code": AREA, "count": 3, "name": PERSON}],
            },
            [AREA, PERSON],
        ),
        ({"lens_id": "reach-deprivation", "counts": POSTCODE}, [POSTCODE]),
        ({"counts": [{"postcode": POSTCODE, "name": PERSON}]}, [POSTCODE, PERSON]),
        (
            {
                "lens_id": PERSON,
                "counts": [{"lsoa_code": AREA, "count": 3}],
                "options": PERSON,
            },
            [AREA, PERSON],
        ),
    ],
}


@pytest.fixture(autouse=True)
def _stand_ins(england: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every case runs the real lenses against the small England."""
    monkeypatch.setattr(
        places, "lookup_postcodes", lambda postcode: fakes.postcode_frame(AREA)
    )


def _call(tool: str, arguments: dict[str, Any]) -> str:
    """Call a tool as an assistant would and return the whole reply as text."""

    async def call() -> str:
        async with Client(build_server()) as client:
            reply = await client.call_tool(tool, arguments)
        return json.dumps(reply.model_dump(mode="json", by_alias=True))

    return asyncio.run(call())


def _squash(text: str) -> str:
    """Lower-case ``text`` and drop spaces, so "se13 7vc" matches "SE137VC"."""
    return "".join(text.split()).lower()


def test_every_tool_has_a_privacy_case() -> None:
    async def names() -> set[str]:
        async with Client(build_server()) as client:
            return {tool.name for tool in (await client.list_tools()).tools}

    assert asyncio.run(names()) == set(CASES)


@pytest.mark.parametrize(
    ("tool", "arguments", "row_values"),
    [(tool, *case) for tool, cases in CASES.items() for case in cases],
)
def test_no_row_value_reaches_a_tool_result(
    tool: str, arguments: dict[str, Any], row_values: list[str]
) -> None:
    reply = _squash(_call(tool, arguments))

    for value in row_values:
        assert _squash(value) not in reply


def test_good_calls_still_answer() -> None:
    """Guard against the test above passing because every call failed."""
    place = json.loads(_call("describe_place", {"place": POSTCODE}))
    run = json.loads(
        _call(
            "run_lens_on_counts",
            {
                "lens_id": "reach-deprivation",
                "counts": [{"lsoa_code": AREA, "count": 12}],
            },
        )
    )

    assert place["isError"] is False
    assert place["structuredContent"]["status"] == "found"
    assert run["isError"] is False
    assert run["structuredContent"]["status"] == "ok"


@pytest.mark.usefixtures("leaky_lens_engine")
def test_a_lens_that_repeats_input_is_stopped_at_the_connector() -> None:
    arguments = {
        "lens_id": "reach-deprivation",
        "counts": [{"lsoa_code": AREA, "count": 3}],
    }

    reply = json.loads(_call("run_lens_on_counts", arguments))

    assert reply["isError"] is True
    assert AREA not in json.dumps(reply)


def test_every_answer_says_it_holds_no_rows() -> None:
    for tool, arguments in [
        ("describe_place", {"place": "Lewisham"}),
        ("describe_place", {"place": "Newcastle"}),
    ]:
        answer = json.loads(_call(tool, arguments))["structuredContent"]
        assert answer["privacy"]["row_level_output"] is False


class TestGuard:
    def test_passes_totals_through_unchanged(self) -> None:
        payload = {"figures": [{"value": 12}], "privacy": {"row_level_output": False}}

        assert ensure_totals_only(payload, ["SE13 7VC"]) is payload

    def test_refuses_a_result_marked_row_level(self) -> None:
        with pytest.raises(PrivacyError, match="row-level"):
            ensure_totals_only({"privacy": {"row_level_output": True}})

    @pytest.mark.parametrize(
        "payload",
        [
            {"warnings": ["Postcode se137vc was not found"]},
            {"tables": [{"rows": [{"area": "SE13 7VC", "people": 1}]}]},
            {"figures": {"SE13 7VC": 1}},
        ],
    )
    def test_refuses_a_row_value_anywhere(self, payload: dict[str, Any]) -> None:
        with pytest.raises(PrivacyError) as raised:
            ensure_totals_only(payload, ["SE13 7VC"])

        assert "SE13" not in str(raised.value).upper()

    def test_says_where_the_value_was(self) -> None:
        payload = {"tables": [{"rows": [{"area": "SE13 7VC"}]}]}

        assert find_row_values(payload, ["se13 7vc"]) == [
            "result.tables[0].rows[0].area"
        ]

    def test_short_values_are_not_treated_as_identifying(self) -> None:
        payload = {"figures": [{"value": 2021, "note": "Census 2021"}]}

        assert find_row_values(payload, ["12", 202]) == []
