# Copyright (c) 2019 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

from __future__ import annotations
from typing import Any, TYPE_CHECKING, Callable, Optional
import logging
import pycyphal
from yakut.util import METADATA_KEY

if TYPE_CHECKING:
    import pycyphal.application
    from pycyphal.application.register import Value
    from uavcan.register import Access_1


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


def unexplode_value(xpl: Any, prototype: Optional["Value"] = None) -> Optional["Value"]:
    """
    Reverse the effect of :func:`explode`.
    Returns None if the exploded form is invalid or not applicable to the prototype.
    Some simplified exploded forms can be unexploded only if the prototype
    is given because simplification erases type information.
    Some unambiguous simplified forms may be unexploded autonomously.

    >>> from tests.dsdl import ensure_compiled_dsdl
    >>> ensure_compiled_dsdl()
    >>> from pycyphal.application.register import Value, Natural16
    >>> ux = unexplode_value

    >>> ux(None)                                         # None is a simplified form of Empty.
    uavcan.register.Value...(empty=...)
    >>> ux({"integer8": {"value": [1,2,3]}, "_meta_": {"whatever": 0}})  # Metadata ignored.
    uavcan.register.Value...(integer8=...[1,2,3]))
    >>> ux({"integer8": {"value": [1,2,3]}})             # Pure Value (same as above)
    uavcan.register.Value...(integer8=...[1,2,3]))
    >>> ux([1,2,3]) is None                              # Prototype required.
    True
    >>> ux([1,2,3], Value(natural16=Natural16([0,0,0])))
    uavcan.register.Value...(natural16=...[1,2,3]))
    >>> ux(123, Value(natural16=Natural16([0])))
    uavcan.register.Value...(natural16=...[123]))
    >>> ux("abc", Value(natural16=Natural16([0]))) is None # Not applicable
    True

    Roundtrip:

    >>> unexplode_value(explode_value(Value(natural16=Natural16([0,1,2])), metadata={"a": 654}))
    uavcan.register.Value...(natural16=...[0,1,2]))
    """
    from pycyphal.dsdl import update_from_builtin
    from pycyphal.application.register import ValueProxy, Value, ValueConversionError

    if xpl is None:
        return Value()
    if isinstance(xpl, dict) and xpl:  # Empty dict is not a valid representation.
        try:
            res = update_from_builtin(
                Value(),
                {k: v for k, v in xpl.items() if k.strip("_") == k},  # Strip metadata fields.
            )
            assert isinstance(res, Value)
            return res
        except (ValueError, TypeError):
            pass
    if prototype is not None:
        ret = ValueProxy(prototype)
        try:
            ret.assign(xpl)
            assert isinstance(ret.value, Value)
            return ret.value
        except ValueConversionError:
            pass
    return None


def explode_value(val: "Value", *, simplify: bool = False, metadata: dict[str, Any] | None = None) -> Any:
    """
    Represent the register value using primitives (list, dict, string, etc.).
    If simplified mode is selected,
    the metadata and type information will be discarded and only a human-friendly representation of the
    value will be constructed.
    The reconstruction back to the original form is a bit involved but we provide :func:`unexplode` for that.
    The metadata is added under a key ``_meta_``, if there is any, but it is ignored in simplified mode.
    """
    if not simplify:
        out = pycyphal.dsdl.to_builtin(val)
        if metadata is not None:
            out[METADATA_KEY] = dict(metadata)
        return out
    return _simplify_value(val)


def _simplify_value(msg: "Value") -> Any:
    """
    Construct simplified human-friendly representation of the register value using primitives (list, string, etc.).
    Designed for use with commands that output compact register values in YAML/JSON/TSV/whatever,
    discarding the detailed type information.

    >>> from tests.dsdl import ensure_compiled_dsdl
    >>> ensure_compiled_dsdl()
    >>> from pycyphal.application.register import Value, Empty
    >>> from pycyphal.application.register import Integer8, Natural8, Integer32, String, Unstructured

    >>> None is _simplify_value(Value())  # empty is none
    True
    >>> _simplify_value(Value(integer8=Integer8([123])))
    123
    >>> _simplify_value(Value(natural8=Natural8([123, 23])))
    [123, 23]
    >>> _simplify_value(Value(integer32=Integer32([123, -23, 105])))
    [123, -23, 105]
    >>> _simplify_value(Value(integer32=Integer32([99999])))
    99999
    >>> _simplify_value(Value(string=String("Hello world")))
    'Hello world'
    >>> _simplify_value(Value(unstructured=Unstructured(b"Hello world")))
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


def get_access_response_metadata(val: "Access_1.Response") -> dict[str, Any]:
    """
    This is for use with :func:`explode_value`.
    """
    return {
        "mutable": val.mutable,
        "persistent": val.persistent,
    }


_logger = logging.getLogger(__name__)
