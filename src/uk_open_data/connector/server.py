"""The Kindtech connector: an MCP server over the analyses and open data.

The same server runs locally over stdio and hosted over Streamable HTTP. Every
tool is read-only and returns totals, never rows.

    >>> from uk_open_data.connector import build_server
    >>> build_server().run()  # stdio
"""

import logging
import traceback
from collections.abc import Callable
from typing import Annotated, Any, Literal

import pydantic_core
from mcp.server.apps import Apps
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError, UnexpectedToolError
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import Field, ValidationError

import uk_open_data
from uk_open_data.connector.analyses import (
    find_analysis,
    record_chat_run,
    run_and_keep_result,
)
from uk_open_data.connector.maps import (
    MAP_META_KEY,
    MAP_VIEW,
    MAP_VIEW_URI,
    Boundaries,
    picture_for,
)
from uk_open_data.connector.places import describe_place
from uk_open_data.connector.privacy import PrivacyError

logger = logging.getLogger(__name__)

SERVER_NAME = "kindtech"
SERVER_TITLE = "Kindtech Evidence: open data for charities"
WEBSITE_URL = "https://github.com/KindTechUK/uk-open-data"

INSTRUCTIONS = """\
Kindtech Evidence answers questions a UK charity asks of its own figures and \
of open data. Each analysis is fixed and documented, and returns totals with \
their sources.

Rules for using these tools:
- Totals, never rows. Do not pass rows about individual people (one postcode, \
name or case per row) to any tool, and do not ask the person to paste them \
into the chat. Ask for counts that are already totalled by area or by group.
- Open with the answer. A result holds an answer sentence written by the \
analysis. Begin your reply with it in its exact words, then give the key \
figures it names.
- Show the checks and caveats that come back next to the figures. The checks \
are questions for the person. Do not answer them on the person's behalf.
- Say where each figure comes from, using the sources in the result.
- Quote each figure as it is shown, rounded. A result also holds the value \
of a share or a rate before rounding, and the code that runs the analysis \
again. Give either only when the person asks how a figure was worked out, or \
asks for the code. The code holds nothing from their figures.
- A suppressed figure is hidden to protect a small count. Do not try to \
work it out from other figures.
- When a run would hide counts, the tool says so before it shows anything. \
Pass that on and let the person choose: combine the small counts, or run \
with them hidden.
"""

READ_ONLY_LOCAL = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)
READ_ONLY_OPEN_DATA = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=True,
)


class TotalsOnlyServer(MCPServer):
    """An ``MCPServer`` whose errors and log never repeat the arguments.

    The stock error for arguments that do not fit a tool's schema quotes the
    rejected values. Those values may be rows about people, so here the error
    names the argument and what was wrong with it, and nothing else.

    When a tool crashes, the stock server writes the error's own text to the
    log. That text can quote a value from the rows or a web address, so here
    the log says which tool stopped, with what kind of error and where, and
    leaves the text out.
    """

    async def call_tool(
        self, name: str, arguments: dict[str, Any], context: Any = None
    ) -> Any:
        """Call a tool, rewording any argument error to leave the values out."""
        try:
            return await super().call_tool(name, arguments, context)
        except UnexpectedToolError as error:
            _log_crash(name, error.__cause__)
            failed = str(error)
        except ToolError as error:
            if isinstance(error.__cause__, ValidationError):
                raise ToolError(_argument_problems(name, error.__cause__)) from None
            raise
        # Raised outside the handler above, so the new error has no link at all
        # to the crash, and nothing that logs it can reach the crash's text.
        raise UnexpectedToolError(failed)


def build_server(map_boundaries: Boundaries | None = None) -> MCPServer:
    """Build the connector with its tools registered.

    Args:
        map_boundaries: Gives the outlines of the areas on a result's map, as
            GeoJSON, so the map can be drawn without the network. Left out,
            the outlines are fetched from the ONS Open Geography Portal each
            time a map is drawn. When you host the connector, pass a function
            that reads outlines kept on the server.

    Returns:
        An ``MCPServer`` ready to run over stdio (``server.run()``) or to be
        mounted as a web app (``server.streamable_http_app()``).
    """
    apps = Apps()
    apps.add_html_resource(
        MAP_VIEW_URI,
        MAP_VIEW,
        name="analysis-map",
        title="Map of an analysis result",
        description="Shows the map drawn for an analysis result.",
    )
    apps.tool(
        resource_uri=MAP_VIEW_URI,
        name="run_analysis_on_counts",
        title="Run an analysis on counts",
        annotations=READ_ONLY_OPEN_DATA,
    )(run_analysis_handler(map_boundaries))
    server = TotalsOnlyServer(
        name=SERVER_NAME,
        title=SERVER_TITLE,
        instructions=INSTRUCTIONS,
        website_url=WEBSITE_URL,
        version=uk_open_data.__version__,
        extensions=[apps],
    )
    server.tool(
        name="find_analysis", title="Find an analysis", annotations=READ_ONLY_LOCAL
    )(handle_find_analysis)
    server.tool(
        name="describe_place",
        title="Describe a place",
        annotations=READ_ONLY_OPEN_DATA,
    )(handle_describe_place)
    return server


def handle_find_analysis(
    query: Annotated[
        str | None,
        Field(
            description="The question in the person's own words, or a few key "
            "words. Leave out to list every analysis."
        ),
    ] = None,
) -> dict[str, Any]:
    """Find the analysis that answers a charity's question.

    An analysis answers one fixed question, such as "are we reaching people in
    the most deprived neighbourhoods?". Use this first to see which analyses
    exist, what data each one needs and which options can be changed. An
    analysis named under 'needs_rows' takes no totals, so it cannot run in a
    chat: tell the person where it can run. Returns analysis descriptions
    only; it reads no data.
    """
    return find_analysis(query)


def handle_describe_place(
    place: Annotated[
        str,
        Field(
            description="A local authority name ('Lewisham') or code "
            "('E09000023'), a 2021 LSOA code ('E01003189') or a postcode "
            "district ('SE13'). Never a full postcode or a street address: "
            "give the first half of the postcode."
        ),
    ],
) -> dict[str, Any]:
    """Describe a place in England from published deprivation statistics.

    Returns how deprived the place is against the rest of England (Indices of
    Deprivation 2025), resident numbers and which types of deprivation stand
    out, with sources and caveats. Use it for context about where a charity
    works. It covers England only and returns totals about areas, never
    anything about a person. A full postcode is not accepted, a venue's
    included, because nothing tells it from a person's home: pass the first
    half, such as 'SE13', or the place name. A street address is not
    accepted either. If several places match, the answer lists them so the
    person can choose.
    """
    return describe_place(place)


def run_analysis_handler(
    map_boundaries: Boundaries | None = None,
) -> Callable[..., CallToolResult]:
    """Make the handler that runs an analysis and draws maps with these outlines."""

    def handle_run_analysis_on_counts(
        analysis_id: Annotated[
            str,
            Field(
                description="The analysis id from find_analysis, for example "
                "'reach-deprivation'."
            ),
        ],
        counts: Annotated[
            list[dict[str, Any]],
            Field(
                description="One object per area or group, keyed by the role names "
                "of an input mode marked 'aggregated' in find_analysis, for example "
                "{'lsoa_code': 'E01003189', 'count': 12}, {'local_authority': "
                "'Lewisham', 'count': 120}, {'group': 'Black Caribbean', 'count': "
                "40} or {'local_authority': 'Lewisham', 'volume': 1200}. Totals "
                "only: never one row per person or per site."
            ),
        ],
        options: Annotated[
            dict[str, Any] | None,
            Field(
                description="Analysis options to change, keyed by the option "
                "names find_analysis lists. Leave out to use the defaults. "
                "Where an analysis needs one, such as 'catchment' (the area "
                "you serve), ask the person for it. A message names an option "
                "by its label in quotes, such as 'Area you serve'; "
                "find_analysis gives the label beside each name."
            ),
        ] = None,
        hidden_counts: Annotated[
            Literal["ask", "accept"],
            Field(
                description="Leave out on the first call. If the answer would hide "
                "counts, the status is 'would_hide_counts' and nothing is shown: "
                "tell the person, and pass 'accept' only after they have chosen "
                "to run with those counts hidden."
            ),
        ] = "ask",
    ) -> Annotated[CallToolResult, dict[str, Any]]:
        """Run an analysis on counts that are already totalled by area or by group.

        Returns an answer sentence, headline figures, summary tables, the
        working, the choices the analysis made, checks for the person to
        confirm, caveats and sources. Open your reply with result.answer in its
        exact words, then the figures named in result.key_figures. Show the
        checks and caveats with the figures and do not answer the checks for the
        person. Quote figures as shown: a figure's 'exact' value and
        result.code, the Python that runs the analysis again, are for a person
        who asks how a figure was worked out or asks for the code. Rows about
        individuals are refused. Small counts are hidden, and
        a second count with them. If the status is 'would_hide_counts', nothing
        has been shown: tell the person what would be hidden and offer the
        choices in the answer before calling again. A table named under
        'rows_left_out' is not empty: its rows are for a map or a download and
        are left out of the answer. Where the answer has 'map', a picture of
        the result's map was drawn for the person or its note says why not;
        you are not given the picture, so do not describe it. If the status is
        'input_problem', show the person the problems as they are; 'option'
        or 'role', when given, is the name of the option or the column to
        change. If the status is 'unavailable', a data source could not be
        reached: say so and try again later.
        """
        answer, result, guarded = run_and_keep_result(
            analysis_id, counts, options, hidden_counts
        )
        picture = None
        if result is not None:
            picture, note = picture_for(result, guarded, map_boundaries)
            if note:
                answer["map"] = {"drawn": picture is not None, "note": note}
        reply = _tool_result(answer, {MAP_META_KEY: picture} if picture else None)
        if result is not None:
            record_chat_run(result)
        return reply

    return handle_run_analysis_on_counts


def _tool_result(answer: dict[str, Any], meta: dict[str, Any] | None) -> CallToolResult:
    """An answer as a tool result, with anything for the app only beside it.

    The answer is what the model reads, as text and as structured content.
    ``meta`` travels in the result's ``_meta``, which an app can read and which
    is not part of what a model is given.
    """
    text = pydantic_core.to_json(answer, fallback=str, indent=2).decode()
    return CallToolResult(
        content=[TextContent(type="text", text=text)],
        structured_content=answer,
        meta=meta,
    )


def _log_crash(tool: str, cause: BaseException | None) -> None:
    """Log which tool crashed, the kind of error and where, never its text.

    The privacy guard's own message is written to be safe to show, so it is
    kept: it says where in a result a value was found and not what it was.
    """
    said = f": {cause}" if isinstance(cause, PrivacyError) else ""
    where = "".join(traceback.format_tb(cause.__traceback__)) if cause else ""
    logger.error(
        "Tool %s stopped with %s%s\n%s", tool, type(cause).__name__, said, where
    )


def _argument_problems(tool: str, error: ValidationError) -> str:
    """Say which arguments were wrong and why, without quoting their values."""
    problems = sorted(
        {
            f"{'.'.join(str(part) for part in item['loc']) or 'arguments'}: "
            f"{item['type'].replace('_', ' ')}"
            for item in error.errors(include_input=False, include_url=False)
        }
    )
    return f"The arguments for {tool} did not fit: {'; '.join(problems)}."
