# Copyright (c) 2021 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

from __future__ import annotations
import time
import functools
from typing import Callable, Dict, Type, Any, Optional
import pyuavcan
import yakut
from yakut.controller import Sample


__all__ = ["MessageFactory", "ControlSampler", "ControlSamplerFactory"]


ControlSampler = Callable[[], Sample]
"""
A function that samples a HID controller and returns its current state.
"""

ControlSamplerFactory = Callable[[str], Optional[ControlSampler]]
"""
Mapping from controls selector (which is a string) to the sampling function for that control.
The value is None if no such control exists.
This function is used during the initialization only; afterwards, the sampler is invoked during expression evaluation.
"""


class MessageFactory:
    def __init__(
        self,
        dtype: Type[pyuavcan.dsdl.CompositeObject],
        expression: str,
        control_sampler_factory: ControlSamplerFactory,
    ) -> None:
        self._dtype = dtype
        _logger.debug("%s: Constructed OK", self)

    def build(self) -> pyuavcan.dsdl.CompositeObject:
        pass

    def __repr__(self) -> str:
        out = pyuavcan.util.repr_attributes(self, self._dtype)
        assert isinstance(out, str)
        return out


@functools.lru_cache(None)
def construct_expression_context() -> Dict[str, Any]:
    import os
    import math
    import random
    import inspect

    modules = [
        (random, True),
        (time, True),
        (math, True),
        (os, False),
        (pyuavcan, False),
    ]

    out: Dict[str, Any] = {}
    for mod, wildcard in modules:
        out[mod.__name__] = mod
        if wildcard:
            out.update(
                {name: member for name, member in inspect.getmembers(mod) if not name.startswith("_")},
            )

    _logger.debug("Expression context contains %d items (on the next line):\n%s", len(out), out)
    return out


_logger = yakut.get_logger(__name__)
