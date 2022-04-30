# Copyright (c) 2022 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

from __future__ import annotations
import asyncio
import time
from typing import Any
import json
import tempfile
from pathlib import Path
from pprint import pprint
import pytest
from tests.dsdl import OUTPUT_DIR
from tests.transport import TransportFactory
from tests.subprocess import execute_cli, Subprocess


@pytest.mark.asyncio
async def _unittest_caller(compiled_dsdl: Any) -> None:
    from pycyphal.transport.loopback import LoopbackTransport
    import pycyphal.application
    from pycyphal.application.register import ValueProxy, Natural64, Value, String
    from yakut.cmd.register_batch._directive import Directive
    from yakut.cmd.register_batch._caller import Skipped, Timeout, TypeCoercionFailure, do_calls

    _ = compiled_dsdl

    node = pycyphal.application.make_node(pycyphal.application.NodeInfo(), transport=LoopbackTransport(10))
    try:
        node.registry.clear()
        node.registry["a"] = ValueProxy("a")
        node.registry["b"] = ValueProxy(Natural64([1, 2, 3]))
        node.registry["c"] = ValueProxy(Natural64([3, 2, 1]))
        node.start()

        res = await do_calls(
            node,
            lambda x: print("Progress:", x),
            timeout=1.0,
            directive=Directive(
                registers_per_node={
                    10: {
                        "c": lambda _: None,  # Type coercion failure does not interrupt further processing.
                        "a": Value(string=String("z")),
                        "d": Value(string=String("n")),  # No such register.
                        "b": lambda v: v,
                    },
                    11: {
                        "y": lambda _: None,
                        "z": lambda _: None,
                    },
                }
            ),
        )
        pprint(res.responses_per_node)
        assert res.responses_per_node.keys() == {10, 11}

        assert res.responses_per_node[10]["a"].value.string.value.tobytes().decode() == "z"  # type: ignore
        assert list(res.responses_per_node[10]["b"].value.natural64.value) == [1, 2, 3]  # type: ignore
        assert isinstance(res.responses_per_node[10]["c"], TypeCoercionFailure)
        assert res.responses_per_node[10]["d"].value.empty  # type: ignore

        assert res.responses_per_node[11]["y"] == Timeout()
        assert res.responses_per_node[11]["z"] == Skipped()

    finally:
        node.close()
        await asyncio.sleep(1)


def _unittest_cmd(compiled_dsdl: Any, transport_factory: TransportFactory) -> None:
    _ = compiled_dsdl
    file = Path(tempfile.mktemp("yakut_register_batch_test.yaml"))
    # Run dummy nodes which we can query.
    bg_nodes = [
        Subprocess.cli(
            "sub",
            "1000:uavcan.primitive.empty",
            environment_variables={
                **transport_factory(10 + idx).environment,
                "YAKUT_PATH": str(OUTPUT_DIR),
            },
        )
        for idx in range(2)
    ]
    time.sleep(1)
    try:
        # READ INPUT KEYED
        file.write_text("{10: [uavcan.node.id, uavcan.node.description], 11: [uavcan.node.id]}")
        status, stdout, _ = execute_cli(
            "register-batch",
            f"--file={file}",
            environment_variables={
                **transport_factory(100).environment,
                "YAKUT_PATH": str(OUTPUT_DIR),
            },
        )
        assert status == 0
        data = json.loads(stdout.strip())
        print(json.dumps(data, indent=4))
        assert len(data) == 2
        assert data["10"]["uavcan.node.id"] == 10
        assert data["10"]["uavcan.node.description"] == ""
        assert data["11"]["uavcan.node.id"] == 11

        # MODIFY INPUT KEYED
        file.write_text("{10: {uavcan.node.description: TEN}, 11: {uavcan.node.description: ELEVEN}}")
        status, stdout, _ = execute_cli(
            "register-batch",
            f"--file={file}",
            environment_variables={
                **transport_factory(100).environment,
                "YAKUT_PATH": str(OUTPUT_DIR),
            },
        )
        assert status == 0
        data = json.loads(stdout.strip())
        print(json.dumps(data, indent=4))
        assert len(data) == 2
        assert data["10"]["uavcan.node.description"] == "TEN"
        assert data["11"]["uavcan.node.description"] == "ELEVEN"

        # READ INPUT FLAT, OUTPUT FLAT
        file.write_text("[uavcan.node.id, uavcan.node.description]")
        status, stdout, _ = execute_cli(
            "register-batch",
            f"--file={file}",
            "10",
            environment_variables={
                **transport_factory(100).environment,
                "YAKUT_PATH": str(OUTPUT_DIR),
            },
        )
        assert status == 0
        data = json.loads(stdout.strip())
        print(json.dumps(data, indent=4))
        assert len(data) == 2
        assert data["uavcan.node.id"] == 10
        assert data["uavcan.node.description"] == "TEN"

        # MODIFY INPUT FLAT, OUTPUT KEYED
        file.write_text("{uavcan.node.description: 'TEN OR ELEVEN'}")
        status, stdout, _ = execute_cli(
            "register-batch",
            f"--file={file}",
            "10,11",
            environment_variables={
                **transport_factory(100).environment,
                "YAKUT_PATH": str(OUTPUT_DIR),
            },
        )
        assert status == 0
        data = json.loads(stdout.strip())
        print(json.dumps(data, indent=4))
        assert len(data) == 2
        assert data["10"]["uavcan.node.description"] == "TEN OR ELEVEN"
        assert data["11"]["uavcan.node.description"] == "TEN OR ELEVEN"

        # MODIFY INPUT FLAT, OUTPUT KEYED, ONE TIMED OUT WITH ERROR
        file.write_text("{uavcan.node.description: XXX}")
        status, stdout, _ = execute_cli(
            "register-batch",
            f"--file={file}",
            "10-13",
            environment_variables={
                **transport_factory(100).environment,
                "YAKUT_PATH": str(OUTPUT_DIR),
            },
            ensure_success=False,
        )
        assert status != 0
        data = json.loads(stdout.strip())
        print(json.dumps(data, indent=4))
        assert len(data) == 3
        assert data["10"]["uavcan.node.description"] == "XXX"
        assert data["11"]["uavcan.node.description"] == "XXX"
        assert not data["12"]

        # MODIFY INPUT FLAT, OUTPUT KEYED, NO SUCH REGISTER ERROR
        file.write_text("{nonexistent.register: 123}")
        status, stdout, _ = execute_cli(
            "register-batch",
            f"--file={file}",
            "10,11",
            environment_variables={
                **transport_factory(100).environment,
                "YAKUT_PATH": str(OUTPUT_DIR),
            },
            ensure_success=False,
        )
        assert status != 0
        data = json.loads(stdout.strip())
        print(json.dumps(data, indent=4))
        assert len(data) == 2
        assert data["10"]["nonexistent.register"] is None
        assert data["11"]["nonexistent.register"] is None

        # MODIFY INPUT FLAT, OUTPUT KEYED, NO SUCH REGISTER, ERROR IGNORED
        file.write_text("{nonexistent.register: 123}")
        status, stdout, _ = execute_cli(
            "register-batch",
            f"--file={file}",
            "10,11",
            "--optional-register",
            environment_variables={
                **transport_factory(100).environment,
                "YAKUT_PATH": str(OUTPUT_DIR),
            },
        )
        assert status == 0
        data = json.loads(stdout.strip())
        print(json.dumps(data, indent=4))
        assert len(data) == 2
        assert data["10"]["nonexistent.register"] is None
        assert data["11"]["nonexistent.register"] is None

        # MODIFY INPUT FLAT, OUTPUT FLAT, DETAILED
        file.write_text("[uavcan.node.id]")
        status, stdout, _ = execute_cli(
            "register-batch",
            f"--file={file}",
            "10",
            "--detailed",
            environment_variables={
                **transport_factory(100).environment,
                "YAKUT_PATH": str(OUTPUT_DIR),
            },
        )
        assert status == 0
        data = json.loads(stdout.strip())
        print(json.dumps(data, indent=4))
        assert len(data) == 1
        assert data["uavcan.node.id"]["natural16"]["value"] == [10]

        # MODIFY INPUT FLAT, OUTPUT FLAT, DETAILED, FILTERED EMPTY
        file.write_text("[uavcan.node.id]")
        status, stdout, _ = execute_cli(
            "register-batch",
            f"--file={file}",
            "10",
            "--only=iv",  # The requested register is not immutable-volatile so it will be skipped.
            environment_variables={
                **transport_factory(100).environment,
                "YAKUT_PATH": str(OUTPUT_DIR),
            },
        )
        assert status == 0
        data = json.loads(stdout.strip())
        print(json.dumps(data, indent=4))
        assert data == {}
    finally:
        for bg in bg_nodes:
            bg.wait(10, interrupt=True)
        file.unlink()
