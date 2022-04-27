# Copyright (c) 2022 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

from __future__ import annotations
from typing import Sequence, TYPE_CHECKING
import click
import pycyphal
import yakut
from yakut.int_set_parser import parse_int_set, INT_SET_USER_DOC
from yakut.progress import ProgressReporter
from yakut.param.formatter import FormatterHints
from ._logic import list_names

if TYPE_CHECKING:
    import pycyphal.application

_logger = yakut.get_logger(__name__)


_HELP = f"""
List registers available on the specified remote node(s).

Examples:

\b
    yakut register-list 42
    yakut rl 90,100..125,!110-115
    yakut rl '[1,2,42,105]'

{INT_SET_USER_DOC}
"""


@yakut.subcommand(aliases=["rl", "lsreg"], help=_HELP)
@click.argument("node_ids", type=parse_int_set)
@click.option(
    "--timeout",
    "-T",
    type=float,
    default=pycyphal.presentation.DEFAULT_SERVICE_REQUEST_TIMEOUT,
    show_default=True,
    metavar="SECONDS",
    help="Service response timeout.",
)
@click.option(
    "--optional-service",
    "-s",
    is_flag=True,
    help="""
Ignore nodes that fail to respond to the first RPC-service request instead of reporting an error
assuming that the register service is not supported.
If a node responded at least once it is assumed to support the service and any future timeout
will be always treated as an error.
Best-effort output will always be produced regardless of this option; that is, it only affects the exit code.
""",
)
@yakut.pass_purser
@yakut.asynchronous()
async def register_list(
    purser: yakut.Purser,
    node_ids: Sequence[int],
    timeout: float,
    optional_service: bool,
) -> int:
    node_ids = list(sorted(node_ids))
    _logger.debug("node_ids=%r, timeout=%r optional_service=%r", node_ids, timeout, optional_service)
    formatter = purser.make_formatter(FormatterHints(short_rows=True, single_document=True))
    with purser.get_node("register-list", allow_anonymous=False) as node:
        with ProgressReporter() as prog:
            result = await list_names(
                node,
                prog,
                node_ids,
                optional_service=optional_service,
                timeout=timeout,
            )
    # The node is no longer needed.
    for msg in result.errors:
        click.secho(msg, err=True, fg="red", bold=True)
    for msg in result.warnings:
        click.secho(msg, err=True, fg="yellow")
    print(formatter(result.names_per_node))

    return 1 if result.errors else 0
