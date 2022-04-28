# Copyright (c) 2022 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

from __future__ import annotations
import dataclasses
from typing import TYPE_CHECKING, Optional
import pycyphal
import yakut
from yakut.progress import ProgressCallback
from ._directive import Directive, RegisterDirective

if TYPE_CHECKING:
    import pycyphal.application
    from uavcan.register import Access_1


@dataclasses.dataclass
class Result:
    responses_per_node: dict[int, dict[str, Optional["Access_1.Response"]]] = dataclasses.field(default_factory=dict)
    """
    Keys of the innermost dict are always the same as those in the directive regardless of success.
    On success, none of the values will be None.
    None means that a request has timed out and so the final value of the register is unknown,
    and further registers of this node (if any) are not processed (other nodes are still processed).
    """


async def do_calls(
    local_node: "pycyphal.application.Node",
    progress: ProgressCallback,
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
            responses: dict[str, Access_1.Response | None] = {k: None for k in node_dir}
            for idx, (reg_name, reg_dir) in enumerate(node_dir.items()):
                progress(f"{reg_name!r} @{node_id: 5}")
                resp = await _process_one(cln, reg_name, reg_dir)
                if resp is None:
                    _logger.info(
                        "Register %r @ %r has timed out (%r of %r); further processing of this node skipped",
                        reg_name,
                        node_id,
                        idx + 1,
                        len(node_dir),
                    )
                    break
                responses[reg_name] = resp  # None by default.
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
