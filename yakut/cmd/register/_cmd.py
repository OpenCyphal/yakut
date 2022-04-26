# Copyright (c) 2022 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

from __future__ import annotations
import sys
from typing import Any, Sequence, TYPE_CHECKING, Callable, Union
import click
import pycyphal
import yakut
from yakut.param.formatter import Formatter
from yakut.int_set_parser import parse_int_set, INT_SET_USER_DOC

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
    default=False,
    show_default=True,
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
    default=False,
    show_default=True,
    help="""
Nodes that report that they don't have such register are silently ignored instead of reporting an error.
Best-effort output will always be produced regardless of this option; that is, it only affects the exit code.
""",
)
@click.option(
    "--flat",
    "-f",
    default=False,
    show_default=True,
    help="Do not group registers by node-ID but join them into one flat structure.",
)
@click.option(
    "--with-metadata",
    "-M",
    default=False,
    show_default=True,
    help="Extend the register value with metadata.",
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
    with_metadata: bool,
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
        "maybe_no_service=%r maybe_missing=%r flat=%r with_metadata=%r",
        maybe_no_service,
        maybe_missing,
        flat,
        with_metadata,
    )
    reg_val_str = " ".join(register_value_element) if len(register_value_element) > 0 else None
    del register_value_element
    error_count = 0

    def warn(what: str) -> None:
        click.secho(what, err=True, fg="yellow", bold=True)

    def error(what: str) -> None:
        nonlocal error_count
        error_count += 1
        click.secho(what, err=True, fg="red", bold=True)

    if sys.stderr.isatty():

        def report_progress(text: str) -> None:
            click.secho(f"\r{text}\r", nl=False, file=sys.stderr, fg="green")

    else:

        def report_progress(text: str) -> None:
            _ = text

    with purser.get_node("register", allow_anonymous=False) as node:
        final_output: dict[int, list[str] | dict[str, Any] | None] = {}

        def mark_no_service(node_id: int) -> None:
            final_output[node_id] = None
            if maybe_no_service:
                warn(f"Service not accessible at node {nid}, ignoring as requested")
            else:
                error(f"Service not accessible at node {nid}")
                assert error_count > 0

        if not register_name:
            for nid, names in (await _list_names(node, report_progress, node_ids, timeout=timeout)).items():
                _logger.debug("Names @%r: %r", nid, names)
                if isinstance(names, NoServiceTag):
                    mark_no_service(nid)
                else:
                    lst = final_output.setdefault(nid, [])
                    assert isinstance(lst, list)
                    for idx, n in enumerate(names):
                        if isinstance(n, TimeoutTag):
                            error(f"Request #{idx} to node {nid} has timed out, data incomplete")
                        else:
                            lst.append(n)
        else:
            for nid, sample in (
                await _getset(node, report_progress, node_ids, register_name, reg_val_str, timeout=timeout)
            ).items():
                _logger.debug("Register @%r: %r", nid, sample)
                final_output[nid] = None  # Error state is default state
                if isinstance(sample, NoServiceTag):
                    mark_no_service(nid)
                elif isinstance(sample, TimeoutTag):
                    error(f"Request to node {nid} has timed out")
                elif isinstance(sample, Exception):
                    error(f"Assignment failed on node {nid}: {type(sample).__name__}: {sample}")
                else:
                    if sample.value.empty and reg_val_str is not None:
                        if maybe_missing:
                            warn(
                                f"Cannot assign nonexistent register {register_name!r} at node {nid}, "
                                f"ignoring as requested"
                            )
                        else:
                            error(f"Cannot assign nonexistent register {register_name!r} at node {nid}")

    return 0 if error_count == 0 else 1


class NoServiceTag:
    pass


class TimeoutTag:
    pass


async def _list_names(
    local_node: pycyphal.application.Node,
    progress: ProgressCallback,
    node_ids: Sequence[int],
    *,
    timeout: float,
) -> dict[int, list[str | TimeoutTag] | NoServiceTag]:
    from uavcan.register import List_1

    out: dict[int, list[str | TimeoutTag] | NoServiceTag] = {}
    for nid in node_ids:
        cln = local_node.make_client(List_1, nid)
        try:
            cln.response_timeout = timeout
            name_list: list[str | TimeoutTag] | NoServiceTag = []
            for idx in range(2**16):
                progress(f"#{idx:05}@{nid:05}")
                resp = await cln(List_1.Request(index=idx))
                assert isinstance(name_list, list)
                if resp is None:
                    if 0 == idx:  # First request timed out, assume service not supported or node is offline
                        name_list = NoServiceTag()
                    else:  # Non-first request has timed out, assume network error
                        name_list.append(TimeoutTag())
                    break
                assert isinstance(resp, List_1.Response)
                name = resp.name.name.tobytes().decode(errors="replace")
                if not name:
                    break
                name_list.append(name)
        finally:
            cln.close()
        _logger.debug("Register names fetched from node %r: %r", nid, name_list)
        out[nid] = name_list
    progress("Done")
    return out


async def _getset(
    local_node: pycyphal.application.Node,
    progress: ProgressCallback,
    node_ids: Sequence[int],
    reg_name: str,
    reg_val_str: str | None,
    *,
    timeout: float,
) -> dict[
    int,
    Union[NoServiceTag, TimeoutTag, "Access_1.Response", "pycyphal.application.register.ValueConversionError"],
]:
    from uavcan.register import Access_1

    out: dict[
        int,
        Access_1.Response | NoServiceTag | TimeoutTag | pycyphal.application.register.ValueConversionError,
    ] = {}
    for nid in node_ids:
        progress(f"{reg_name!r}@{nid:05}")
        cln = local_node.make_client(Access_1, nid)
        try:
            cln.response_timeout = timeout
            out[nid] = await _getset_one(cln, reg_name, reg_val_str)
        finally:
            cln.close()
    progress("Done")
    return out


async def _getset_one(
    client: pycyphal.presentation.Client["Access_1"],
    reg_name: str,
    reg_val_str: str | None,
) -> Union[NoServiceTag, TimeoutTag, "Access_1.Response", "pycyphal.application.register.ValueConversionError"]:
    from uavcan.register import Access_1, Name_1
    from pycyphal.application.register import ValueProxy, ValueConversionError

    resp = await client(Access_1.Request(name=Name_1(reg_name)))
    if resp is None:
        return NoServiceTag()
    assert isinstance(resp, Access_1.Response)
    if reg_val_str is None or resp.value.empty:  # Modification is not required or there is no such register.
        return resp

    # Coerce the supplied value to the type of the remote register.
    assert not resp.value.empty
    val = ValueProxy(resp.value)
    try:
        val.assign_environment_variable(reg_val_str)
    except ValueConversionError as ex:  # Oops, not coercible (e.g., register is float[], value is string)
        return ex

    # Write the coerced value to the node; it may also modify it so return the response, not the coercion result.
    resp = await client(Access_1.Request(name=Name_1(reg_name), value=val.value))
    if resp is None:  # We got a response before but now we didn't, something is messed up so the result is different.
        return TimeoutTag()
    assert isinstance(resp, Access_1.Response)
    return resp
