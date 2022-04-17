# Copyright (c) 2019 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

from __future__ import annotations
from typing import Any, TYPE_CHECKING, Callable
import logging
import decimal
import pycyphal

if TYPE_CHECKING:
    import pycyphal.application

_logger = logging.getLogger(__name__)


async def fetch_registers(
    local_node: pycyphal.application.Node,
    node_id: int,
    predicate: Callable[[str], bool] = lambda *_: True,
    timeout: float = pycyphal.presentation.DEFAULT_SERVICE_REQUEST_TIMEOUT,
    priority: pycyphal.transport.Priority = pycyphal.transport.Priority.LOW,
) -> dict[str, pycyphal.application.register.ValueProxy] | None:
    """
    Obtain registers from the specified remote node for whose names the predicate is true.
    Returns None on network timeout.
    """
    from pycyphal.application.register import ValueProxy as RegisterValue
    from uavcan.register import Access_1, List_1, Name_1

    # Fetch register names.
    c_list = local_node.make_client(List_1, node_id)
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
        if not resp.name.name:
            break
        names.append(resp.name.name.tobytes().decode())
    _logger.debug("Register names fetched from node %r: %s", node_id, names)
    c_list.close()
    del c_list

    names = list(filter(predicate, names))

    # Then fetch the registers themselves.
    c_access = local_node.make_client(Access_1, node_id)
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


def convert_transfer_metadata_to_builtin(
    transfer: pycyphal.transport.TransferFrom, **extra_fields: dict[str, Any]
) -> dict[str, Any]:
    out = {
        "timestamp": {
            "system": transfer.timestamp.system.quantize(_MICRO),
            "monotonic": transfer.timestamp.monotonic.quantize(_MICRO),
        },
        "priority": transfer.priority.name.lower(),
        "transfer_id": transfer.transfer_id,
        "source_node_id": transfer.source_node_id,
    }
    out.update(extra_fields)
    return {"_metadata_": out}


_MICRO = decimal.Decimal("0.000001")
