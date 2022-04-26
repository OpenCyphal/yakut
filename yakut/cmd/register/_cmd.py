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
from ._list_names import list_names
from ._getset import getset

if TYPE_CHECKING:
    import pycyphal.application
    from uavcan.register import Access_1

_logger = yakut.get_logger(__name__)

ProgressCallback = Callable[[str], None]


_HELP = f"""
Get/set a register on one or multiple remote nodes; list available registers.

TODO the docs are missing.

{INT_SET_USER_DOC}
"""


@yakut.subcommand(aliases=["r", "reg"], help=_HELP)
@click.argument("node_ids", type=parse_int_set)
@click.argument("register_name", default="")
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
    "--maybe-no-service",
    "-s",
    is_flag=True,
    help="""
Nodes that fail to respond to the first RPC-service request of type uavcan.register.*
are silently ignored instead of reporting an error assuming that the register service is not supported.
If a node responded at least once it is assumed to support the service and any future timeout
will be always treated as error.
Best-effort output will always be produced regardless of this option; that is, it only affects the exit code.
""",
)
@click.option(
    "--maybe-missing",
    "-m",
    is_flag=True,
    help="""
Nodes that report that they don't have such register are silently ignored instead of reporting an error.
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
    help="Display the response as-is, do not simplify the output",
)
@yakut.pass_purser
@yakut.asynchronous()
async def register(
    purser: yakut.Purser,
    node_ids: Sequence[int],
    register_name: str,
    register_value_element: Sequence[str],
    timeout: float,
    maybe_no_service: bool,
    maybe_missing: bool,
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
        "maybe_no_service=%r maybe_missing=%r flat=%r asis=%r",
        maybe_no_service,
        maybe_missing,
        flat,
        asis,
    )
    reg_val_str = " ".join(register_value_element) if len(register_value_element) > 0 else None
    del register_value_element
    formatter = purser.make_formatter()

    with purser.get_node("register", allow_anonymous=False) as node:
        if not register_name:
            if maybe_missing:
                _logger.warning("maybe-missing has no effect in listing mode")
            result = await list_names(
                node,
                get_progress_callback(),
                node_ids,
                maybe_no_service=maybe_no_service,
                timeout=timeout,
            )
        else:
            result = await getset(
                node,
                get_progress_callback(),
                node_ids,
                reg_name=register_name,
                reg_val_str=reg_val_str,
                maybe_no_service=maybe_no_service,
                maybe_missing=maybe_missing,
                timeout=timeout,
                asis=asis,
            )
    # The node is no longer needed.

    for msg in result.errors:
        click.secho(msg, err=True, fg="red", bold=True)
    for msg in result.warnings:
        click.secho(msg, err=True, fg="yellow")

    final = result.data_per_node
    if flat:
        raise NotImplementedError
    print(formatter(final))

    return 1 if result.errors else 0
