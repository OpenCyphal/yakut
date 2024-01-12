# Copyright (c) 2021 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

from __future__ import annotations
import time
import json
import typing
from pytest import approx
from tests.dsdl import OUTPUT_DIR
from tests.subprocess import execute_cli, Subprocess


def _unittest_publish_expression_a(compiled_dsdl: typing.Any) -> None:
    _ = compiled_dsdl
    env = {
        "YAKUT_PATH": str(OUTPUT_DIR),
        "UAVCAN__UDP__IFACE": "127.0.0.1",
        "UAVCAN__NODE__ID": "1234",
    }

    proc_sub = Subprocess.cli(
        "-j",
        "sub",
        "7654:uavcan.primitive.array.Real64.1.0",
        environment_variables=env,
    )

    wall_time_when_started = time.time()
    execute_cli(
        "-vv",
        "pub",
        "7654:uavcan.primitive.array.Real64.1.0",
        "value: [!$ 1 + n + t * 0.1, !$ 'cos(A(0, 12))', !$ 'B(0, 34)', !$ 'B(0, 56)', 123456, !$ 123456, !$ time()]",
        #           {1.0, 2.1}           1.0                 0              0          123456     123456     (time)
        "--count=2",
        timeout=10.0,
        environment_variables=env,
    )

    _, stdout, _ = proc_sub.wait(10.0, interrupt=True)
    print(stdout)
    msgs = list(map(json.loads, stdout.splitlines()))
    print(msgs)
    assert msgs[0]["7654"]["value"] == [
        approx(1.0),
        approx(1.0),
        approx(0),
        approx(0),
        approx(123456),
        approx(123456),
        approx(wall_time_when_started, abs=10.0),
    ]
    assert msgs[1]["7654"]["value"] == [
        approx(2.1),
        approx(1.0),
        approx(0),
        approx(0),
        approx(123456),
        approx(123456),
        approx(wall_time_when_started + 1.0, abs=10.0),
    ]


def _unittest_publish_expression_b(compiled_dsdl: typing.Any) -> None:
    _ = compiled_dsdl
    env = {
        "YAKUT_PATH": str(OUTPUT_DIR),
        "UAVCAN__UDP__IFACE": "127.0.0.1",
        "UAVCAN__NODE__ID": "1234",
    }

    proc_sub = Subprocess.cli(
        "-j",
        "sub",
        "7654:uavcan.primitive.String.1.0",
        environment_variables=env,
    )

    execute_cli(
        "pub",
        "7654:uavcan.primitive.String.1.0",
        "value: !$ str(pycyphal.dsdl.get_model(dtype))",
        "--count=1",
        timeout=10.0,
        environment_variables=env,
    )

    _, stdout, _ = proc_sub.wait(10.0, interrupt=True)
    print(stdout)
    msg = json.loads(stdout)
    print(msg)
    assert msg["7654"]["value"] == "uavcan.primitive.String.1.0"
