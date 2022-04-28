# Copyright (c) 2022 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

from __future__ import annotations
import dataclasses
from typing import TYPE_CHECKING, Optional, Union, Any
import pycyphal
import yakut
from yakut.progress import ProgressCallback
from ._directive import Directive

if TYPE_CHECKING:
    import pycyphal.application
    from uavcan.register import Access_1, Value_1


@dataclasses.dataclass
class Result:
    responses_per_node: dict[int, list[Optional["Access_1.Response"]]] = dataclasses.field(default_factory=dict)
    errors: list[str] = dataclasses.field(default_factory=list)


async def execute(
    local_node: "pycyphal.application.Node",
    progress: ProgressCallback,
    *,
    timeout: float,
    directive: Directive,
) -> Result:
    from uavcan.register import Access_1

    out = Result()
    for node_id, reg_dir in directive.registers_per_node.items():
        cln = local_node.make_client(Access_1, node_id)
        try:
            cln.response_timeout = timeout
            responses: list[Access_1.Response | None] = []
            for nm in reg_dir:
                progress(f"{nm!r} @{node_id: 5}")
                resp = await _process_one(cln, nm, reg_dir)
                responses.append(resp)
                if resp is None:
                    out.errors.append(f"Request of register {nm!r} from node {node_id} has timed out")
                    break
        finally:
            cln.close()
        out.responses_per_node[node_id] = responses
    return out


async def _process_one(
    client: pycyphal.presentation.Client["Access_1"],
    register_name: str,
    directive: Union[None, "Value_1", Any],
) -> Optional["Access_1.Response"]:
    from uavcan.register import Access_1, Name_1

    # TODO
    resp = await client(Access_1.Request(name=Name_1(register_name)))
    if resp is None:
        return None
    assert isinstance(resp, Access_1.Response)
    # TODO
    return resp


_logger = yakut.get_logger(__name__)
