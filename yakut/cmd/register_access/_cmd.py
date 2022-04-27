# Copyright (c) 2022 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

from __future__ import annotations
from typing import Any, Sequence, TYPE_CHECKING, Callable, Union
import click
import pycyphal
import yakut
from yakut.int_set_parser import parse_int_set, INT_SET_USER_DOC
from yakut.progress import get_progress_callback
from yakut.param.formatter import FormatterHints
from ._logic import access

if TYPE_CHECKING:
    import pycyphal.application

_logger = yakut.get_logger(__name__)


_HELP = f"""
Read or modify a register on one or multiple remote nodes.

If no value is given, the register will be read from the specified nodes.
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
If register assignment is requested (i.e., if a value is given),
nodes that report that they don't have such register are silently ignored instead of reporting an error.
Best-effort output will always be produced regardless of this option; that is, it only affects the exit code.
""",
)
@click.option(
    "--flat",
    "-f",
    is_flag=True,
    help="Do not group registers by node-ID but join them into one flat structure.",
)
@click.option(
    "--asis",
    "-a",
    is_flag=True,
    help="Display the response as-is, with metadata, do not simplify the output.",
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
    try:
        from pycyphal.application import Node
    except ImportError as ex:
        from yakut.cmd.compile import make_usage_suggestion

        raise click.ClickException(make_usage_suggestion(ex.name))

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
    formatter = purser.make_formatter(FormatterHints(short_rows=True, single_document=True))

    with purser.get_node("register-access", allow_anonymous=False) as node:
        result = await access(
            node,
            get_progress_callback(),
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

    final: Any
    if flat:
        final = []
        for val in result.value_per_node.values():
            if val not in final and val is not None:  # Cannot use set because values unhashable
                final.append(val)
        final = None if len(final) == 0 else final[0] if len(final) == 1 else final
    else:
        final = result.value_per_node
    print(formatter(final))

    return 1 if result.errors else 0
