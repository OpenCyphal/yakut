# Copyright (c) 2022 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

from __future__ import annotations
import dataclasses
from typing import TYPE_CHECKING, Union, Callable
import pycyphal
import yakut
from ._directive import Directive, RegisterDirective

if TYPE_CHECKING:
    import pycyphal.application
    from uavcan.register import Access_1


@dataclasses.dataclass(frozen=True)
class Tag:
    def __eq__(self, other: object) -> bool:
        """
        >>> TypeCoercionFailure("foo") == TypeCoercionFailure("bar")
        True
        >>> TypeCoercionFailure("") == Timeout()
        False
        """
        return issubclass(type(self), type(other)) and issubclass(type(other), type(self))


@dataclasses.dataclass(frozen=True)
class TypeCoercionFailure(Tag):
    msg: str

    __eq__ = Tag.__eq__


@dataclasses.dataclass(frozen=True)
class Timeout(Tag):
    pass


@dataclasses.dataclass(frozen=True)
class Skipped(Tag):
    pass


@dataclasses.dataclass
class Result:
    responses_per_node: dict[int, dict[str, Union[Tag, "Access_1.Response"]]] = dataclasses.field(default_factory=dict)
    """
    Keys of the innermost dict are always the same as those in the directive regardless of success.
    Processing of a node stops at first timeout, further items set to Skipped.
    Empty value means that there is no such register.
    """


async def do_calls(
    local_node: "pycyphal.application.Node",
    progress: Callable[[str], None],
    *,
    timeout: float,
    directive: Directive,
) -> Result:
    from uavcan.register import Access_1

    out = Result()
    for node_id, node_dir in directive.registers_per_node.items():
        cln = local_node.make_client(Access_1, node_id)
        try:
            cln.response_timeout = timeout
            responses: dict[str, Access_1.Response | Tag] = {k: Skipped() for k in node_dir}
            for idx, (reg_name, reg_dir) in enumerate(node_dir.items()):
                progress(f"{node_id: 5}: {reg_name!r}")
                resp = await _process_one(cln, reg_name, reg_dir)
                responses[reg_name] = resp
                _logger.info("Result for %r@%r (%r/%r): %r", reg_name, node_id, idx + 1, len(node_dir), resp)
                if isinstance(resp, Timeout):
                    break
        finally:
            cln.close()
        out.responses_per_node[node_id] = responses

    assert out.responses_per_node.keys() == directive.registers_per_node.keys()
    assert all(
        out.responses_per_node[node_id].keys() == directive.registers_per_node[node_id].keys()
        for node_id in directive.registers_per_node
    )
    return out


async def _process_one(
    client: pycyphal.presentation.Client["Access_1"],
    register_name: str,
    directive: RegisterDirective,
) -> Union[TypeCoercionFailure, Timeout, "Access_1.Response"]:
    from pycyphal.application.register import Value
    from uavcan.register import Access_1, Name_1

    # Construct the request object. If we are given the full type information then we can do the job in one query.
    req = Access_1.Request(name=Name_1(register_name), value=directive if isinstance(directive, Value) else None)

    # Go through the network. Empty response means there is no such register, no point proceeding.
    resp = await client(req)
    if resp is None:
        return Timeout()
    assert isinstance(resp, Access_1.Response)
    if resp.value.empty or isinstance(directive, Value):
        return resp

    # Perform type coercion to the discovered type.
    assert callable(directive)
    coerced = directive(resp.value)
    if coerced is None:
        return TypeCoercionFailure(f"Value not coercible to {resp.value}")

    # Send the write request with the updated coerced value.
    req = Access_1.Request(name=Name_1(register_name), value=coerced)
    assert isinstance(req.value, Value)
    return await client(req) or Timeout()


_logger = yakut.get_logger(__name__)
