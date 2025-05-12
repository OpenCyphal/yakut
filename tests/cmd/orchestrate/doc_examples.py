# Copyright (c) 2021 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

from __future__ import annotations
import sys
import time
from pathlib import Path
import pytest
from tests.subprocess import Subprocess, execute_cli


if sys.platform.startswith("win"):  # pragma: no cover
    pytest.skip("These are GNU/Linux-only tests", allow_module_level=True)


def _unittest_example_basic() -> None:
    from yakut.cmd.orchestrate import EXAMPLE_BASIC, EXAMPLE_BASIC_STDOUT, EXAMPLE_BASIC_EXIT_CODE

    src = Path("src.orc.yaml")
    src.write_text(EXAMPLE_BASIC)

    # Run to completion.
    started_at = time.monotonic()
    proc = Subprocess.cli("-v", "orc", str(src.absolute()))
    exit_code, stdout, _stderr = proc.wait(timeout=20)
    assert 11 <= time.monotonic() - started_at <= 19
    assert exit_code == EXAMPLE_BASIC_EXIT_CODE
    assert stdout.splitlines() == EXAMPLE_BASIC_STDOUT.splitlines()

    # Premature termination.
    started_at = time.monotonic()
    proc = Subprocess.cli("-v", "orc", str(src.name))
    time.sleep(5.0)
    exit_code, stdout, _stderr = proc.wait(timeout=10, interrupt=True)
    assert 5 <= time.monotonic() - started_at <= 9
    assert exit_code not in (0, EXAMPLE_BASIC_EXIT_CODE)
    assert stdout.splitlines() == [EXAMPLE_BASIC_STDOUT.splitlines()[0], EXAMPLE_BASIC_STDOUT.splitlines()[-1]]


def _unittest_example_external() -> None:
    from yakut.cmd.orchestrate import EXAMPLE_EXTERNAL, EXAMPLE_EXTERNAL_VARS, EXAMPLE_EXTERNAL_ECHO
    from yakut.cmd.orchestrate import EXAMPLE_EXTERNAL_EXIT_CODE, EXAMPLE_EXTERNAL_STDOUT

    Path("ext.orc.yaml").write_text(EXAMPLE_EXTERNAL)
    Path("vars.orc.yaml").write_text(EXAMPLE_EXTERNAL_VARS)
    Path("echo.orc.yaml").write_text(EXAMPLE_EXTERNAL_ECHO)

    exit_code, stdout, _ = execute_cli("-v", "orc", "ext.orc.yaml", timeout=60.0, ensure_success=False)
    assert EXAMPLE_EXTERNAL_EXIT_CODE == exit_code
    assert stdout.splitlines() == EXAMPLE_EXTERNAL_STDOUT.splitlines()


def _unittest_example_pub_sub() -> None:
    from yakut.cmd.orchestrate import EXAMPLE_PUB_SUB, EXAMPLE_PUB_SUB_STDOUT

    Path("pub_sub.orc.yaml").write_text(EXAMPLE_PUB_SUB)

    _, stdout, _ = execute_cli("orc", "pub_sub.orc.yaml", timeout=300.0)
    # APPLY SORTING TO BATTLE TEMPORAL JITTER AS THE MESSAGE AND THE FIRST HEARTBEAT MAY COME SWAPPED.
    assert sorted(stdout.splitlines()) == sorted(EXAMPLE_PUB_SUB_STDOUT.splitlines())
