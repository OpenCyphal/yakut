# Copyright (c) 2020 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

from __future__ import annotations
from tests.subprocess import execute_cli


def _unittest_subscribe() -> None:
    env = {
        "YAKUT_TRANSPORT": "Loopback(1234)",
    }

    # No subjects specified.
    _, _, stderr = execute_cli("-vv", "sub", timeout=5.0, environment_variables=env)
    assert "nothing to do" in stderr.lower()
    assert "no subject" in stderr.lower()

    # Count zero.
    _, _, stderr = execute_cli(
        "-vv", "sub", "4444.uavcan.si.unit.force.Scalar.1.0", "--count=0", timeout=5.0, environment_variables=env
    )
    assert "nothing to do" in stderr.lower()
    assert "count" in stderr.lower()

    # Compiled DSDL not found.
    result, _, stderr = execute_cli(
        "sub", "4444.uavcan.si.unit.force.Scalar.1.0", timeout=5.0, ensure_success=False, environment_variables=env
    )
    assert result != 0
    assert "yakut compile" in stderr.lower()

    # Transport not specified.
    result, _, stderr = execute_cli("sub", "4444.uavcan.si.unit.force.Scalar.1.0", timeout=5.0, ensure_success=False)
    assert result != 0
    assert "transport" in stderr.lower()
