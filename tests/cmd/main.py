# Copyright (c) 2019 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

import pytest
from tests.subprocess import execute_cli, CalledProcessError
import u.cmd


def _unittest_help() -> None:
    """
    Just make sure that the help can be displayed without issues.
    """
    execute_cli("--help", timeout=10.0)
    for cmd in dir(u.cmd):
        if not cmd.startswith("_") and cmd not in ("pyuavcan", "sys"):
            execute_cli(cmd, "--help", timeout=3.0)


def _unittest_error() -> None:
    with pytest.raises(CalledProcessError):
        execute_cli("invalid-command", timeout=2.0)

    with pytest.raises(CalledProcessError):  # Ambiguous abbreviation.
        execute_cli("c", timeout=2.0)
