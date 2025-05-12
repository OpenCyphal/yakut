# Copyright (c) 2020 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

from __future__ import annotations
from tests.subprocess import execute_cli


def _unittest_subscribe() -> None:
    env = {"UAVCAN__LOOPBACK": "1", "UAVCAN__NODE__ID": "1234"}
    # No subjects specified.
    _, _, stderr = execute_cli("-vv", "sub", timeout=5.0, environment_variables=env)
    assert "nothing to do" in stderr.lower()
    assert "no subject" in stderr.lower()
    # Count zero.
    _, _, stderr = execute_cli(
        "-vv", "sub", "4444:uavcan.si.unit.force.Scalar", "--count=0", timeout=5.0, environment_variables=env
    )
    assert "nothing to do" in stderr.lower()
    assert "count" in stderr.lower()


def _unittest_transport_not_specified() -> None:
    result, _, stderr = execute_cli(
        "sub",
        "4444:uavcan.si.unit.force.Scalar",
        timeout=5.0,
        ensure_success=False,
    )
    assert result != 0
    assert "transport" in stderr.lower()
