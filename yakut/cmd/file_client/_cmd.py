# Copyright (c) 2021 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

from __future__ import annotations
import sys
from typing import TYPE_CHECKING
from pathlib import Path, PurePosixPath
import click
import pycyphal
import yakut
from yakut.int_set_parser import parse_int_set
from yakut.param.formatter import FormatterHints
from yakut.ui import ProgressReporter, show_error, show_warning
from yakut.util import EXIT_CODE_UNSUCCESSFUL
from ._list_files import list_files
from ._file_error import FileError

if TYPE_CHECKING:
    import pycyphal.application  # pylint: disable=ungrouped-imports
    import pycyphal.application.file  # pylint: disable=ungrouped-imports

_logger = yakut.get_logger(__name__)

@yakut.commandgroup(aliases="fcli")
@click.pass_context
@yakut.pass_purser
def file_client(purser: yakut.Purser, cmd: str):
    """Main CLI group."""
    pass

@file_client.command()
@click.argument("node_ids", type=parse_int_set)
@click.argument("path", default="")
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
@click.option(
    "--get-info",
    "-i",
    is_flag=True,
    help="Also request GetInfo for each file.",
)
@yakut.pass_purser
@yakut.asynchronous(interrupted_ok=True)
async def file_list(
    purser: yakut.Purser,
    node_ids: set[int] | int,
    path: Path,
    timeout: float,
    optional_service: bool,
    get_info: bool,
) -> None:
    _logger.debug("node_ids=%r, path=%r, timeout=%r", node_ids, path, timeout)
    node_ids_list = list(sorted(node_ids)) if isinstance(node_ids, set) else [node_ids]
    assert isinstance(node_ids_list, list) and all(isinstance(x, int) for x in node_ids_list)
    formatter = purser.make_formatter(FormatterHints(single_document=True))
    with purser.get_node("file_client_list", allow_anonymous=False) as node:
        with ProgressReporter() as prog:
            result = await list_files(
                node,
                prog,
                node_ids_list,
                path,
                optional_service=optional_service,
                get_info=get_info,
                timeout=timeout,
            )
    # The node is no longer needed.
    for msg in result.errors:
        show_error(msg)
    for msg in result.warnings:
        show_warning(msg)
    final = result.files_per_node if not isinstance(node_ids, int) else result.files_per_node[node_ids]
    sys.stdout.write(formatter(final))
    sys.stdout.flush()

    return EXIT_CODE_UNSUCCESSFUL if result.errors else 0

@file_client.command()
@click.argument("node_ids", type=parse_int_set)
@click.argument("path", default="")
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
@yakut.asynchronous(interrupted_ok=True)
async def file_remove(
    purser: yakut.Purser,
    node_ids: set[int] | int,
    path: Path,
    timeout: float,
) -> None:
    try:
        from uavcan.file import Path_2_0
        from uavcan.file import Error_1_0
        from uavcan.file import Modify_1_1
    except ImportError as ex:
        from yakut.cmd.compile import make_usage_suggestion

        raise click.ClickException(make_usage_suggestion(ex.name)) from None

    _logger.debug("node_ids=%r, path=%r, timeout=%r", node_ids, path, timeout)
    node_ids_list = list(sorted(node_ids)) if isinstance(node_ids, set) else [node_ids]
    assert isinstance(node_ids_list, list) and all(isinstance(x, int) for x in node_ids_list)

    error = False
    with purser.get_node("file_client_remove", allow_anonymous=False) as node:
        for nid in node_ids_list:
            cln = node.make_client(Modify_1_1, nid)
            try:
                cln.response_timeout = timeout
                resp = await cln(Modify_1_1.Request(source=Path_2_0(path=path)))
                if resp is None:
                    show_error(f"Request to node {nid} has timed out")
                    error = True
                    break
                assert isinstance(resp, Modify_1_1.Response)
                assert isinstance(resp.error, Error_1_0)
                if resp.error.value == Error_1_0.OK:
                    _logger.info("Removed path %r on node %r", path, nid)
                elif resp.error.value == Error_1_0.NOT_FOUND:
                    show_warning(f"Path {path} not found on node {nid}")
                else:
                    show_error(f"Error {FileError(resp.error.value)} while removing {path} on node {nid}")
                    error = True
                    
            finally:
                cln.close()

    return EXIT_CODE_UNSUCCESSFUL if error else 0

UNSTRUCTURED_MAX_SIZE = 256

@file_client.command()
@click.argument("node_id", type=int)
@click.argument("src")
@click.argument("dst", required=False)
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
@yakut.asynchronous(interrupted_ok=True)
async def file_read(
    purser: yakut.Purser,
    node_id: int,
    src: str,
    dst: str | None,
    timeout: float,
) -> None:
    try:
        from uavcan.file import Path_2_0
        from uavcan.file import Error_1_0
        from uavcan.file import Read_1_1
    except ImportError as ex:
        from yakut.cmd.compile import make_usage_suggestion

        raise click.ClickException(make_usage_suggestion(ex.name)) from None

    src = PurePosixPath(src)
    dst = Path(dst) if dst else Path(src.name)
    out = None
    total_read = 0
    error = False
    with purser.get_node("file_client_read", allow_anonymous=False) as node:
        prog = ProgressReporter()
        cln = node.make_client(Read_1_1, node_id)
        cln.response_timeout = timeout
        try:
            while True:
                resp = await cln(Read_1_1.Request(path=Path_2_0(path=str(src)), offset=total_read))
                if resp is None:
                    show_error(f"Request to node {node_id} has timed out")
                    error = True
                    break
                assert isinstance(resp, Read_1_1.Response)
                assert isinstance(resp.error, Error_1_0)
                if resp.error.value != Error_1_0.OK:
                    show_error(f"Error {FileError(resp.error.value)} while reading {src} on node {node_id}")
                    error = True
                    break

                bytes_read = len(resp.data.value)
                total_read += bytes_read
                prog(f"read {total_read} bytes")
                if out is None:
                    out = open(dst, "wb")
                
                out.write(resp.data.value)

                if bytes_read < UNSTRUCTURED_MAX_SIZE:
                    break
        finally:
            cln.close()
    
    if out is not None:
        out.close()

    return EXIT_CODE_UNSUCCESSFUL if error else 0

@file_client.command()
@click.argument("node_id", type=int)
@click.argument("src")
@click.argument("dst", required=False)
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
@yakut.asynchronous(interrupted_ok=True)
async def file_write(
    purser: yakut.Purser,
    node_id: int,
    src: str,
    dst: str | None,
    timeout: float,
) -> None:
    try:
        from uavcan.file import Path_2_0
        from uavcan.file import Error_1_0
        from uavcan.file import Write_1_1
        from uavcan.primitive import Unstructured_1_0
    except ImportError as ex:
        from yakut.cmd.compile import make_usage_suggestion

        raise click.ClickException(make_usage_suggestion(ex.name)) from None

    src = Path(src)
    dst = PurePosixPath(dst) if dst else PurePosixPath(src.name)
    file = open(src, "rb")

    total_written = 0
    error = False
    with purser.get_node("file_client_write", allow_anonymous=False) as node:
        prog = ProgressReporter()
        cln = node.make_client(Write_1_1, node_id)
        cln.response_timeout = timeout
        try:
            while True:
                chunk = file.read(UNSTRUCTURED_MAX_SIZE)
                req = Write_1_1.Request(
                    path=Path_2_0(path=str(dst)),
                    offset=total_written,
                    data=Unstructured_1_0(value=chunk)
                )
                resp = await cln(req)
                if resp is None:
                    show_error(f"Request to node {node_id} has timed out")
                    error = True
                    break
                assert isinstance(resp, Write_1_1.Response)
                assert isinstance(resp.error, Error_1_0)
                if resp.error.value != Error_1_0.OK:
                    show_error(f"Error {FileError(resp.error.value)} while writing {dst} on node {node_id}")
                    error = True
                    break

                bytes_written = len(chunk)
                total_written += bytes_written
                prog(f"written {total_written} bytes")

                if bytes_written < UNSTRUCTURED_MAX_SIZE:
                    break
        finally:
            cln.close()
    
    file.close()

    return EXIT_CODE_UNSUCCESSFUL if error else 0
