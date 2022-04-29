# Copyright (c) 2021 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

from __future__ import annotations
from typing import Any, TextIO
import decimal
import ruamel.yaml
import ruamel.yaml.constructor


class Loader:
    """
    YAML parsing facade.
    """

    def __init__(self) -> None:
        self._impl = ruamel.yaml.YAML()

    def load(self, text: str | TextIO) -> Any:
        return self._impl.load(text)


def _unittest_yaml() -> None:
    import pytest
    from ._dumper import Dumper

    ref = Dumper(explicit_start=True).dumps(
        {
            "abc": decimal.Decimal("-inf"),
            "def": [decimal.Decimal("nan"), {"qaz": decimal.Decimal("789")}],
        }
    )
    assert Loader().load(ref) == {
        "abc": -float("inf"),
        "def": [pytest.approx(float("nan"), nan_ok=True), {"qaz": pytest.approx(789)}],
    }
