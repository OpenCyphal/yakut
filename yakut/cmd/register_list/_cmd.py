# Copyright (c) 2022 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

from __future__ import annotations
import sys
from typing import Sequence, TYPE_CHECKING
import click
import pycyphal
import yakut
from yakut.int_set_parser import parse_int_set, INT_SET_USER_DOC
from yakut.ui import ProgressReporter, show_error, show_warning
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
    y rl 90,100..125,!110-115
    y rl '[1,2,42,105]' > all_registers.json

Filter by name, in this case those matching "uavcan*id", using regex and plain match:

\b
    y rl 100-128 | jq 'map_values([.[] | select(test("uavcan.+id"))])'
    y rl 100-128 | jq 'map_values([.[] | select(startswith("uavcan.") and endswith(".id"))])'

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
    formatter = purser.make_formatter(FormatterHints(single_document=True))
    with purser.get_node("register_list", allow_anonymous=False) as node:
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
        show_error(msg)
    for msg in result.warnings:
        show_warning(msg)
    sys.stdout.write(formatter(result.names_per_node))
    sys.stdout.flush()

    return 1 if result.errors else 0
