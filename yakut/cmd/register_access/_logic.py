# Copyright (c) 2022 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

from __future__ import annotations
import dataclasses
from typing import Sequence, TYPE_CHECKING, Union, Optional, Callable
import pycyphal
import yakut


if TYPE_CHECKING:
    import pycyphal.application
    from uavcan.register import Access_1


@dataclasses.dataclass
class Result:
    value_per_node: dict[int, Optional["Access_1.Response"]] = dataclasses.field(default_factory=dict)
    errors: list[str] = dataclasses.field(default_factory=list)
    warnings: list[str] = dataclasses.field(default_factory=list)


async def access(
    local_node: "pycyphal.application.Node",
    progress: Callable[[str], None],
    node_ids: Sequence[int],
    *,
    reg_name: str,
    reg_val_str: str | None,
    optional_service: bool,
    optional_register: bool,
    timeout: float,
) -> Result:
    res = Result()
    for nid, item in (await _access(local_node, progress, node_ids, reg_name, reg_val_str, timeout=timeout)).items():
        _logger.debug("Register @%r: %r", nid, item)
        res.value_per_node[nid] = None  # Error state is default state
        if isinstance(item, _NoService):
            if optional_service:
                res.warnings.append(f"Service not accessible at node {nid}, ignoring as requested")
            else:
                res.errors.append(f"Service not accessible at node {nid}")

        elif isinstance(item, _Timeout):
            res.errors.append(f"Request to node {nid} has timed out")

        elif isinstance(item, tuple):
            resp, exc = item
            res.value_per_node[nid] = resp
            res.errors.append(f"Assignment failed at node {nid}: {type(exc).__name__}: {exc}")

        else:
            res.value_per_node[nid] = item
            if item.value.empty and reg_val_str is not None:
                if optional_register:
                    res.warnings.append(f"Nonexistent register {reg_name!r} at node {nid} ignored as requested")
                else:
                    res.errors.append(f"Cannot assign nonexistent register {reg_name!r} at node {nid}")
    return res


class _NoService:
    pass


class _Timeout:
    pass


async def _access(
    local_node: pycyphal.application.Node,
    progress: Callable[[str], None],
    node_ids: Sequence[int],
    reg_name: str,
    reg_val_str: str | None,
    *,
    timeout: float,
) -> dict[
    int,
    Union[
        _NoService,
        _Timeout,
        "Access_1.Response",
        tuple["Access_1.Response", "pycyphal.application.register.ValueConversionError"],
    ],
]:
    from uavcan.register import Access_1

    out: dict[
        int,
        Access_1.Response | _NoService | _Timeout | pycyphal.application.register.ValueConversionError,
    ] = {}
    for nid in node_ids:
        progress(f"{nid: 5}: {reg_name!r}")
        cln = local_node.make_client(Access_1, nid)
        try:
            cln.response_timeout = timeout
            out[nid] = await _access_one(cln, reg_name, reg_val_str)
        finally:
            cln.close()
    return out


async def _access_one(
    client: pycyphal.presentation.Client["Access_1"],
    reg_name: str,
    reg_val_str: str | None,
) -> Union[
    _NoService,
    _Timeout,
    "Access_1.Response",
    tuple["Access_1.Response", "pycyphal.application.register.ValueConversionError"],
]:
    from uavcan.register import Access_1, Name_1
    from pycyphal.application.register import ValueProxy, ValueConversionError

    resp = await client(Access_1.Request(name=Name_1(reg_name)))
    if resp is None:
        return _NoService()
    assert isinstance(resp, Access_1.Response)
    if reg_val_str is None or resp.value.empty:  # Modification is not required or there is no such register.
        return resp

    # Coerce the supplied value to the type of the remote register.
    assert not resp.value.empty
    val = ValueProxy(resp.value)
    try:
        val.assign_environment_variable(reg_val_str)
    except ValueConversionError as ex:  # Oops, not coercible (e.g., register is float[], value is string)
        return resp, ex

    # Write the coerced value to the node; it may also modify it so return the response, not the coercion result.
    resp = await client(Access_1.Request(name=Name_1(reg_name), value=val.value))
    if resp is None:  # We got a response before but now we didn't, something is messed up so the result is different.
        return _Timeout()
    assert isinstance(resp, Access_1.Response)
    return resp


_logger = yakut.get_logger(__name__)
