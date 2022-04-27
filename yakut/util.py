# Copyright (c) 2019 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

from __future__ import annotations
from typing import Any, Callable, TypeVar
import decimal
import functools
import pycyphal


T = TypeVar("T")


def compose(*fs: Callable[..., T]) -> Callable[..., T]:
    """
    >>> compose(lambda x: x+2, lambda x: x*2)(3)
    10
    """
    return functools.reduce(_compose_unit, fs[::-1])


def _compose_unit(f: Callable[..., T], g: Callable[..., T]) -> Callable[..., T]:
    return lambda *a, **kw: f(g(*a, **kw))


def convert_transfer_metadata_to_builtin(
    transfer: pycyphal.transport.TransferFrom, **extra_fields: dict[str, Any]
) -> dict[str, Any]:
    out = {
        "timestamp": {
            "system": transfer.timestamp.system.quantize(_MICRO),
            "monotonic": transfer.timestamp.monotonic.quantize(_MICRO),
        },
        "priority": transfer.priority.name.lower(),
        "transfer_id": transfer.transfer_id,
        "source_node_id": transfer.source_node_id,
    }
    out.update(extra_fields)
    return {"_metadata_": out}


_MICRO = decimal.Decimal("0.000001")
