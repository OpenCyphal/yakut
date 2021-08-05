# Copyright (c) 2021 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

import io
from typing import Any, TextIO
import decimal
import ruamel.yaml


class Dumper:
    """
    YAML generation facade.
    Natively represents decimal.Decimal as floats in the output.
    """

    def __init__(self, explicit_start: bool = False):
        # We need to use the roundtrip representer to retain ordering of mappings, which is important for usability.
        self._impl = ruamel.yaml.YAML(typ="rt")
        # noinspection PyTypeHints
        self._impl.explicit_start = explicit_start
        self._impl.default_flow_style = None  # Choose between block/inline automatically
        self._impl.width = 2 ** 31  # Unlimited width

    def dump(self, data: Any, stream: TextIO) -> None:
        self._impl.dump(data, stream)

    def dumps(self, data: Any) -> str:
        s = io.StringIO()
        self.dump(data, s)
        return s.getvalue()


def _represent_decimal(self: ruamel.yaml.BaseRepresenter, data: decimal.Decimal) -> ruamel.yaml.ScalarNode:
    if data.is_finite():
        s = str(_POINT_ZERO_DECIMAL + data)  # The zero addition is to force float-like string representation
    elif data.is_nan():
        s = ".nan"
    elif data.is_infinite():
        s = ".inf" if data > 0 else "-.inf"
    else:
        assert False
    return self.represent_scalar("tag:yaml.org,2002:float", s)


ruamel.yaml.add_representer(decimal.Decimal, _represent_decimal, representer=ruamel.yaml.RoundTripRepresenter)

_POINT_ZERO_DECIMAL = decimal.Decimal("0.0")


def _unittest_yaml() -> None:
    ref = Dumper(explicit_start=True).dumps(
        {
            "abc": decimal.Decimal("-inf"),
            "def": [decimal.Decimal("nan"), {"qaz": decimal.Decimal("789")}],
        }
    )
    assert (
        ref
        == """---
abc: -.inf
def:
- .nan
- {qaz: 789.0}
"""
    )
