# Copyright (c) 2022 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

from __future__ import annotations
import dataclasses
from typing import TYPE_CHECKING, Any, Union
from pycyphal.dsdl import update_from_builtin
import yakut
from yakut.register import unexplode

if TYPE_CHECKING:
    from uavcan.register import Value_1


class InvalidDirectiveError(ValueError):
    pass


@dataclasses.dataclass(frozen=True)
class Directive:
    registers_per_node: dict[int, dict[str, Union["Value_1", Any]]]
    """
    Any means that type coercion is required, so the register needs to be read first.
    """

    @staticmethod
    def load(ast: Any) -> Directive:
        if isinstance(ast, dict):
            registers_per_node: dict[int, dict[str, Union["Value_1", Any]]] = {}
            for node_id_str, node_spec in ast.items():
                try:
                    node_id = int(node_id_str)
                except ValueError:
                    raise InvalidDirectiveError(f"Not a valid node-ID: {node_id_str}") from None
                nd = _load_node(node_spec)
                registers_per_node[node_id] = nd
                _logger.debug("Loaded node directive for %d: %r", node_id, nd)
            return Directive(registers_per_node=registers_per_node)
        raise InvalidDirectiveError(f"Invalid directive: expected mapping (node_id->...), found {type(ast).__name__}")


def _load_node(ast: Any) -> dict[str, Union["Value_1", Any]]:
    if isinstance(ast, list) and all(isinstance(x, str) for x in ast):
        return {str(x): None for x in ast}

    if isinstance(ast, dict) and all(isinstance(x, str) for x in ast.keys()):
        return {reg_name: unexplode(ast) for reg_name, reg_spec in ast.items()}

    raise InvalidDirectiveError(
        f"Invalid node specifier: expected [register_name] or (register_name->register_value); "
        f"found {type(ast).__name__}"
    )


_logger = yakut.get_logger(__name__)
