# Copyright (c) 2022 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

from __future__ import annotations
import asyncio
import time
import json
import pytest
from tests.transport import TransportFactory
from tests.subprocess import execute_cli, Subprocess


@pytest.mark.asyncio
async def _unittest_logic() -> None:
    from pycyphal.transport.loopback import LoopbackTransport
    import pycyphal.application
    from pycyphal.application.register import ValueProxy
    from yakut.cmd.register_list._logic import list_names

    node = pycyphal.application.make_node(pycyphal.application.NodeInfo(), transport=LoopbackTransport(10))
    try:
        node.registry.clear()
        node.registry["a"] = ValueProxy("a")
        node.registry["b"] = ValueProxy("b")
        node.registry["c"] = ValueProxy("c")
        node.start()

        res = await list_names(
            node,
            lambda text: print(f"Progress: {text!r}"),
            node_ids=[10],
            optional_service=False,
            timeout=1.0,
        )
        assert not res.errors
        assert not res.warnings
        assert res.names_per_node == {
            10: ["a", "b", "c"],
        }

        res = await list_names(
            node,
            lambda text: print(f"Progress: {text!r}"),
            node_ids=[10, 3],
            optional_service=False,
            timeout=1.0,
        )
        assert len(res.errors) == 1
        assert not res.warnings
        assert res.names_per_node == {
            10: ["a", "b", "c"],
            3: None,
        }

        res = await list_names(
            node,
            lambda text: print(f"Progress: {text!r}"),
            node_ids=[10, 3],
            optional_service=True,
            timeout=1.0,
        )
        assert not res.errors
        assert len(res.warnings) == 1
        assert res.names_per_node == {
            10: ["a", "b", "c"],
            3: None,
        }
    finally:
        node.close()
        await asyncio.sleep(1)


def _unittest_cmd(transport_factory: TransportFactory) -> None:
    # Run a dummy node which we can query.
    bg_node = Subprocess.cli(
        "sub",
        "1000:uavcan.primitive.empty",
        environment_variables=transport_factory(10).environment,
    )
    time.sleep(2)
    expect_register = "uavcan.node.description"
    try:
        # Not keyed by node-ID.
        status, stdout, _ = execute_cli(
            "-j",
            "register-list",
            "--timeout=10",
            "10",
            environment_variables={"YAKUT_TRANSPORT": transport_factory(100).expression},
        )
        assert status == 0
        data = json.loads(stdout.strip())
        print(json.dumps(data, indent=4))
        assert len(data) > 1
        assert expect_register in data

        # Keyed by node-ID.
        status, stdout, _ = execute_cli(
            "-j",
            "register-list",
            "--timeout=10",
            "10,",  # Mind the comma!
            environment_variables={"YAKUT_TRANSPORT": transport_factory(100).expression},
        )
        assert status == 0
        data = json.loads(stdout.strip())
        print(json.dumps(data, indent=4))
        assert len(data) == 1
        assert expect_register in data["10"]

        # Poll non-existent nodes.
        status, stdout, _ = execute_cli(
            "-j",
            "register-list",
            "--timeout=3",  # Shorter timeout because some nodes are expected to not respond.
            "10..13",
            environment_variables={"YAKUT_TRANSPORT": transport_factory(100).expression},
            ensure_success=False,
        )
        assert status != 0  # Because timed out
        data = json.loads(stdout.strip())
        print(json.dumps(data, indent=4))
        assert len(data) == 3
        assert expect_register in data["10"]
        assert data["11"] is None
        assert data["12"] is None

        # Same but no error.
        status, stdout, _ = execute_cli(
            "-j",
            "register-list",
            "--timeout=3",  # Shorter timeout because some nodes are expected to not respond.
            "10..13",
            "--optional-service",
            environment_variables={"YAKUT_TRANSPORT": transport_factory(100).expression},
        )
        assert status == 0
        data = json.loads(stdout.strip())
        print(json.dumps(data, indent=4))
        assert len(data) == 3
        assert expect_register in data["10"]
        assert data["11"] is None
        assert data["12"] is None
    finally:
        bg_node.wait(10, interrupt=True)
