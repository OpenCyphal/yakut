# Copyright (c) 2021 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

from __future__ import annotations
import time
from types import CodeType
from typing import Callable, Dict, Type, Any, Optional
from collections import defaultdict
import dataclasses
import pyuavcan
import yakut
from yakut import hid_controller


Sampler = Callable[[], hid_controller.Sample]
"""
A function that samples a HID controller and returns its current state.
"""

ControlSamplerFactory = Callable[[str], Optional[Sampler]]
"""
Mapping from controls selector (which is a string) to the sampling function for that control.
The value is None if no such control exists.
This function is used during the initialization only; afterwards, the sampler is invoked during expression evaluation.
"""


class MessageFactory:
    def __init__(
        self,
        dtype: Type[pyuavcan.dsdl.CompositeObject],
        field_spec: str,
        control_sampler_factory: ControlSamplerFactory,
    ) -> None:
        self._dtype = dtype
        loader = construct_yaml_loader(control_sampler_factory)
        self._ast = loader(field_spec)
        _logger.debug("%s: Constructed OK", self)

    def build(self) -> pyuavcan.dsdl.CompositeObject:
        started_at = time.monotonic()
        result = evaluate(self._ast)
        elapsed = time.monotonic() - started_at
        _logger.debug("%s: Computed in %.3f sec: %r", self, elapsed, result)
        obj = pyuavcan.dsdl.update_from_builtin(self._dtype(), result)
        return obj

    def __repr__(self) -> str:
        out = pyuavcan.util.repr_attributes(self, self._dtype, self._ast)
        assert isinstance(out, str)
        return out


class DynamicExpression:
    def __init__(self, control_sampler: Sampler, compiled_expression: CodeType) -> None:
        self._control_sampler = control_sampler
        self._code = compiled_expression
        self._context = DynamicExpression._make_evaluation_context()

    def evaluate(self) -> Any:
        sample = self._control_sampler()
        _logger.debug("%s: Control sample: %r", self, sample)
        for name, value in dataclasses.astuple(sample):
            self._context[name] = defaultdict(int, value) if isinstance(value, dict) else value
        started_at = time.monotonic()
        result = eval(self._code, self._context)
        elapsed = time.monotonic() - started_at
        _logger.debug("%s: Evaluated in %.3f sec, result: %r", self, elapsed, result)
        return result

    def __repr__(self) -> str:
        out = pyuavcan.util.repr_attributes(self, repr(self._code), self._control_sampler)
        assert isinstance(out, str)
        return out

    @staticmethod
    def _make_evaluation_context() -> Dict[str, Any]:
        import os
        import math
        import inspect

        out = {name: member for name, member in inspect.getmembers(math) if not name.startswith("_")}
        out["os"] = os
        return out


def evaluate(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {key: evaluate(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return list(map(evaluate, obj))
    if isinstance(obj, (bool, int, float)) or obj is None:
        return obj
    if isinstance(obj, DynamicExpression):
        return obj.evaluate()
    raise TypeError(f"Unexpected object type: {type(obj).__name__}")  # pragma: no cover


def construct_yaml_loader(control_sampler_factory: ControlSamplerFactory) -> Callable[[str], Any]:
    """
    Make the YAML loader that can correctly parse dynamic expressions.
    The loader accepts YAML string and returns the parsed object.

    - https://yaml.readthedocs.io/en/latest/dumpcls.html?highlight=register_class#dumping-python-classes
    - https://stackoverflow.com/questions/50996060/python-ruamel-yaml-dumps-tags-with-quotes
    - https://gist.github.com/bossjones/e7071871db18b930872d4e362e763c24
    """
    # Normally, we should be using yakut.yaml, but this component requires very advanced functionality that is not
    # supported by the facade, so we have to access the underlying library directly.
    import ruamel.yaml

    def construct_dynamic_expression(
        _constructor: ruamel.yaml.Constructor,
        tag: str,
        node: ruamel.yaml.Node,
    ) -> DynamicExpression:
        assert isinstance(tag, str), "Internal error"
        _logger.debug("Constructing dynamic expression from YAML node %r with tag %r", node, tag)
        if not isinstance(node, ruamel.yaml.ScalarNode):
            raise ValueError(f"Expression must be a YAML scalar, not {type(node).__name__}")

        controller_selector = tag.lstrip("!")  # Remove YAML-related overheads.
        expression_text = str(node.value)
        _logger.debug("Parsing checkpoint: selector=%r, expression=%r", controller_selector, expression_text)

        try:
            compiled_expression = compile(expression_text, "<dynamic_expression>", "eval")
        except Exception as ex:
            raise ValueError(f"Could not compile dynamic expression:\n{expression_text!r}\n{ex}") from ex
        _logger.debug("Compiled: %r", compiled_expression)

        control_sampler = control_sampler_factory(controller_selector)
        if control_sampler is None:
            raise ValueError(f"There is no controller that matches selector {controller_selector!r}")
        _logger.debug("Control sampler: %r", control_sampler)

        return DynamicExpression(
            control_sampler=control_sampler,
            compiled_expression=compiled_expression,
        )

    loader = ruamel.yaml.YAML()
    loader.constructor.add_multi_constructor("", construct_dynamic_expression)
    return loader.load


_logger = yakut.get_logger(__name__)
