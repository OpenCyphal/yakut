# Copyright (c) 2022 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

from __future__ import annotations
import sys
from typing import TYPE_CHECKING
import click
import pycyphal
import yakut
from yakut.int_set_parser import parse_int_set, INT_SET_USER_DOC
from yakut.ui import ProgressReporter, show_error, show_warning
from yakut.param.formatter import FormatterHints
from yakut.util import EXIT_CODE_UNSUCCESSFUL
from ._logic import list_names

if TYPE_CHECKING:
    import pycyphal.application

_logger = yakut.get_logger(__name__)


_HELP = f"""
List registers available on the specified remote node(s).

If the specified node-ID is a single integer, then the output contains simply the list of register names on that node.

If the specified node-ID is a set of integers (or a single integer followed by element separator, like `123,`),
then the output is a mapping (node_id->[register_name]).

The output can be piped to another command like yakut register-batch.

Examples:

\b
    y rl 42 > registers.json
    y rl 90,100..125,!110-115 | y rb > registers_all.json
    y rl '[1,2,42,105]' | jq > register_names_all.json

Filter by name, in this case those matching "uavcan*id" (mind the comma!):

\b
    y rl 125  | jq 'map(select(test("uavcan.+id")))'
    y rl 125, | jq 'map_values([.[] | select(test("uavcan.+id"))])'

Compute intersection -- registers that are available in all of the queried nodes:

\b
    y rl 120-128 | jq '. as $in|reduce .[] as $item ($in|flatten|flatten;.-(.-$item))|unique'

{INT_SET_USER_DOC}
"""


@yakut.subcommand(aliases="rl", help=_HELP)
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
""",
)
@yakut.pass_purser
@yakut.asynchronous()
async def register_list(
    purser: yakut.Purser,
    node_ids: set[int] | int,
    timeout: float,
    optional_service: bool,
) -> int:
    _logger.debug("node_ids=%r, timeout=%r optional_service=%r", node_ids, timeout, optional_service)
    node_ids_list = list(sorted(node_ids)) if isinstance(node_ids, set) else [node_ids]
    assert isinstance(node_ids_list, list) and all(isinstance(x, int) for x in node_ids_list)
    formatter = purser.make_formatter(FormatterHints(single_document=True))
    with purser.get_node("register_list", allow_anonymous=False) as node:
        with ProgressReporter() as prog:
            result = await list_names(
                node,
                prog,
                node_ids_list,
                optional_service=optional_service,
                timeout=timeout,
            )
    # The node is no longer needed.
    for msg in result.errors:
        show_error(msg)
    for msg in result.warnings:
        show_warning(msg)
    final = result.names_per_node if not isinstance(node_ids, int) else result.names_per_node[node_ids]
    sys.stdout.write(formatter(final))
    sys.stdout.flush()

    return EXIT_CODE_UNSUCCESSFUL if result.errors else 0
