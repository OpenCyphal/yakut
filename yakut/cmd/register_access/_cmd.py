# Copyright (c) 2022 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

from __future__ import annotations
import sys
from typing import Any, Sequence, TYPE_CHECKING
import click
import pycyphal
import yakut
from yakut.int_set_parser import parse_int_set, INT_SET_USER_DOC
from yakut.progress import ProgressReporter
from yakut.param.formatter import FormatterHints
from ._logic import access

if TYPE_CHECKING:
    import pycyphal.application

_logger = yakut.get_logger(__name__)


_HELP = f"""
Read or modify a register on one or multiple remote nodes.

If no value is given, the register will be only read from the specified nodes.
If a value is given, it shall follow the environment variable notation described in the
uavcan.register.Access service specification.
The value will be parsed depending on the type of the register reported by the remote node
(which may be different per node).

If no value is given, only one request will be sent per node.
If a value is given, two requests will be sent: the first one to discover the type,
the second to actually write the value
(unless the provided value could not be applied to the register type).
The final value returned by the node is always printed at the end,
which may be different from the assigned value depending on the internal logic of the node
(e.g., the value could be adjusted to satisfy constraints, the register could be read-only, etc.).

Examples:

\b
    yakut reg 120-125 m.inductance_dq
    yakut reg 120-125 m.inductance_dq '12.0e-6 14.7e-6'
    yakut reg 120-125 m.inductance_dq  12.0e-6 14.7e-6  # Quotes are optional
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
    "--flat",
    "--flatten",
    "-f",
    is_flag=True,
    help="""
Do not group register values by node-ID but join them into one flat structure with duplicates and empty values removed.
If only one value is left at the end, report it as-is without the enclosing list.
""",
)
@click.option(
    "--asis",
    "-a",
    is_flag=True,
    help="Display the response as-is, with metadata and type information, do not simplify the output.",
)
@yakut.pass_purser
@yakut.asynchronous()
async def register_access(
    purser: yakut.Purser,
    node_ids: Sequence[int],
    register_name: str,
    register_value_element: Sequence[str],
    timeout: float,
    optional_service: bool,
    optional_register: bool,
    flat: bool,
    asis: bool,
) -> int:
    node_ids = list(sorted(node_ids))
    _logger.debug(
        "node_ids=%r, register_name=%r, register_value_element=%r timeout=%r",
        node_ids,
        register_name,
        register_value_element,
        timeout,
    )
    _logger.debug(
        "optional_service=%r optional_register=%r flat=%r asis=%r",
        optional_service,
        optional_register,
        flat,
        asis,
    )
    reg_val_str = " ".join(register_value_element) if len(register_value_element) > 0 else None
    del register_value_element
    formatter = purser.make_formatter(FormatterHints(single_document=True))

    with purser.get_node("register_access", allow_anonymous=False) as node:
        with ProgressReporter() as prog:
            result = await access(
                node,
                prog,
                node_ids,
                reg_name=register_name,
                reg_val_str=reg_val_str,
                optional_service=optional_service,
                optional_register=optional_register,
                timeout=timeout,
                asis=asis,
            )
    # The node is no longer needed.
    for msg in result.errors:
        click.secho(msg, err=True, fg="red", bold=True)
    for msg in result.warnings:
        click.secho(msg, err=True, fg="yellow")

    final = _flatten(result.value_per_node) if flat else result.value_per_node
    sys.stdout.write(formatter(final))
    sys.stdout.flush()

    return 1 if result.errors else 0


def _flatten(value_per_node: dict[int, Any]) -> Any:
    collapsed: list[Any] = []
    for val in value_per_node.values():
        if val not in collapsed and val is not None:  # Cannot use set because values unhashable
            collapsed.append(val)
    return None if len(collapsed) == 0 else collapsed[0] if len(collapsed) == 1 else collapsed