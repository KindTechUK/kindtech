"""The Kindtech connector: an MCP server over the lenses and open data.

The same server runs locally over stdio and hosted over Streamable HTTP. Every
tool is read-only and returns totals, never rows.

    >>> from uk_open_data.connector import build_server
    >>> build_server().run()  # stdio
"""

import logging
import traceback
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError, UnexpectedToolError
from mcp.types import ToolAnnotations
from pydantic import Field, ValidationError

import uk_open_data
from uk_open_data.connector.lenses import find_lens, run_lens_on_counts
from uk_open_data.connector.places import describe_place
from uk_open_data.connector.privacy import PrivacyError

logger = logging.getLogger(__name__)

SERVER_NAME = "kindtech"
SERVER_TITLE = "Kindtech open data for charities"
WEBSITE_URL = "https://github.com/KindTechUK/uk-open-data"

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
        version=uk_open_data.__version__,
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
            "'Lewisham', 'count': 120}, {'group': 'Black Caribbean', 'count': "
            "40} or {'local_authority': 'Lewisham', 'volume': 1200}. Totals "
            "only: never one row per person or per site."
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
    hidden_counts: Annotated[
        Literal["ask", "accept"],
        Field(
            description="Leave out on the first call. If the answer would hide "
            "counts, the status is 'would_hide_counts' and nothing is shown: "
            "tell the person, and pass 'accept' only after they have chosen "
            "to run with those counts hidden."
        ),
    ] = "ask",
) -> dict[str, Any]:
    """Run a lens on counts that are already totalled by area or by group.

    Returns headline figures, summary tables, the working, the choices the
    lens made, checks for the person to confirm, caveats and sources. Show the
    checks and caveats with the figures and do not answer the checks for the
    person. Rows about individuals are refused. Small counts are hidden, and
    a second count with them. If the status is 'would_hide_counts', nothing
    has been shown: tell the person what would be hidden and offer the
    choices in the answer before calling again. A table named under
    'rows_left_out' is not empty: its rows are for a map or a download and
    are left out of the answer. If the status is 'unavailable', a data source
    could not be reached: say so and try again later.
    """
    return run_lens_on_counts(lens_id, counts, options, hidden_counts)


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
