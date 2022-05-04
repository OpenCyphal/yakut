# Copyright (c) 2022 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

from __future__ import annotations
import sys
from typing import Any, Sequence, TYPE_CHECKING, Optional, Callable
import click
import pycyphal
import yakut
from yakut.int_set_parser import parse_int_set, INT_SET_USER_DOC
from yakut.ui import ProgressReporter, show_error, show_warning
from yakut.param.formatter import FormatterHints
from yakut.register import explode_value, get_access_response_metadata
from yakut.util import EXIT_CODE_UNSUCCESSFUL
from ._logic import access

if TYPE_CHECKING:
    import pycyphal.application
    from uavcan.register import Access_1

_logger = yakut.get_logger(__name__)


_HELP = f"""
Read or modify a register on one or multiple remote nodes.

If no value is given, the register will be only read from the specified nodes,
and only one request will be sent per node.

If a value is given, it shall follow the standard environment variable notation described in the
uavcan.register.Access service specification.
The assignment value will be parsed depending on the type of the register reported by the remote node
(which may be different per node).

If a value is given, two requests will be sent: the first one to discover the type,
the second to actually write the value
(unless the provided value could not be applied to the register type).
The final value returned by the node is always printed at the end,
which may be different from the assigned value depending on the internal logic of the node
(e.g., the value could be adjusted to satisfy constraints, the register could be read-only, etc.).

The output (but not the behavior) depends on how the node-ID set is specified:
if it's a single number, the result will be only the value of the specified register;
if multiple node-IDs are given or the sole node-ID is given in the set notation,
the output will be a map of (node_id->register_value).

Examples:

\b
    yakut reg 125  m.inductance_dq                      # Outputs only the value
    yakut reg 125, m.inductance_dq                      # Outputs {{125: value}}
    yakut reg 122-126 m.inductance_dq '12.0e-6 14.7e-6'
    yakut reg 122-126 m.inductance_dq  12.0e-6 14.7e-6  # Quotes are optional
    y r 122-126 m.inductance_dq | jq '[.[]]|unique'     # Remove duplicate values from output
    y r 125 uavcan.node.description "Motor rear-left #3"

{INT_SET_USER_DOC}
"""


@yakut.subcommand(aliases=["r", "reg"], help=_HELP)
@click.argument("node_ids", type=parse_int_set)
@click.argument("register_name")
@click.argument("register_value_element", nargs=-1)
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
will be always treated as error.
Best-effort output will always be produced regardless of this option; that is, it only affects the exit code.
""",
)
@click.option(
    "--optional-register",
    "-r",
    is_flag=True,
    help="""
If modification is requested (i.e., if a value is given),
nodes that report that they don't have such register are silently ignored instead of reporting an error.
Best-effort output will always be produced regardless of this option; that is, it only affects the exit code.
""",
)
@click.option(
    "--detailed",
    "-d",
    count=True,
    help="Display the value as-is, with DSDL type information, do not simplify. Specify twice to also show metadata.",
)
@yakut.pass_purser
@yakut.asynchronous()
async def register_access(
    purser: yakut.Purser,
    node_ids: Sequence[int] | int,
    register_name: str,
    register_value_element: Sequence[str],
    timeout: float,
    optional_service: bool,
    optional_register: bool,
    detailed: int,
) -> int:
    _logger.debug(
        "node_ids=%r, register_name=%r, register_value_element=%r timeout=%r",
        node_ids,
        register_name,
        register_value_element,
        timeout,
    )
    _logger.debug(
        "optional_service=%r optional_register=%r detailed=%r",
        optional_service,
        optional_register,
        detailed,
    )
    reg_val_str = " ".join(register_value_element) if len(register_value_element) > 0 else None
    del register_value_element
    formatter = purser.make_formatter(FormatterHints(single_document=True))
    representer = _make_representer(simplify=detailed < 1, metadata=detailed > 1)

    with purser.get_node("register_access", allow_anonymous=False) as node:
        with ProgressReporter() as prog:
            result = await access(
                node,
                prog,
                list(sorted(node_ids)) if not isinstance(node_ids, int) else [node_ids],
                reg_name=register_name,
                reg_val_str=reg_val_str,
                optional_service=optional_service,
                optional_register=optional_register,
                timeout=timeout,
            )
    # The node is no longer needed.
    for msg in result.errors:
        show_error(msg)
    for msg in result.warnings:
        show_warning(msg)

    final = (
        {k: representer(v) for k, v in result.value_per_node.items()}
        if not isinstance(node_ids, int)
        else representer(result.value_per_node[node_ids])
    )
    sys.stdout.write(formatter(final))
    sys.stdout.flush()

    return EXIT_CODE_UNSUCCESSFUL if result.errors else 0


def _make_representer(simplify: bool, metadata: bool) -> Callable[[Optional["Access_1.Response"]], Any]:
    def represent(response: Optional["Access_1.Response"]) -> Any:
        return (
            explode_value(
                response.value,
                simplify=simplify,
                metadata=get_access_response_metadata(response) if metadata else None,
            )
            if response is not None
            else None
        )

    return represent
