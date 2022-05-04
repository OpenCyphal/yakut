# Copyright (c) 2021 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

from __future__ import annotations
import re
import shutil
import typing
import asyncio
import tempfile
from pathlib import Path
from typing import Tuple, Optional
import pytest
import pycyphal
from pycyphal.transport.serial import SerialTransport
from tests.subprocess import Subprocess
from tests.dsdl import OUTPUT_DIR


@pytest.mark.asyncio
async def _unittest_file_server_pnp(compiled_dsdl: typing.Any, serial_broker: str) -> None:
    from pycyphal.application import make_node, NodeInfo, make_registry
    from pycyphal.application.file import FileClient
    from pycyphal.application.plug_and_play import Allocatee

    _ = compiled_dsdl
    asyncio.get_running_loop().slow_callback_duration = 10.0
    root = tempfile.mkdtemp(".file_server", "root.")
    print("ROOT:", root)

    srv_proc = Subprocess.cli(
        "file-server",
        root,
        f"--plug-and-play={root}/allocation_table.db",
        environment_variables={
            "UAVCAN__SERIAL__IFACE": serial_broker,
            "UAVCAN__NODE__ID": "42",
            "YAKUT_PATH": str(OUTPUT_DIR),
        },
    )
    cln_node = make_node(
        NodeInfo(name="org.opencyphal.yakut.test.file.client"),
        make_registry(
            None,
            {
                "UAVCAN__SERIAL__IFACE": serial_broker,
                "UAVCAN__NODE__ID": "43",
                "YAKUT_PATH": str(OUTPUT_DIR),
            },
        ),
    )
    try:
        fc = FileClient(cln_node, 42, response_timeout=10.0)
        await asyncio.sleep(3.0)  # Let the server initialize.
        assert srv_proc.alive

        async def ls(path: str) -> typing.List[str]:
            out: typing.List[str] = []
            async for e in fc.list(path):
                out.append(e)
            return out

        # Check the file server.
        assert ["allocation_table.db"] == await ls("/")
        assert 0 == await fc.touch("/foo")
        assert ["allocation_table.db", "foo"] == await ls("/")
        assert 0 == await fc.write("/foo", b"Hello world!")
        assert b"Hello world!" == await fc.read("/foo")
        assert 0 == await fc.remove("/foo")
        assert 0 != await fc.remove("/foo")
        assert ["allocation_table.db"] == await ls("/")

        # Check the allocator.
        alloc_transport = SerialTransport(serial_broker, None)
        try:
            alloc_client = Allocatee(alloc_transport, b"badc0ffee0ddf00d")
            assert alloc_client.get_result() is None
            for _ in range(10):
                await asyncio.sleep(1.0)
                if alloc_client.get_result() is not None:
                    break
            assert alloc_client.get_result() is not None
            print("Allocated node-ID:", alloc_client.get_result())
        finally:
            alloc_transport.close()
    finally:
        srv_proc.wait(10.0, interrupt=True)
        cln_node.close()
        await asyncio.sleep(2.0)
    shutil.rmtree(root, ignore_errors=True)  # Do not remove on failure for diagnostics.


@pytest.mark.asyncio
async def _unittest_file_server_update(compiled_dsdl: typing.Any, serial_broker: str) -> None:
    from pycyphal.application import make_node, NodeInfo, make_registry, make_transport, Node
    from pycyphal.application.plug_and_play import Allocatee
    from uavcan.node import ExecuteCommand_1_1 as ExecuteCommand

    _ = compiled_dsdl
    asyncio.get_running_loop().slow_callback_duration = 10.0
    root = tempfile.mkdtemp(".file_server", "root.")
    print("ROOT:", root)

    class RemoteNode:
        def __init__(self, node: Node, execute_command_response: Optional[int]):
            self.last_command: Optional[ExecuteCommand.Request] = None
            self.node = node

            async def handle_execute_command(
                req: ExecuteCommand.Request, _meta: pycyphal.presentation.ServiceRequestMetadata
            ) -> Optional[ExecuteCommand.Response]:
                print(f"COMMAND FOR {self.node}:", req, f"(response {execute_command_response})")
                self.last_command = req
                if execute_command_response is not None:
                    return ExecuteCommand.Response(execute_command_response)
                return None

            self._srv_exec_cmd = self.node.get_server(ExecuteCommand)
            self._srv_exec_cmd.serve_in_background(handle_execute_command)
            self.node.start()

        def close(self) -> None:
            self.node.close()

        @staticmethod
        async def new(
            name: str,
            unique_id: bytes,
            hw_ver: Optional[Tuple[int, int]],
            sw_ver: Tuple[int, int],
            sw_vcs: Optional[int],
            sw_crc: Optional[int],
            *,
            execute_command_response: Optional[int] = 0,
        ) -> "RemoteNode":
            unique_id = unique_id.ljust(16)
            info = NodeInfo(name=name, unique_id=list(unique_id))
            if hw_ver:
                info.hardware_version.major, info.hardware_version.minor = hw_ver
            info.software_version.major, info.software_version.minor = sw_ver
            if sw_vcs is not None:
                info.software_vcs_revision_id = sw_vcs
            if sw_crc is not None:
                info.software_image_crc = [sw_crc]

            reg = make_registry(None, {"UAVCAN__SERIAL__IFACE": serial_broker, "YAKUT_PATH": str(OUTPUT_DIR)})
            trans = make_transport(reg)
            if trans.local_node_id is None:
                print("Starting a node-ID allocator for", info.unique_id.tobytes())
                alloc = Allocatee(trans, info.unique_id.tobytes())
                for _ in range(20):
                    await asyncio.sleep(1.0)
                    if alloc.get_result() is not None:
                        break
                allocated = alloc.get_result()
                if allocated is None:
                    raise TimeoutError("Node-ID allocation has timed out")
                print("Allocation for", info.unique_id.tobytes(), "is", allocated)
                reg["uavcan.node.id"] = allocated
                trans.close()
                trans = make_transport(reg)
            assert trans.local_node_id is not None

            return RemoteNode(make_node(info, reg, transport=trans), execute_command_response)

        def __del__(self) -> None:
            self.node.close()

    srv_proc = Subprocess.cli(
        "file-server",
        root,
        f"--plug-and-play={root}/allocation_table.db",
        f"-u",
        environment_variables={
            "UAVCAN__SERIAL__IFACE": serial_broker,
            "UAVCAN__NODE__ID": "42",
            "YAKUT_PATH": str(OUTPUT_DIR),
        },
    )
    try:
        await asyncio.sleep(3.0)  # Let the server initialize.
        assert srv_proc.alive

        # Populate some update files.
        Path(root, "x-1.2-3.4.a.b.app").touch()
        Path(root, "y-3.4.app").touch()

        # Spawn nodes in different configurations and check the results a few seconds later.
        # fmt: off
        #                            name UID     hw ver  sw ver  vcs   crc
        n_x_a = await RemoteNode.new("x", b"x_a", (1, 2), (3, 4), 0x0A, 0x0B)  # NO     same app
        n_x_b = await RemoteNode.new("x", b"x_b",   None, (3, 4), None, None)  # NO     missing params
        n_x_c = await RemoteNode.new("x", b"x_c", (1, 2), (3, 4), 0x0A, 0x0C)  # YES    CRC mismatch
        n_x_d = await RemoteNode.new("x", b"x_d", (1, 3), (3, 4), 0x0A, 0x0C)  # NO     wrong hardware

        n_y_a = await RemoteNode.new("y", b"y_a", (1, 2), (3, 4), 0x0A, None)  # NO     same app
        n_y_b = await RemoteNode.new("y", b"y_b", (1, 2), (3, 4), None, 0x0B)  # NO     same app
        n_y_c = await RemoteNode.new("y", b"y_c", (1, 2), (3, 5), None, 0x0B)  # NO     newer than the file
        n_y_d = await RemoteNode.new("y", b"y_d",   None, (3, 3), None, None)  # YES    older than the file

        n_z_a = await RemoteNode.new("z", b"z_a", (1, 2), (3, 4), 0x0A, 0x0B)  # NO     no such file
        # fmt: on

        await asyncio.sleep(10.0)  # Let the server do its job, this time should be enough.

        # Validate the results.
        def reap_command(n: RemoteNode) -> Optional[Tuple[int, str]]:
            n.close()
            if n.last_command is not None:
                return n.last_command.command, n.last_command.parameter.tobytes().decode()
            return None

        assert reap_command(n_x_a) is None
        assert reap_command(n_x_b) is None
        assert reap_command(n_x_c) == (ExecuteCommand.Request.COMMAND_BEGIN_SOFTWARE_UPDATE, "x-1.2-3.4.a.b.app")
        assert reap_command(n_x_d) is None

        assert reap_command(n_y_a) is None
        assert reap_command(n_y_b) is None
        assert reap_command(n_y_c) is None
        assert reap_command(n_y_d) == (ExecuteCommand.Request.COMMAND_BEGIN_SOFTWARE_UPDATE, "y-3.4.app")

        assert reap_command(n_z_a) is None

        # Server failure cases -- update is required but cannot be performed due to ExecuteCommand server failure.
        n_x_e = await RemoteNode.new(
            "x", b"x_e", None, (3, 4), 0xA, 0xC, execute_command_response=ExecuteCommand.Response.STATUS_INTERNAL_ERROR
        )  # Return error
        n_x_f = await RemoteNode.new("x", b"x_f", None, (3, 4), 0xA, 0xC, execute_command_response=None)  # Timeout

        await asyncio.sleep(10.0)  # Let the server do its job, this time should be enough.

        assert reap_command(n_x_e) == (ExecuteCommand.Request.COMMAND_BEGIN_SOFTWARE_UPDATE, "x-1.2-3.4.a.b.app")
        assert reap_command(n_x_f) == (ExecuteCommand.Request.COMMAND_BEGIN_SOFTWARE_UPDATE, "x-1.2-3.4.a.b.app")

        # Check the logs to ensure that the server recognized the failures correctly.
        _, _, stderr = srv_proc.wait(10.0, interrupt=True)
        assert isinstance(stderr, str)
        error_lines = [x for x in stderr.splitlines() if "ERR" in x]
        print(len(error_lines), "error lines out of", len(stderr.splitlines()), "total")
        assert len(error_lines) == 2
        assert re.match(
            rf".*Node {n_x_e.node.id} responded to .* with error {ExecuteCommand.Response.STATUS_INTERNAL_ERROR}",
            error_lines[0],
        )
        assert re.match(
            rf".*Node {n_x_f.node.id} did not respond.*",
            error_lines[1],
        )
    finally:
        srv_proc.wait(10.0, interrupt=True)
        await asyncio.sleep(2.0)
    shutil.rmtree(root, ignore_errors=True)  # Do not remove on failure for diagnostics.
