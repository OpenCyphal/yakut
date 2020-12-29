# Copyright (c) 2020 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

import pytest
from tests.subprocess import execute_cli, CalledProcessError


def _unittest_doc() -> None:
    assert (
        len(execute_cli("-vv", "doc", timeout=2.0, log=False)[1].splitlines()) > 10
    ), "The doc output is suspiciously short"

    with pytest.raises(CalledProcessError):
        execute_cli("doc", "nonexistent-entry", timeout=2.0, log=False)
