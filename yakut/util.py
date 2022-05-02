# Copyright (c) 2019 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

from __future__ import annotations
from typing import Any, Callable, TypeVar
import decimal
import functools
import pycyphal


T = TypeVar("T")

METADATA_KEY = "_meta_"

EXIT_CODE_UNSUCCESSFUL = 100
"""
The command was invoked and executed correctly but the desired goal could not be attained for external reasons.
"""


def compose(*fs: Callable[..., T]) -> Callable[..., T]:
    """
    >>> compose(lambda x: x+2, lambda x: x*2)(3)
    10
    """
    return functools.reduce(_compose_unit, fs[::-1])


def _compose_unit(f: Callable[..., T], g: Callable[..., T]) -> Callable[..., T]:
    return lambda *a, **kw: f(g(*a, **kw))


def convert_transfer_metadata_to_builtin(
    transfer: pycyphal.transport.TransferFrom,
    *,
    dtype: Any,
    **extra_fields: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    return {
        METADATA_KEY: {
            "ts_system": transfer.timestamp.system.quantize(_MICRO),
            "ts_monotonic": transfer.timestamp.monotonic.quantize(_MICRO),
            "source_node_id": transfer.source_node_id,
            "transfer_id": transfer.transfer_id,
            "priority": transfer.priority.name.lower(),
            "dtype": get_dtype_full_name_with_version(dtype),
            **extra_fields,
        }
    }


@functools.lru_cache(None)
def get_dtype_full_name_with_version(dtype: Any) -> str:
    return str(pycyphal.dsdl.get_model(dtype))


_MICRO = decimal.Decimal("0.000001")
