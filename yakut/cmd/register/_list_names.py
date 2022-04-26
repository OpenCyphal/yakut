# Copyright (c) 2022 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

from __future__ import annotations
from typing import Sequence, TYPE_CHECKING
import bisect
import pycyphal
import yakut
from ._common import Result, ProgressCallback

if TYPE_CHECKING:
    import pycyphal.application


async def list_names(
    local_node: "pycyphal.application.Node",
    progress: ProgressCallback,
    node_ids: Sequence[int],
    *,
    maybe_no_service: bool,
    timeout: float,
) -> Result:
    res = Result()
    for nid, names in (await _impl_list_names(local_node, progress, node_ids, timeout=timeout)).items():
        _logger.debug("Names @%r: %r", nid, names)
        if isinstance(names, _NoService):
            res.data_per_node[nid] = None
            if maybe_no_service:
                res.warnings.append(f"Service not accessible at node {nid}, ignoring as requested")
            else:
                res.errors.append(f"Service not accessible at node {nid}")
        else:
            lst = res.data_per_node.setdefault(nid, [])
            assert isinstance(lst, list)
            for idx, n in enumerate(names):
                if isinstance(n, _Timeout):
                    res.errors.append(f"Request #{idx} to node {nid} has timed out, data incomplete")
                else:
                    bisect.insort(lst, n)
    return res


class _NoService:
    pass


class _Timeout:
    pass


async def _impl_list_names(
    local_node: "pycyphal.application.Node",
    progress: ProgressCallback,
    node_ids: Sequence[int],
    *,
    timeout: float,
) -> dict[int, list[str | _Timeout] | _NoService]:
    from uavcan.register import List_1

    out: dict[int, list[str | _Timeout] | _NoService] = {}
    for nid in node_ids:
        cln = local_node.make_client(List_1, nid)
        try:
            cln.response_timeout = timeout
            name_list: list[str | _Timeout] | _NoService = []
            for idx in range(2**16):
                progress(f"#{idx:05}@{nid:05}")
                resp = await cln(List_1.Request(index=idx))
                assert isinstance(name_list, list)
                if resp is None:
                    if 0 == idx:  # First request timed out, assume service not supported or node is offline
                        name_list = _NoService()
                    else:  # Non-first request has timed out, assume network error
                        name_list.append(_Timeout())
                    break
                assert isinstance(resp, List_1.Response)
                name = resp.name.name.tobytes().decode(errors="replace")
                if not name:
                    break
                name_list.append(name)
        finally:
            cln.close()
        _logger.debug("Register names fetched from node %r: %r", nid, name_list)
        out[nid] = name_list
    progress("Done")
    return out


_logger = yakut.get_logger(__name__)
