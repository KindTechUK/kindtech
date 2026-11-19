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

from uk_open_data.analyses.need_reach import keep_need_figures  # noqa: E402
from uk_open_data.analyses.who_we_miss import keep_residents  # noqa: E402
from uk_open_data.connector import (  # noqa: E402
    PrivacyError,
    build_server,
    ensure_totals_only,
)
from uk_open_data.connector.privacy import find_row_values  # noqa: E402

POSTCODE = fakes.SECRET_POSTCODE
PERSON = "Zebedee Quillfeather"
AREA = "E01000001"
COUNCIL = "Lewisham"
OWN_LABEL = "Black Caribbean"

# tool name -> cases of (arguments, values that must not come back)
CASES: dict[str, list[tuple[dict[str, Any], list[str]]]] = {
    "find_analysis": [
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
    "run_analysis_on_counts": [
        (
            {
                "analysis_id": "reach-deprivation",
                "counts": [{"lsoa_code": AREA, "count": 12}],
            },
            [AREA],
        ),
        (
            # Too few people for the analysis to give figures at all.
            {
                "analysis_id": "reach-deprivation",
                "counts": [{"lsoa_code": AREA, "count": 3}],
            },
            [AREA],
        ),
        (
            # A result that would hide counts is held back with a plain answer.
            {
                "analysis_id": "reach-deprivation",
                "counts": [
                    {"lsoa_code": AREA, "count": 3},
                    {"lsoa_code": "E01000002", "count": 30},
                ],
            },
            [AREA, "E01000002"],
        ),
        (
            {"analysis_id": "reach-deprivation", "counts": [{"postcode": POSTCODE}]},
            [POSTCODE],
        ),
        (
            {
                "analysis_id": "reach-deprivation",
                "counts": [{"lsoa_code": AREA, "count": 3, "name": PERSON}],
            },
            [AREA, PERSON],
        ),
        ({"analysis_id": "reach-deprivation", "counts": POSTCODE}, [POSTCODE]),
        ({"counts": [{"postcode": POSTCODE, "name": PERSON}]}, [POSTCODE, PERSON]),
        (
            {
                "analysis_id": PERSON,
                "counts": [{"lsoa_code": AREA, "count": 3}],
                "options": PERSON,
            },
            [AREA, PERSON],
        ),
        ({"analysis_id": "need-reach", "counts": [{"postcode": POSTCODE}]}, [POSTCODE]),
        (
            # A postcode or a name where a local authority should be.
            {
                "analysis_id": "need-reach",
                "counts": [
                    {"local_authority": COUNCIL, "count": 30},
                    {"local_authority": POSTCODE, "count": 12},
                    {"local_authority": PERSON, "count": 9},
                ],
            },
            [POSTCODE, PERSON],
        ),
        (
            {
                "analysis_id": "need-reach",
                "counts": [{"local_authority": POSTCODE, "count": 1}],
            },
            [POSTCODE],
        ),
        (
            {
                "analysis_id": "who-we-miss",
                "counts": [{"group": "White", "postcode": POSTCODE}],
                "options": {"catchment": [COUNCIL]},
            },
            [POSTCODE],
        ),
        (
            # A postcode, a name or a charity's own label where a group should be.
            {
                "analysis_id": "who-we-miss",
                "counts": [
                    {"group": "White", "count": 220},
                    {"group": OWN_LABEL, "count": 40},
                    {"group": POSTCODE, "count": 12},
                    {"group": PERSON, "count": 9},
                ],
                "options": {"catchment": [COUNCIL]},
            },
            [POSTCODE, PERSON, OWN_LABEL],
        ),
        (
            # No catchment, so the analysis gives no figures at all.
            {"analysis_id": "who-we-miss", "counts": [{"group": PERSON, "count": 9}]},
            [PERSON],
        ),
        (
            # One row per site, which is not a total.
            {
                "analysis_id": "provision-gap",
                "counts": [{"postcode": POSTCODE, "volume": 30}],
            },
            [POSTCODE],
        ),
        (
            # A postcode or a name where a local authority should be.
            {
                "analysis_id": "provision-gap",
                "counts": [
                    {"local_authority": COUNCIL, "volume": 1200},
                    {"local_authority": POSTCODE, "volume": 12},
                    {"local_authority": PERSON, "volume": 9},
                ],
            },
            [POSTCODE, PERSON],
        ),
        (
            # A name or a postcode where a volume should be.
            {
                "analysis_id": "provision-gap",
                "counts": [
                    {"local_authority": COUNCIL, "volume": PERSON},
                    {"local_authority": COUNCIL, "volume": POSTCODE},
                ],
            },
            [POSTCODE, PERSON],
        ),
    ],
}


@pytest.fixture(autouse=True)
def _stand_ins(england: None) -> None:
    """Every case runs the real analyses against the small England."""
    keep_need_figures("unemployed", fakes.NEED, "invented for a test.")
    keep_need_figures("residents", fakes.NEED, "invented for a test.")
    keep_residents("ethnic_group", fakes.RESIDENTS, "invented for a test.")


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
    place = json.loads(_call("describe_place", {"place": COUNCIL}))
    refused = json.loads(_call("describe_place", {"place": POSTCODE}))
    run = json.loads(
        _call(
            "run_analysis_on_counts",
            {
                "analysis_id": "reach-deprivation",
                "counts": [{"lsoa_code": AREA, "count": 12}],
            },
        )
    )
    second = json.loads(
        _call(
            "run_analysis_on_counts",
            {
                "analysis_id": "need-reach",
                "counts": [
                    {"local_authority": COUNCIL, "count": 30},
                    {"local_authority": POSTCODE, "count": 12},
                ],
                "options": {"catchment": "England"},
            },
        )
    )
    third = json.loads(
        _call(
            "run_analysis_on_counts",
            {
                "analysis_id": "who-we-miss",
                "counts": [
                    {"group": "White", "count": 220},
                    {"group": OWN_LABEL, "count": 40},
                ],
                "options": {"catchment": [COUNCIL]},
            },
        )
    )
    fourth = json.loads(
        _call(
            "run_analysis_on_counts",
            {
                "analysis_id": "provision-gap",
                "counts": [
                    {"local_authority": COUNCIL, "volume": "1,200"},
                    {"local_authority": POSTCODE, "volume": 12},
                ],
            },
        )
    )

    assert place["isError"] is False
    assert place["structuredContent"]["status"] == "found"
    # A full postcode is turned away with a plain answer, not an error.
    assert refused["isError"] is False
    assert refused["structuredContent"]["status"] == "not_accepted"
    assert run["isError"] is False
    assert run["structuredContent"]["status"] == "ok"
    assert second["isError"] is False
    assert second["structuredContent"]["status"] == "ok"
    # A local authority is a public place, so the second analysis may name it.
    assert COUNCIL in json.dumps(second["structuredContent"]["result"]["tables"])
    assert third["isError"] is False
    assert third["structuredContent"]["status"] == "ok"
    # A census group is public, so the third analysis names it, and not the label.
    by_group = json.dumps(third["structuredContent"]["result"]["tables"])
    assert "Black" in by_group
    assert OWN_LABEL not in by_group
    assert fourth["isError"] is False
    assert fourth["structuredContent"]["status"] == "ok"
    # A volume sent as text is read as a number, and the place may be named.
    assert COUNCIL in json.dumps(fourth["structuredContent"]["result"]["tables"])


@pytest.mark.usefixtures("postcode_table")
@pytest.mark.parametrize("place", [POSTCODE, "ZZ99 7VC", "CF10 1VC", "ZZ99"])
def test_no_postcode_comes_back_when_placed_on_this_machine(place: str) -> None:
    reply = _call("describe_place", {"place": place})

    if len(place) > 4:
        assert _squash(place) not in _squash(reply)
    assert json.loads(reply)["isError"] is False


@pytest.mark.usefixtures("leaky_analysis_engine")
def test_an_analysis_that_repeats_input_is_stopped_at_the_connector() -> None:
    arguments = {
        "analysis_id": "reach-deprivation",
        "counts": [{"lsoa_code": AREA, "count": 3}],
    }

    reply = json.loads(_call("run_analysis_on_counts", arguments))

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
            {"answer": "Most of your people live near SE13 7VC."},
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
