"""The Kindtech connector: an MCP server over the lenses and open data.

The same server runs locally over stdio and hosted over Streamable HTTP. Every
tool is read-only and returns totals, never rows.

    >>> from kindtech.connector import build_server
    >>> build_server().run()  # stdio
"""

from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError, UnexpectedToolError
from mcp.types import ToolAnnotations
from pydantic import Field, ValidationError

import kindtech
from kindtech.connector.lenses import find_lens, run_lens_on_counts
from kindtech.connector.places import describe_place

SERVER_NAME = "kindtech"
SERVER_TITLE = "Kindtech open data for charities"
WEBSITE_URL = "https://github.com/KindTechUK/kindtech"

INSTRUCTIONS = """\
Kindtech answers questions a UK charity asks of its own figures and of open \
data, using lenses: fixed, documented analyses that return totals with their \
sources.

Rules for using these tools:
- Totals, never rows. Do not pass rows about individual people (one postcode, \
name or case per row) to any tool, and do not ask the person to paste them \
into the chat. Ask for counts that are already totalled by area or by group.
- Show the checks and caveats that come back next to the figures. The checks \
are questions for the person. Do not answer them on the person's behalf.
- Say where each figure comes from, using the sources in the result.
- A suppressed figure is hidden because it is a small count. Do not try to \
work it out from other figures.
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
    """An ``MCPServer`` whose argument errors never repeat the arguments.

    The stock error for arguments that do not fit a tool's schema quotes the
    rejected values. Those values may be rows about people, so here the error
    names the argument and what was wrong with it, and nothing else.
    """

    async def call_tool(
        self, name: str, arguments: dict[str, Any], context: Any = None
    ) -> Any:
        """Call a tool, rewording any argument error to leave the values out."""
        try:
            return await super().call_tool(name, arguments, context)
        except UnexpectedToolError:
            raise
        except ToolError as error:
            if isinstance(error.__cause__, ValidationError):
                raise ToolError(_argument_problems(name, error.__cause__)) from None
            raise


def build_server() -> MCPServer:
    """Build the connector with its tools registered.

    Returns:
        An ``MCPServer`` ready to run over stdio (``server.run()``) or to be
        mounted as a web app (``server.streamable_http_app()``).
    """
    server = TotalsOnlyServer(
        name=SERVER_NAME,
        title=SERVER_TITLE,
        instructions=INSTRUCTIONS,
        website_url=WEBSITE_URL,
        version=kindtech.__version__,
    )
    server.tool(name="find_lens", title="Find a lens", annotations=READ_ONLY_LOCAL)(
        handle_find_lens
    )
    server.tool(
        name="describe_place",
        title="Describe a place",
        annotations=READ_ONLY_OPEN_DATA,
    )(handle_describe_place)
    server.tool(
        name="run_lens_on_counts",
        title="Run a lens on counts",
        annotations=READ_ONLY_OPEN_DATA,
    )(handle_run_lens_on_counts)
    return server


def handle_find_lens(
    query: Annotated[
        str | None,
        Field(
            description="The question in the person's own words, or a few key "
            "words. Leave out to list every lens."
        ),
    ] = None,
) -> dict[str, Any]:
    """Find the lens that answers a charity's question.

    A lens is a fixed analysis, such as "are we reaching people in the most
    deprived neighbourhoods?". Use this first to see which lenses exist, what
    data each one needs and which options can be changed. Returns lens
    descriptions only; it reads no data.
    """
    return find_lens(query)


def handle_describe_place(
    place: Annotated[
        str,
        Field(
            description="A local authority name ('Lewisham') or code "
            "('E09000023'), a 2021 LSOA code ('E01003189'), a postcode district "
            "('SE13'), or the postcode of a venue or office. Never the postcode "
            "of a client or other individual."
        ),
    ],
) -> dict[str, Any]:
    """Describe a place in England from published deprivation statistics.

    Returns how deprived the place is against the rest of England (Indices of
    Deprivation 2025), resident numbers and which types of deprivation stand
    out, with sources and caveats. Use it for context about where a charity
    works. It covers England only and returns totals about areas, never
    anything about a person. A postcode passed in is not repeated in the
    answer. If several places match, the answer lists them so the person can
    choose.
    """
    return describe_place(place)


def handle_run_lens_on_counts(
    lens_id: Annotated[
        str, Field(description="The lens id from find_lens, e.g. 'reach-deprivation'.")
    ],
    counts: Annotated[
        list[dict[str, Any]],
        Field(
            description="One object per area or group, keyed by the role names "
            "of an input mode marked 'aggregated' in find_lens, for example "
            "{'lsoa_code': 'E01003189', 'count': 12}, {'local_authority': "
            "'Lewisham', 'count': 120} or {'group': 'Black Caribbean', 'count': "
            "40}. Totals only: never one row per person."
        ),
    ],
    options: Annotated[
        dict[str, Any] | None,
        Field(
            description="Lens options to change, as listed by find_lens. Leave "
            "out to use the defaults. Where a lens needs one, such as "
            "'catchment' (the area the charity serves), ask the person for it."
        ),
    ] = None,
) -> dict[str, Any]:
    """Run a lens on counts that are already totalled by area or by group.

    Returns headline figures, summary tables, the working, the choices the
    lens made, checks for the person to confirm, caveats and sources. Small
    counts are hidden. Show the checks and caveats with the figures and do not
    answer the checks for the person. Rows about individuals are refused. If
    the status is 'unavailable', a data source could not be reached: say so
    and try again later.
    """
    return run_lens_on_counts(lens_id, counts, options)


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
