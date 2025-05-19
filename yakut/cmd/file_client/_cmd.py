# Copyright (c) 2021 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

from __future__ import annotations
import sys
from pathlib import Path, PurePosixPath
import click
import pycyphal
import yakut
from yakut.int_set_parser import parse_int_set
from yakut.param.formatter import FormatterHints
from yakut.ui import ProgressReporter, show_error, show_warning
from yakut.util import EXIT_CODE_UNSUCCESSFUL
from ruamel.yaml import YAML
import dataclasses

yaml = YAML()

@yaml.register_class
@dataclasses.dataclass
class FileInfo:
    size: int
    timestamp: int
    is_file_not_directory: bool
    is_link: bool
    is_readable: bool
    is_writable: bool

@yaml.register_class
@dataclasses.dataclass
class FileResult:
    name: str
    info: FileInfo | None

_logger = yakut.get_logger(__name__)

@yakut.commandgroup(aliases="fcli")
@click.pass_context
@yakut.pass_purser
def file_client(purser: yakut.Purser, cmd: str):
    """File client commands."""
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
will be treated as an error.
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
async def ls(
    purser: yakut.Purser,
    node_ids: set[int] | int,
    path: Path,
    timeout: float,
    optional_service: bool,
    get_info: bool,
) -> None:
    """
    List files on a remote node using the standard Cyphal file service.
    """
    try:
        from pycyphal.application.file import FileClient2
        from uavcan.file import Path_2_0
    except ImportError as ex:
        from yakut.cmd.compile import make_usage_suggestion
        raise click.ClickException(make_usage_suggestion(ex.name))

    _logger.debug("node_ids=%r, path=%r, timeout=%r", node_ids, path, timeout)
    node_ids_list = list(sorted(node_ids)) if isinstance(node_ids, set) else [node_ids]
    assert isinstance(node_ids_list, list) and all(isinstance(x, int) for x in node_ids_list)

    errors: list[str] = []
    warnings: list[str] = []
    files_per_node: dict[int, list[str]] = {}

    formatter = purser.make_formatter(FormatterHints(single_document=True))

    with purser.get_node("file_client_ls", allow_anonymous=False) as node:
        prog = ProgressReporter()
        for nid in node_ids_list:
            files = []
            try:
                fc = FileClient2(node, nid, response_timeout=timeout)
                async for entry in fc.list(str(path)):
                    prog(f"List {nid: 5}: {len(files): 5}")
                    info = None
                    if get_info:
                        try:
                            filepath = chr(Path_2_0.SEPARATOR).join([path, entry])
                            resp = await fc.get_info(filepath)
                            info = FileInfo(
                                size = resp.size,
                                timestamp=resp.unix_timestamp_of_last_modification,
                                is_file_not_directory=resp.is_file_not_directory,
                                is_link=resp.is_link,
                                is_readable=resp.is_readable,
                                is_writable=resp.is_writeable
                            )
                        except Exception as e:
                            warnings.append(f"Could not get info for {path}/{entry} from node {nid}: {e}")

                    files.append(dataclasses.asdict(FileResult(name=entry, info=info)))

                files_per_node[nid] = files

            except Exception as e:
                if not (optional_service and "not supported" in str(e).lower()):
                    errors.append(f"Error listing {path} from node {nid}: {e}")

    for msg in errors:
        show_error(msg)
    for msg in warnings:
        show_warning(msg)

    final = files_per_node if not isinstance(node_ids, int) else files_per_node[node_ids]
    sys.stdout.write(formatter(final))
    sys.stdout.flush()

    return yakut.util.EXIT_CODE_UNSUCCESSFUL if errors else 0

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
async def rm(
    purser: yakut.Purser,
    node_ids: set[int] | int,
    path: Path,
    timeout: float,
) -> None:
    """
    Remove a file or directory on remote node(s) using the standard Cyphal file service.
    """
    try:
        from pycyphal.application.file import FileClient2
    except ImportError as ex:
        from yakut.cmd.compile import make_usage_suggestion
        raise click.ClickException(make_usage_suggestion(ex.name))

    _logger.debug("node_ids=%r, path=%r, timeout=%r", node_ids, path, timeout)
    node_ids_list = list(sorted(node_ids)) if isinstance(node_ids, set) else [node_ids]
    assert isinstance(node_ids_list, list) and all(isinstance(x, int) for x in node_ids_list)

    error = False
    with purser.get_node("file_client_rm", allow_anonymous=False) as node:
        prog = ProgressReporter()
        for nid in node_ids_list:
            try:
                fc = FileClient2(node, nid, response_timeout=timeout)
                prog(f"Remove from node {nid}")
                
                try:
                    await fc.remove(str(path))
                    _logger.info("Removed path %r on node %r", path, nid)
                except FileNotFoundError:
                    show_warning(f"Path {path} not found on node {nid}")
                except Exception as e:
                    show_error(f"Error removing {path} on node {nid}: {e}")
                    error = True

            except Exception as e:
                show_error(f"Error setting up file client for node {nid}: {e}")
                error = True

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
async def read(
    purser: yakut.Purser,
    node_id: int,
    src: str,
    dst: str | None,
    timeout: float,
) -> None:
    """
    Read a file from a remote node using the standard Cyphal file service.
    """
    try:
        from pycyphal.application.file import FileClient2
    except ImportError as ex:
        from yakut.cmd.compile import make_usage_suggestion
        raise click.ClickException(make_usage_suggestion(ex.name))

    src = PurePosixPath(src)
    dst = Path(dst) if dst else Path(src.name)
    error = False

    with purser.get_node("file_client_read", allow_anonymous=False) as node:
        prog = ProgressReporter()
        def read_progress_cb(bytes_read: int, bytes_total: int | None) -> None:
            prog(f"Read {bytes_read} bytes")

        try:
            fc = FileClient2(node, node_id, response_timeout=timeout)
            
            with open(dst, "wb") as out:
                res = await fc.read(str(src), progress=read_progress_cb)
                out.write(res)
                
            _logger.info("Read %d bytes from %r on node %r to %r", len(res), src, node_id, dst)

        except FileNotFoundError:
            show_error(f"File {src} not found on node {node_id}")
            error = True
        except Exception as e:
            show_error(f"Error reading {src} from node {node_id}: {e}")
            error = True

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
async def write(
    purser: yakut.Purser,
    node_id: int,
    src: str,
    dst: str | None,
    timeout: float,
) -> None:
    """
    Write a file to a remote node using the standard Cyphal file service.
    """
    try:
        from pycyphal.application.file import FileClient2
    except ImportError as ex:
        from yakut.cmd.compile import make_usage_suggestion
        raise click.ClickException(make_usage_suggestion(ex.name))

    src = Path(src)
    dst = PurePosixPath(dst) if dst else PurePosixPath(src.name)
    error = False

    with purser.get_node("file_client_write", allow_anonymous=False) as node:
        prog = ProgressReporter()
        def write_progress_cb(bytes_written: int, bytes_total: int | None) -> None:
            prog(f"Written {bytes_written}/{bytes_total} bytes")

        try:
            fc = FileClient2(node, node_id, response_timeout=timeout)
            
            with open(src, "rb") as file:
                data = file.read()
                await fc.write(str(dst), data, progress=write_progress_cb)
                
            _logger.info("Written %d bytes from %r to %r on node %r", len(data), src, dst, node_id)

        except Exception as e:
            show_error(f"Error writing {src} to node {node_id}: {e}")
            error = True

    return EXIT_CODE_UNSUCCESSFUL if error else 0
