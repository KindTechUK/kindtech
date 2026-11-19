"""The command that starts the Kindtech connector."""

import argparse
import logging
import sys
from collections.abc import Sequence

from uk_open_data.analyses import RUNS_LOGGER
from uk_open_data.connector.maps import keep_addresses_out_of_the_log

# How the usage line names the command, unless the caller started it another way.
PROG = "python -m uk_open_data.connector"
STDIO = "stdio"
STREAMABLE_HTTP = "streamable-http"


def main(argv: Sequence[str] | None = None, prog: str = PROG) -> None:
    """Run the connector over stdio, or over Streamable HTTP when hosted.

    Args:
        argv: Command line arguments; defaults to ``sys.argv[1:]``.
        prog: The command the person typed to start it, shown in the usage
            line of ``--help`` and of an error about an option.
    """
    args = _parser(prog).parse_args(argv)
    # stdout carries the protocol over stdio, so logs must go to stderr.
    logging.basicConfig(level=args.log_level, stream=sys.stderr)
    # One line for each answer given, whatever the level chosen for the rest.
    logging.getLogger(RUNS_LOGGER).setLevel(logging.INFO)
    # The boundary service's own error lines hold the web address it was asked.
    keep_addresses_out_of_the_log()
    from uk_open_data.connector import build_server

    server = build_server()
    if args.transport == STDIO:
        server.run(STDIO)
        return
    server.run(
        STREAMABLE_HTTP,
        host=args.host,
        port=args.port,
        stateless_http=True,
        json_response=True,
    )


def start() -> None:
    """Run :func:`main` for ``python -m uk_open_data.connector``.

    A missing ``connector`` extra ends the command with the one sentence that
    says how to install it, where a traceback would bury it.
    """
    try:
        main()
    except ImportError as error:
        raise SystemExit(str(error)) from None


def _parser(prog: str) -> argparse.ArgumentParser:
    """The command line options."""
    parser = argparse.ArgumentParser(
        prog=prog,
        description="Kindtech's read-only connector for chat assistants.",
    )
    parser.add_argument(
        "--transport",
        choices=[STDIO, STREAMABLE_HTTP],
        default=STDIO,
        help="stdio for a local assistant (default); streamable-http to host it.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Address to listen on.")
    parser.add_argument("--port", type=int, default=8000, help="Port to listen on.")
    parser.add_argument("--log-level", default="WARNING", help="Logging level.")
    return parser
