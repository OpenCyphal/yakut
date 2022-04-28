# Copyright (c) 2022 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

from __future__ import annotations
import dataclasses
from typing import TYPE_CHECKING, Any, Union, Callable, Optional
import yakut
from yakut.register import unexplode

if TYPE_CHECKING:
    from pycyphal.application.register import Value


Unexploder = Callable[["Value"], Optional["Value"]]
"""
Returns None if the value is not coercible to the prototype.
"""

RegisterDirective = Union["Value", Unexploder]


class InvalidDirectiveError(ValueError):
    pass


@dataclasses.dataclass(frozen=True)
class Directive:
    registers_per_node: dict[int, dict[str, RegisterDirective]]
    """
    The directive contains either values or factories that take a prototype and return the value (or None on error).
    When a value is available, it is to be written immediately in one request.
    Otherwise, a read request will need to be executed first to discover the type of the register;
    the factory will then use that information to perform coercion (which may fail).
    """

    @staticmethod
    def load(ast: Any) -> Directive:
        if isinstance(ast, dict):
            registers_per_node: dict[int, dict[str, RegisterDirective]] = {}
            for node_id_orig, node_spec in ast.items():
                try:
                    node_id = int(node_id_orig)
                except ValueError:
                    raise InvalidDirectiveError(f"Not a valid node-ID: {node_id_orig}") from None
                nd = _load_node(node_spec)
                registers_per_node[node_id] = nd
                _logger.debug("Loaded node directive for %d: %r", node_id, nd)
            return Directive(registers_per_node=registers_per_node)
        raise InvalidDirectiveError(f"Invalid directive: expected mapping (node_id->...), found {type(ast).__name__}")


def _load_node(ast: Any) -> dict[str, RegisterDirective]:
    from pycyphal.application.register import Value

    if isinstance(ast, list) and all(isinstance(x, str) for x in ast):
        return {str(x): Value() for x in ast}

    if isinstance(ast, dict) and all(isinstance(x, str) for x in ast.keys()):
        return {reg_name: _load_leaf(reg_spec) for reg_name, reg_spec in ast.items()}

    raise InvalidDirectiveError(
        f"Invalid node specifier: expected [register_name] or (register_name->register_value); "
        f"found {type(ast).__name__}"
    )


def _load_leaf(exploded: Any) -> RegisterDirective:
    return unexplode(exploded) or (lambda proto: unexplode(exploded, proto))


_logger = yakut.get_logger(__name__)


def _unittest_directive() -> None:
    from pytest import raises
    from pycyphal.application.register import Value, String, Integer32, Bit

    class CV(Value):  # type: ignore
        def __eq__(self, other: object) -> bool:
            if isinstance(other, Value):
                return repr(self) == repr(other)
            return NotImplemented

    # Load full form
    dr = Directive.load(
        {
            "0": {
                "a": {"value": {"string": {"value": "z"}}},
            },
            1: {
                "b": {"string": {"value": "y"}},
                "c": None,
                "d": {"empty": {}},
            },
            " 2 ": ["e", "f"],
        },
    )
    assert dr.registers_per_node == {
        0: {"a": CV(string=String("z"))},
        1: {"b": CV(string=String("y")), "c": CV(), "d": CV()},
        2: {"e": CV(), "f": CV()},
    }

    # Load simplified form, deferred callables returned.
    dr = Directive.load(
        {
            "0": {
                "a": [0, 1, 2],
                "b": 456,
            },
        },
    )
    assert dr and len(dr.registers_per_node) == 1
    assert {"a", "b"} == dr.registers_per_node[0].keys()
    uxp = dr.registers_per_node[0]["a"]
    assert callable(uxp)
    assert CV(integer32=Integer32([0, 1, 2])) == uxp(Value(integer32=Integer32([0] * 3)))
    assert CV(bit=Bit([False, True, True])) == uxp(Value(bit=Bit([False] * 3)))
    uxp = dr.registers_per_node[0]["b"]
    assert callable(uxp)
    assert CV(integer32=Integer32([456])) == uxp(Value(integer32=Integer32([0])))

    # Errors.
    with raises(InvalidDirectiveError):
        Directive.load([])
    with raises(InvalidDirectiveError):
        Directive.load("")
    with raises(InvalidDirectiveError):
        Directive.load({"z": []})
    with raises(InvalidDirectiveError):
        Directive.load({"z": "q"})
