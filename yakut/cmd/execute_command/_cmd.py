# Copyright (c) 2022 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

from __future__ import annotations
import sys
from typing import TYPE_CHECKING, Callable, Sequence, Optional, Any
import asyncio
import click
import pycyphal
import yakut
from yakut.int_set_parser import parse_int_set, INT_SET_USER_DOC
from yakut.ui import ProgressReporter, show_error, show_warning
from yakut.param.formatter import FormatterHints
from yakut.util import EXIT_CODE_UNSUCCESSFUL

if TYPE_CHECKING:
    import pycyphal.application
    from uavcan.node import ExecuteCommand_1

_logger = yakut.get_logger(__name__)


_HELP = f"""
Invoke uavcan.node.ExecuteCommand on a group of nodes.

The response objects are returned as a per-node mapping unless the set of node-IDs is one integer,
in which case only that object is returned without the node-ID.

The command may be specified either as an explicit integer or as a mnemonic name defined in the
uavcan.node.ExecuteCommand service specification; e.g., restart=65535, begin_software_update=65533;
abbreviations are also accepted.

Restart many nodes at once, some of which may not be present (for Cyphal/CAN this would be the entire network):

\b
    yakut execute-command 0-128 restart -e
    yakut execute-command 0-128 65535 -e    # Same, with the command code given explicitly.

Request multiple nodes to install the same software image
(requires a file server node) (also see the file server command):

\b
    y cmd 122-126 begin_software_update /path/to/software/image

{INT_SET_USER_DOC}
"""


def _parse_status_set(inp: str) -> set[int] | None:
    """
    >>> _parse_status_set("") is None
    True
    >>> _parse_status_set("1") == {1}
    True
    >>> _parse_status_set("1-5") == {1, 2, 3, 4}
    True
    """
    if not inp:
        return None
    ins = parse_int_set(inp)
    return set(ins) if not isinstance(ins, (int, float)) else {ins}


@yakut.subcommand(aliases="cmd", help=_HELP)
@click.argument("node_ids", type=parse_int_set)
@click.argument("command")
@click.argument("parameter", default="")
@click.option(
    "--expect",
    "-e",
    type=_parse_status_set,
    default="0",
    metavar="[STATUS_CODES]",
    is_flag=False,
    flag_value="",
    help=f"""
Specify the set of status codes that shall be accepted as success (the default is only zero).
The set notation is supported; e.g., use 0-256 to accept any status code as success.

Using this option without any value (or an empty string)
will result in sending the requests simultaneously without requiring the nodes to respond and not validating the status
(fire and forget).
This is occasionally useful because some nodes may be unable to respond to certain requests such as COMMAND_RESTART;
some nodes may not support this service at all.

{INT_SET_USER_DOC}
""",
)
@click.option(
    "--timeout",
    "-T",
    type=float,
    default=pycyphal.presentation.DEFAULT_SERVICE_REQUEST_TIMEOUT,
    show_default=True,
    metavar="SECONDS",
    help="Service response timeout.",
)
@yakut.pass_purser
@yakut.asynchronous()
async def execute_command(
    purser: yakut.Purser,
    node_ids: set[int] | int,
    command: str,
    parameter: str,
    expect: set[int] | None,
    timeout: float,
) -> int:
    _logger.debug(
        "node_ids=%r command=%r parameter=%r expect=%r timeout=%r", node_ids, command, parameter, expect, timeout
    )
    command_parsed = _parse_command(command)
    del command
    formatter = purser.make_formatter(FormatterHints(single_document=True))
    try:
        from uavcan.node import ExecuteCommand_1
    except ImportError as ex:
        from yakut.cmd.compile import make_usage_suggestion

        raise click.ClickException(make_usage_suggestion(ex.name)) from None

    request = ExecuteCommand_1.Request(command=command_parsed, parameter=parameter)
    # Ensure the parameters are valid before constructing the node.
    # Unfortunately, PyCyphal does not allow us to pass pre-serialized objects to a presentation-layer port instance.
    # Perhaps this capability should be added one day.
    _ = pycyphal.dsdl.serialize(request)

    with purser.get_node("execute_command", allow_anonymous=False) as node:
        with ProgressReporter() as prog:
            result = await _run(
                node,
                prog,
                list(sorted(node_ids)) if isinstance(node_ids, set) else [node_ids],
                request,
                timeout=timeout,
                fire_and_forget=expect is None,
            )

    success = True

    def error(text: str) -> None:
        nonlocal success
        success = False
        show_error(text)

    if expect is not None:
        for nid, resp in result.items():
            if resp is None:
                error(f"Timed out while waiting for response from node {nid}")
            elif resp.status not in expect:
                desc = _status_code_to_name(resp.status) or "(unknown status code)"
                error(f"Node {nid} returned unexpected status code: {resp.status} {desc}")
            else:
                _logger.debug("Success @%r: %r", nid, resp)
    else:
        show_warning("Responses not checked as requested")

    final: dict[int, Any] = {
        nid: pycyphal.dsdl.to_builtin(resp) if resp is not None else None for nid, resp in result.items()
    }
    if isinstance(node_ids, int):
        final = final[node_ids]
    sys.stdout.write(formatter(final))
    sys.stdout.flush()
    return 0 if success else EXIT_CODE_UNSUCCESSFUL


async def _run(
    local_node: "pycyphal.application.Node",
    progress: Callable[[str], None],
    node_ids: Sequence[int],
    request: "ExecuteCommand_1.Request",
    *,
    timeout: float,
    fire_and_forget: bool,
) -> dict[int, Optional["ExecuteCommand_1.Response"]]:
    from uavcan.node import ExecuteCommand_1

    async def once(nid: int) -> None:
        cln = local_node.make_client(ExecuteCommand_1, nid)
        try:
            cln.response_timeout = timeout
            result[nid] = await cln(request)
        finally:
            cln.close()

    result: dict[int, ExecuteCommand_1.Response | None] = {}
    if not fire_and_forget:
        for nid in node_ids:
            progress(f"{nid: 5}")
            await once(nid)
    else:
        for r in await asyncio.gather(
            *(asyncio.ensure_future(once(nid)) for nid in node_ids),
            return_exceptions=True,
        ):
            if isinstance(r, BaseException):
                raise r
        # noinspection PyTypeChecker
        result = dict(sorted(result.items()))

    return result


_DSDL_REQUEST_COMMAND_CONSTANT_PREFIX = "COMMAND_"
_DSDL_RESPONSE_STATUS_CONSTANT_PREFIX = "STATUS_"


def _parse_command(inp: str) -> int:
    """
    This function shall not be invoked before the command handler is entered because it requires the standard DSDL
    namespace to be available (or you would need to handle the DSDL not found error here).

    >>> _parse_command("0")
    0
    >>> _parse_command("0x100")
    256
    >>> _parse_command("restart") == _parse_command("ReStArT") == _parse_command("res") == 0xFFFF
    True
    >>> _parse_command("store_persistent_states") == 65530
    True
    >>> _parse_command("no matching option")  # doctest:+IGNORE_EXCEPTION_DETAIL
    Traceback (most recent call last):
    ...
    ClickException: ...
    >>> _parse_command("")  # doctest:+IGNORE_EXCEPTION_DETAIL
    Traceback (most recent call last):
    ...
    ClickException: ...
    """
    for fun in (int, lambda x: int(x, 0)):
        try:
            return fun(inp)  # type: ignore
        except ValueError:
            pass

    from uavcan.node import ExecuteCommand_1

    ty = ExecuteCommand_1.Request
    std = {
        x[len(_DSDL_REQUEST_COMMAND_CONSTANT_PREFIX) :]: getattr(ty, x)
        for x in dir(ty)
        if x.startswith(_DSDL_REQUEST_COMMAND_CONSTANT_PREFIX)
    }
    matches = {k: v for k, v in std.items() if k.lower().startswith(inp.lower())}
    if len(matches) == 1:
        return int(next(iter(matches.values())))
    raise click.ClickException(f"Command not understood: {inp!r}")


def _status_code_to_name(code: int) -> str | None:
    """
    >>> _status_code_to_name(0)
    'SUCCESS'
    >>> _status_code_to_name(1)
    'FAILURE'
    >>> _status_code_to_name(254) is None
    True
    """
    from uavcan.node import ExecuteCommand_1

    ty = ExecuteCommand_1.Response
    return {
        getattr(ty, x): x[len(_DSDL_RESPONSE_STATUS_CONSTANT_PREFIX) :]
        for x in dir(ty)
        if x.startswith(_DSDL_RESPONSE_STATUS_CONSTANT_PREFIX)
    }.get(code)
