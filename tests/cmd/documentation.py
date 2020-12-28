# Copyright (c) 2020 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

import pytest
from tests.subprocess import execute_u, CalledProcessError


def _unittest_doc() -> None:
    assert len(execute_u("-vv", "doc", timeout=2.0).splitlines()) > 10, "The doc output is suspiciously short"

    with pytest.raises(CalledProcessError):
        execute_u("doc", "nonexistent-entry", timeout=2.0)
