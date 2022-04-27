# Copyright (c) 2019 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

from __future__ import annotations
from typing import Any, TYPE_CHECKING, Callable
import logging
import pycyphal

if TYPE_CHECKING:
    import pycyphal.application
    from uavcan.register import Value_1


async def fetch_registers(
    presentation: pycyphal.presentation.Presentation,
    node_id: int,
    *,
    predicate: Callable[[str], bool] = lambda *_: True,
    timeout: float = pycyphal.presentation.DEFAULT_SERVICE_REQUEST_TIMEOUT,
    priority: pycyphal.transport.Priority = pycyphal.transport.Priority.LOW,
) -> dict[str, "pycyphal.application.register.ValueProxy"] | None:
    """
    Obtain registers from the specified remote node for whose names the predicate is true.
    Returns None on network timeout.
    """
    from pycyphal.application.register import ValueProxy as RegisterValue
    from uavcan.register import Access_1, List_1, Name_1

    # Fetch register names.
    c_list = presentation.make_client_with_fixed_service_id(List_1, node_id)
    c_list.response_timeout = timeout
    c_list.priority = priority
    names: list[str] = []
    while True:
        req: Any = List_1.Request(len(names))
        resp = await c_list(req)
        if resp is None:
            _logger.warning("Request to %r has timed out: %s", node_id, req)
            return None
        assert isinstance(resp, List_1.Response)
        if not resp.name.name.tobytes():
            break
        names.append(resp.name.name.tobytes().decode())
    _logger.debug("Register names fetched from node %r: %s", node_id, names)
    c_list.close()
    del c_list

    names = list(filter(predicate, names))

    # Then fetch the registers themselves.
    c_access = presentation.make_client_with_fixed_service_id(Access_1, node_id)
    c_access.response_timeout = timeout
    c_access.priority = priority
    regs: dict[str, RegisterValue] = {}
    for nm in names:
        req = Access_1.Request(name=Name_1(nm))
        resp = await c_access(req)
        if resp is None:
            _logger.warning("Request to %r has timed out: %s", node_id, req)
            return None
        assert isinstance(resp, Access_1.Response)
        regs[nm] = RegisterValue(resp.value)
    c_access.close()

    return regs


def value_as_simplified_builtin(msg: "Value_1") -> Any:
    """
    Designed for use with commands that output compact register values in YAML/JSON/TSV/whatever.
    discarding the detailed type information.

    >>> from tests.dsdl import ensure_compiled_dsdl
    >>> _ = ensure_compiled_dsdl()
    >>> from pycyphal.application.register import Value, Empty
    >>> from pycyphal.application.register import Integer8, Natural8, Integer32, String, Unstructured
    >>> None is value_as_simplified_builtin(Value())  # empty is none
    True
    >>> value_as_simplified_builtin(Value(integer8=Integer8([123])))
    123
    >>> value_as_simplified_builtin(Value(natural8=Natural8([123, 23])))
    [123, 23]
    >>> value_as_simplified_builtin(Value(integer32=Integer32([123, -23, 105])))
    [123, -23, 105]
    >>> value_as_simplified_builtin(Value(integer32=Integer32([99999])))
    99999
    >>> value_as_simplified_builtin(Value(string=String("Hello world")))
    'Hello world'
    >>> value_as_simplified_builtin(Value(unstructured=Unstructured(b"Hello world")))
    b'Hello world'
    """
    # This is kinda crude, perhaps needs improvement.
    if msg.empty:
        return None
    if msg.unstructured:
        return msg.unstructured.value.tobytes()
    if msg.string:
        return msg.string.value.tobytes().decode(errors="replace")
    ((_ty, val),) = pycyphal.dsdl.to_builtin(msg).items()
    val = val["value"]
    val = list(val.encode() if isinstance(val, str) else val)
    if len(val) == 1:  # One-element arrays shown as scalars.
        (val,) = val
    return val


_logger = logging.getLogger(__name__)
