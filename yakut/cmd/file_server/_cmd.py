# Copyright (c) 2021 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

from __future__ import annotations
import asyncio
from typing import Optional, Iterable, TYPE_CHECKING
from pathlib import Path
import click
import pyuavcan
import yakut
from . import AppDescriptor

if TYPE_CHECKING:
    import pyuavcan.application  # pylint: disable=ungrouped-imports
    import pyuavcan.application.file  # pylint: disable=ungrouped-imports

_logger = yakut.get_logger(__name__)


def _validate_root_directory(ctx: click.Context, param: click.Parameter, value: Iterable[str]) -> list[Path]:
    _ = param
    out: list[Path] = []
    for x in value:
        p = Path(x).resolve()
        if not p.is_dir() or not p.exists():
            raise click.UsageError(f"The specified root is not a valid directory: {x!r}", ctx=ctx)
        out.append(p)
    if not out:
        out.append(Path.cwd().resolve())  # This is the default.
    _logger.info("File server root directories: %r", list(map(str, out)))
    return out


@yakut.subcommand()
@click.argument(
    "roots",
    metavar="PATH",
    type=click.Path(exists=True, file_okay=False, resolve_path=True, path_type=str),
    callback=_validate_root_directory,
    nargs=-1,
)
@click.option(
    "--plug-and-play",
    "-P",
    metavar="FILE",
    type=click.Path(dir_okay=False, resolve_path=True, path_type=str),
    help=f"""
Run a centralized plug-and-play (PnP) node-ID allocator alongside the file server.
The file path points to the allocation table; if missing, a new file will be created.

The PnP allocator will be tracking the status of nodes and requesting uavcan.node.GetInfo automatically.

Low-level implementation details are available in the documentation for pyuavcan.application.plug_and_play
at https://pyuavcan.readthedocs.io.
""",
)
@click.option(
    "--update-software/--no-update-software",
    "+U/-U",
    default=False,
    show_default=True,
    help=f"""
Check if all online nodes are running up-to-date software; request update if not.
The software version is determined by invoking uavcan.node.GetInfo for every node that is online or
became online (or restarted).

When a node responds to uavcan.node.GetInfo, the root directory of the file server is scanned for software packages
that are suitable for the node.
If the node is already executing one of the available software packages or no suitable packages are found,
no further action is taken, as it is considered to be up-to-date.
Otherwise, if it is determined that the node should be updated, a standard software update request
of type uavcan.node.ExecuteCommand with COMMAND_BEGIN_SOFTWARE_UPDATE is sent.

To be considered by the server, node software packages shall reside in one of the root directories and
be named following this pattern:

\b
    NAME-HWMAJ.HWMIN-SWMAJ.SWMIN.VCS.CRC.app*
              |____|                |__|
        |__________|            |______|
    either minor or both        either CRC or both
    can be omitted if           CRC and VCS can be
    multiple hardware           omitted
    versions supported

The values are sourced from uavcan.node.GetInfo, and they are as follows:

NAME -- The name of the node; e.g., "com.zubax.telega".

HWMAJ, HWMIN -- Hardware version numbers.
The minor number or both of them can be omitted iff the package is compatible with multiple hardware revisions.

SWMAJ, SWMIN -- Software version numbers.

VCS, CRC --
The version control system (VCS) revision ID (e.g., git commit hash) and the CRC of the software package.
Both are hexadecimal numbers and both are optional: either the CRC alone or both VCS-hash and CRC can be omitted.

The fields are terminated by a literal string ".app",
which can be followed by arbitrary additional metadata (like a file extension).

Examples of compliant names:

\b
    com.zubax.telega-1.2-0.3.68620b82.28df0c432c2718cd.app.bin
    com.zubax.telega-0.3.app.zip

A node running software version X (as determined from uavcan.node.GetInfo)
is considered to require an update to Y (a local package file) if
the names are matching, the hardware version is compatible, and either condition holds:

- The software image CRC is defined for both X and Y and is different.

- The software version of Y is higher than X.

- The software version of Y is not older than X and the VCS hash is different.

- There may be additional heuristics to handle edge cases. Inspect logs or use --verbose to see details.
""",
)
@yakut.pass_purser
@yakut.asynchronous
async def file_server(
    purser: yakut.Purser, roots: list[Path], plug_and_play: Optional[str], update_software: bool
) -> None:
    """
    Run a standard UAVCAN file server; optionally run a plug-and-play node-ID allocator and software updater.

    The command takes a list of root directories for the file server.
    If none are given, the current working directory will be used as the only root.
    If more than one root is given, they all will be visible via UAVCAN as a single unified directory;
    the first directory takes precedence in case of conflicting entries.

    Examples:

    \b
        yakut file-server --plug-and-play=allocation_table.db --update-software
    """
    try:
        from pyuavcan.application import NodeInfo
        from pyuavcan.application.file import FileServer
        from pyuavcan.application.node_tracker import NodeTracker, Entry
        from uavcan.node import ExecuteCommand_1_1 as ExecuteCommand
        from uavcan.node import Heartbeat_1_0 as Heartbeat
    except ImportError as ex:
        from yakut.cmd.compile import make_usage_suggestion

        raise click.UsageError(make_usage_suggestion(ex.name))

    with purser.get_node("file_server", allow_anonymous=False) as node:
        node_tracker: Optional[NodeTracker] = None  # Initialized lazily only if needed.

        def get_node_tracker() -> NodeTracker:
            nonlocal node_tracker
            if node_tracker is None:
                _logger.info("Initializing the node tracker")
                node_tracker = NodeTracker(node)
            return node_tracker

        if plug_and_play:
            _logger.info("Starting a plug-and-play allocator using file %r", plug_and_play)
            from pyuavcan.application.plug_and_play import CentralizedAllocator

            alloc = CentralizedAllocator(node, plug_and_play)

            # The allocator requires integration with the node tracker, as explained in the docs.
            def register_node(node_id: int, _old_entry: Optional[Entry], entry: Optional[Entry]) -> None:
                if entry:
                    _logger.info("Node %r most recent heartbeat: %s", node_id, entry.heartbeat)
                    _logger.info("Node %r info: %s", node_id, entry.info or "<not available>")
                else:
                    _logger.info("Node %r went offline", node_id)
                unique_id = entry.info.unique_id.tobytes() if entry and entry.info else None
                alloc.register_node(node_id, unique_id)

            get_node_tracker().add_update_handler(register_node)

        fs = FileServer(node, roots)

        def check_software_update(node_id: int, _old_entry: Optional[Entry], entry: Optional[Entry]) -> None:
            if entry is None or entry.info is None:
                _logger.debug("Info for node %r is not (yet) available, cannot check software version", node_id)
                return
            heartbeat = entry.heartbeat
            assert isinstance(heartbeat, Heartbeat)
            if (
                heartbeat.mode.value == heartbeat.mode.SOFTWARE_UPDATE
                and heartbeat.health.value < heartbeat.health.WARNING
            ):
                # Do not skip an update request if the health is WARNING because it indicates a problem, possibly
                # caused by a missing application. Details: https://github.com/UAVCAN/yakut/issues/27
                _logger.info(
                    "Node %r does not require an update because it is in the software update mode already "
                    "and its health is acceptable: %r",
                    node_id,
                    heartbeat,
                )
                return
            _logger.info("Checking if node %r requires a software update...", node_id)
            info = entry.info
            assert isinstance(info, NodeInfo)
            package = _locate_package(fs, info)
            if package:
                _local_root_is_irrelevant, remote_visible_path = package
                cmd_request = ExecuteCommand.Request(
                    ExecuteCommand.Request.COMMAND_BEGIN_SOFTWARE_UPDATE,
                    str(remote_visible_path),
                )
                _logger.warning("Requesting node %r to update its software: %r", node_id, cmd_request)
                cmd_client = node.make_client(ExecuteCommand, node_id)
                cmd_client.priority = pyuavcan.transport.Priority.SLOW
                cmd_client.response_timeout = 5.0

                async def do_call() -> None:
                    result = await cmd_client.call(cmd_request)
                    if result is None:
                        _logger.error(
                            "Node %r did not respond to software update command %r in %.1f seconds",
                            node_id,
                            cmd_request,
                            cmd_client.response_timeout,
                        )
                        return
                    response, _ = result
                    assert isinstance(response, ExecuteCommand.Response)
                    if response.status != 0:
                        _logger.error(
                            "Node %r responded to software update command %r with error %r",
                            node_id,
                            cmd_request,
                            response.status,
                        )
                        return
                    _logger.info("Node %r confirmed software update command %r", node_id, cmd_request)

                asyncio.create_task(do_call())
            else:
                _logger.info("Node %r does not require a software update.", node_id)

        if update_software:
            _logger.info("Initializing the software update checker")
            # The check should be run in a separate thread because on a system with slow/busy disk IO this may cause
            # the file server to slow down significantly because the event loop would be blocked here on disk reads.
            get_node_tracker().add_update_handler(check_software_update)

        await asyncio.sleep(1e100)


def _locate_package(
    fs: pyuavcan.application.file.FileServer,
    info: pyuavcan.application.NodeInfo,
) -> Optional[tuple[Path, Path]]:
    """
    If at least one locally available application file is equivalent to the already running application,
    no update will take place.
    This is to support the case where the network may contain nodes running several different versions
    of the application.
    Also, without this capability, if the lookup roots contained more than one application package for a
    given node, they would be continuously replacing one another.
    """
    app = AppDescriptor.from_node_info(info)
    result: Optional[tuple[Path, Path]] = None
    for root, tail in fs.glob(app.make_glob_expression()):
        candidate = AppDescriptor.from_file_name(str(tail.name))
        if candidate:
            if app.is_equivalent(candidate):
                return None
            if app.should_update_to(candidate):
                result = root, tail
    return result
