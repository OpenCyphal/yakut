# Copyright (c) 2021 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

import math
import numpy as np
from typing import Callable, Optional, Any
import pytest
from yakut import hid_controller


def _unittest_parser() -> None:
    from yakut.cmd.publish._message_factory import construct_parser, DynamicExpression, ExpressionError

    axis = {0: 0.5, 5: -0.7}
    button = {2: True}
    toggle = {1: False}

    def make_control_sampler(selector: str) -> Optional[Callable[[], hid_controller.Sample]]:
        print("Constructing control sampler with selector:", selector)
        if selector == "7":
            return lambda: hid_controller.Sample(axis=axis, button=button, toggle=toggle)
        return None

    # Make loader and parse field spec.
    loader = construct_parser(make_control_sampler)
    ast = loader("{foo: !7 'sin(axis[0] + 1.0)', bar: !7 'toggle[1] and button[2]'}")
    print("AST:", ast)
    assert list(ast) == ["foo", "bar"]
    print("foo:", ast["foo"])
    print("bar:", ast["bar"])

    # Evaluate expressions.
    de = ast["foo"]
    assert isinstance(de, DynamicExpression)
    assert de.evaluate() == pytest.approx(math.sin(axis[0] + 1.0))
    de = ast["bar"]
    assert isinstance(de, DynamicExpression)
    assert de.evaluate() == toggle[1] and button[2]

    # Change the controls and re-evaluate.
    axis[0] *= -1
    toggle[1] = True
    de = ast["foo"]
    assert isinstance(de, DynamicExpression)
    assert de.evaluate() == pytest.approx(math.sin(axis[0] + 1.0))
    de = ast["bar"]
    assert isinstance(de, DynamicExpression)
    assert de.evaluate() == toggle[1] and button[2]

    # Ensure non-existent controls are read as zeros.
    axis.clear()
    toggle.clear()
    button.clear()
    de = ast["foo"]
    assert isinstance(de, DynamicExpression)
    assert de.evaluate() == pytest.approx(math.sin(0.0 + 1.0))
    de = ast["bar"]
    assert isinstance(de, DynamicExpression)
    assert de.evaluate() == False

    # Errors.
    with pytest.raises(ExpressionError, match=r"(?i).*YAML scalar.*"):
        loader("baz: !999 []")

    with pytest.raises(ExpressionError, match=r"(?i).*compile.*"):
        loader("baz: !999 0syntax error")

    with pytest.raises(ExpressionError, match=r"(?i).*controller.*selector.*"):
        loader("baz: !999 axis[0]")


def _unittest_message_factory(compiled_dsdl: Any) -> None:
    from yakut.cmd.publish._message_factory import MessageFactory
    from uavcan.primitive.array import Real64_1_0

    _ = compiled_dsdl

    axis = {0: 0.5, 5: -0.7}
    button = {2: True}
    toggle = {1: True}

    def make_control_sampler(selector: str) -> Optional[Callable[[], hid_controller.Sample]]:
        print("Constructing control sampler with selector:", selector)
        if selector == "7":
            return lambda: hid_controller.Sample(axis=axis, button=button, toggle=toggle)
        assert False

    expression = "{value: !7 '[axis[0], axis[1], button[0], button[2], toggle[0], toggle[1]]'}"
    mf = MessageFactory(Real64_1_0, expression, make_control_sampler)
    print(mf)

    msg = mf.build()
    assert isinstance(msg, Real64_1_0)
    assert np.allclose(msg.value, [0.5, 0.0, 0, 1, 0, 1])

    axis.clear()
    button.clear()
    toggle.clear()
    msg = mf.build()
    assert isinstance(msg, Real64_1_0)
    assert np.allclose(msg.value, [0.0, 0.0, 0, 0, 0, 0])
