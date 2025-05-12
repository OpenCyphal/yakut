# Copyright (c) 2020 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

from __future__ import annotations
from tests.subprocess import execute_cli


def _unittest_publish() -> None:
    env = {"UAVCAN__LOOPBACK": "1", "UAVCAN__NODE__ID": "1234"}

    # Count zero, nothing to do.
    _, _, stderr = execute_cli(
        "-vv",
        "pub",
        "4444:uavcan.si.unit.force.Scalar.1.0",
        "{}",
        "--count",
        "0",
        timeout=5.0,
        environment_variables=env,
    )
    assert "nothing to do" in stderr.lower()

    # Invalid period.
    result, _, stderr = execute_cli(
        "-vv",
        "pub",
        "4444:uavcan.si.unit.force.Scalar.1.0",
        "{}",
        "--period=0",
        timeout=5.0,
        ensure_success=False,
        environment_variables=env,
    )
    assert result != 0
    assert "period" in stderr.lower()
    assert "seconds" in stderr.lower()

    # Transport not configured.
    result, _, stderr = execute_cli(
        "pub",
        "4444:uavcan.si.unit.force.Scalar.1.0",
        "{}",
        timeout=5.0,
        ensure_success=False,
    )
    assert result != 0
    assert "transport" in stderr.lower()
