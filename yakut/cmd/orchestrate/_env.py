# Copyright (c) 2021 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

from __future__ import annotations
from typing import Dict, Any


NAME_SEP = "."
ITEM_SEP = " "


class EnvironmentVariableError(ValueError):
    pass


def encode(value: Any) -> bytes:
    """
    Converts the register value to binary environment variable value as defined by the UAVCAN Specification,
    the Register interface.

    >>> encode(123)
    b'123'
    >>> encode('hello world')
    b'hello world'
    >>> encode(b'hello')
    b'hello'
    >>> encode([True, False, True])
    b'1 0 1'
    >>> encode([60_000, 50_000])
    b'60000 50000'
    >>> encode(300_000)
    b'300000'
    >>> encode([2 ** 32, 0])
    b'4294967296 0'
    >>> encode(-10_000)
    b'-10000'
    >>> encode([-10_000, 40_000])
    b'-10000 40000'
    >>> encode([-(2 ** 31), 2 ** 31])
    b'-2147483648 2147483648'
    >>> encode(1.0)
    b'1.0'
    """
    if isinstance(value, str):
        return value.encode()
    if isinstance(value, bytes):
        return value
    if isinstance(value, (int, bool)):
        return encode(str(int(value)))
    if isinstance(value, float):
        return encode(str(value))
    if isinstance(value, list):
        return b" ".join(map(encode, value))
    raise EnvironmentVariableError(f"Cannot encode register value of type {type(value).__name__}")


def flatten_registers(spec: Dict[str, Any], prefix: str = "") -> Dict[str, Any]:
    """
    >>> flatten_registers({"FOO": "BAR", "a": {"b": 123, "c": [456, 789]}})  # doctest: +NORMALIZE_WHITESPACE
    {'FOO': 'BAR',
     'a.b': 123,
     'a.c': [456, 789]}
    """
    out: Dict[str, Any] = {}
    for k, v in spec.items():
        name = NAME_SEP.join((prefix, k)) if prefix else k
        if isinstance(v, dict):
            out.update(flatten_registers(v, name))
        else:
            out[name] = v
    return out
