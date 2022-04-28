# Copyright (c) 2022 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

from __future__ import annotations
import asyncio
import time
import json
from typing import Any
import pytest
from tests.dsdl import OUTPUT_DIR
from tests.transport import TransportFactory
from tests.subprocess import execute_cli, Subprocess


@pytest.mark.asyncio
async def _unittest_logic(compiled_dsdl: Any) -> None:
    from pycyphal.transport.loopback import LoopbackTransport
    import pycyphal.application
    from pycyphal.application.register import ValueProxy, Natural64
    from yakut.cmd.register_access._logic import access, Result

    _ = compiled_dsdl

    node = pycyphal.application.make_node(pycyphal.application.NodeInfo(), transport=LoopbackTransport(10))
    try:
        node.registry.clear()
        node.registry["a"] = ValueProxy("a")
        node.registry["b"] = ValueProxy(Natural64([1, 2, 3]))
        node.start()

        async def once(**kwargs: Any) -> Result:
            print()  # Separate from prior output
            out = await access(  # pylint: disable=missing-kwoa
                node,
                lambda text: print(f"Progress: {text!r}"),
                timeout=1.0,
                **kwargs,
            )
            print("Result:", out.value_per_node)
            print("Errors:", out.errors)
            print("Warns :", out.warnings)
            return out

        # READ EXISTING REGISTER FROM EXISTING NODE
        res = await once(
            node_ids=[10],
            reg_name="a",
            reg_val_str=None,
            optional_service=False,
            optional_register=False,
            asis=False,
        )
        assert not res.errors
        assert not res.warnings
        assert res.value_per_node == {
            10: "a",
        }

        # READ EXISTING REGISTER FROM EXISTING NODE, VALUE AS-IS
        res = await once(
            node_ids=[10],
            reg_name="a",
            reg_val_str=None,
            optional_service=False,
            optional_register=False,
            asis=True,
        )
        assert not res.errors
        assert not res.warnings
        assert len(res.value_per_node) == 1
        assert res.value_per_node[10]["string"]["value"]

        # READ EXISTING REGISTER BUT ONE NODE IS MISSING
        res = await once(
            node_ids=[10, 11],
            reg_name="b",
            reg_val_str=None,
            optional_service=False,
            optional_register=False,
            asis=False,
        )
        assert len(res.errors) == 1
        assert not res.warnings
        assert res.value_per_node == {
            10: [1, 2, 3],
            11: None,
        }

        # READ EXISTING REGISTER, ONE NODE IS MISSING, BUT OPTIONAL SERVICE IS ENABLED
        res = await once(
            node_ids=[10, 11],
            reg_name="b",
            reg_val_str=None,
            optional_service=True,
            optional_register=False,
            asis=False,
        )
        assert not res.errors
        assert len(res.warnings) == 1
        assert res.value_per_node == {
            10: [1, 2, 3],
            11: None,
        }

        # READ NONEXISTENT REGISTER, NO ERROR BECAUSE NOT ASKED TO MODIFY IT
        res = await once(
            node_ids=[10],
            reg_name="c",
            reg_val_str=None,
            optional_service=False,
            optional_register=False,
            asis=False,
        )
        assert not res.errors
        assert not res.warnings
        assert res.value_per_node == {
            10: None,
        }

        # WRITE NONEXISTENT REGISTER, ERROR
        res = await once(
            node_ids=[10],
            reg_name="c",
            reg_val_str="VALUE",
            optional_service=False,
            optional_register=False,
            asis=False,
        )
        assert len(res.errors) == 1
        assert not res.warnings
        assert res.value_per_node == {
            10: None,
        }

        # WRITE NONEXISTENT REGISTER, NO ERROR BECAUSE OPTIONAL REGISTER MODE
        res = await once(
            node_ids=[10],
            reg_name="c",
            reg_val_str="VALUE",
            optional_service=False,
            optional_register=True,
            asis=False,
        )
        assert not res.errors
        assert len(res.warnings) == 1
        assert res.value_per_node == {
            10: None,
        }

        # WRITE REGISTER, DATA NOT COERCIBLE
        res = await once(
            node_ids=[10],
            reg_name="b",
            reg_val_str="NOT VALID",
            optional_service=False,
            optional_register=False,
            asis=False,
        )
        assert len(res.errors) == 1
        assert len(res.warnings) == 0
        assert res.value_per_node == {
            10: [1, 2, 3],  # old value unchanged!
        }

    finally:
        node.close()
        await asyncio.sleep(1)


def _unittest_cmd(compiled_dsdl: Any, transport_factory: TransportFactory) -> None:
    _ = compiled_dsdl
    # Run a dummy node which we can query.
    bg_node = Subprocess.cli(
        "sub",
        "1000:uavcan.primitive.empty",
        environment_variables={
            "YAKUT_TRANSPORT": transport_factory(10).expression,
            "YAKUT_PATH": str(OUTPUT_DIR),
        },
    )
    time.sleep(3)
    expect_register = "uavcan.node.description"
    try:
        # READ EXISTING REGISTER
        status, stdout, _ = execute_cli(
            "--format=json",
            "register-access",
            "10",
            expect_register,
            environment_variables={
                "YAKUT_TRANSPORT": transport_factory(100).expression,
                "YAKUT_PATH": str(OUTPUT_DIR),
            },
        )
        assert status == 0
        data = json.loads(stdout.strip())
        print(json.dumps(data, indent=4))
        assert len(data) == 1
        assert data["10"] == ""

        # MODIFY REGISTER
        status, stdout, _ = execute_cli(
            "--format=json",
            "register-access",
            "10",
            expect_register,
            "Reference value",
            environment_variables={
                "YAKUT_TRANSPORT": transport_factory(100).expression,
                "YAKUT_PATH": str(OUTPUT_DIR),
            },
        )
        assert status == 0
        data = json.loads(stdout.strip())
        print(json.dumps(data, indent=4))
        assert len(data) == 1
        assert data["10"] == "Reference value"

        # FLATTEN
        status, stdout, _ = execute_cli(
            "--format=json",
            "register-access",
            "--flat",
            "10",
            expect_register,
            "Reference value",
            environment_variables={
                "YAKUT_TRANSPORT": transport_factory(100).expression,
                "YAKUT_PATH": str(OUTPUT_DIR),
            },
        )
        assert status == 0
        data = json.loads(stdout.strip())
        print(json.dumps(data, indent=4))
        assert data == "Reference value"
    finally:
        bg_node.wait(10, interrupt=True)


def _unittest_flatten() -> None:
    from yakut.cmd.register_access._cmd import _flatten

    assert "a" == _flatten({1: "a", 2: "a"})
    assert ["a", "b"] == _flatten({1: "a", 2: "b"})
    assert "a" == _flatten({1: "a", 2: None})
    assert None is _flatten({1: None, 2: None})
    assert None is _flatten({})
