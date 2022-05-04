# Copyright (c) 2022 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

from __future__ import annotations
import re
import asyncio
import logging
from typing import TYPE_CHECKING
import pycyphal
from yakut.register import fetch_registers

if TYPE_CHECKING:
    import pycyphal.application


class SubjectResolver:
    _DISCOVERY_TIMEOUT = 3.0
    _RESPONSE_TIMEOUT = 1.0

    def __init__(self, local_node: "pycyphal.application.Node") -> None:
        from uavcan.node import Heartbeat_1
        from pycyphal.application.register import ValueProxy

        self._local_node = local_node
        self._reg_cache: dict[int, dict[str, ValueProxy] | None] = {}
        self._seen_nodes: set[int] = set()
        self._sub_heart = self._local_node.make_subscriber(Heartbeat_1)
        self._sub_heart.transport_session.transfer_id_timeout = 1e-3
        self._sub_heart.receive_in_background(
            lambda _, meta: self._seen_nodes.add(meta.source_node_id) if meta.source_node_id is not None else None
        )
        self._node_discovery_deadline = asyncio.get_running_loop().time() + SubjectResolver._DISCOVERY_TIMEOUT

    async def dtypes_by_id(self, subject_id: int) -> set[str]:
        """
        Maps the given subject-ID to the data types that are used with this subject across the network.
        Empty set means resolution failure -- either no nodes use this subject or they don't support
        the register interface.
        """
        await self._update_reg_cache()
        return _register_dtypes_by_id(
            {k: v for k, v in self._reg_cache.items() if v is not None},
            subject_id,
        )

    async def _update_reg_cache(self) -> None:
        while True:
            remaining = self._seen_nodes - set(self._reg_cache.keys())
            try:
                nid = next(iter(remaining))
            except StopIteration:
                if asyncio.get_running_loop().time() > self._node_discovery_deadline:
                    break
                await asyncio.sleep(0.1)  # Wait for new nodes to come up online, if any.
            else:
                self._reg_cache[nid] = await fetch_registers(
                    self._local_node.presentation,
                    nid,
                    predicate=lambda name: any(
                        x.match(name)
                        for x in [
                            _REGEX_REG_PUBSUB_NAME_ID,
                            _REGEX_REG_PUBSUB_NAME_TYPE,
                        ]
                    ),
                    timeout=SubjectResolver._RESPONSE_TIMEOUT,
                    priority=pycyphal.transport.Priority.HIGH,
                )

    def close(self) -> None:
        """
        It is mandatory to close the instance after use.
        """
        self._sub_heart.close()


_REGEX_REG_PUBSUB_NAME_ID = re.compile(r"uavcan\.(pub|sub)\.(.+)\.id")
_REGEX_REG_PUBSUB_NAME_TYPE = re.compile(r"uavcan\.(pub|sub)\.(.+)\.type")


def _register_dtypes_by_id(
    registers_per_node: dict[int, dict[str, "pycyphal.application.register.ValueProxy"]],
    subject_id: int,
) -> set[str]:
    from pycyphal.application.register import ValueConversionError

    result: set[str] = set()
    names: dict[int, str] = {}
    for node_id, registers in registers_per_node.items():
        for reg_name, reg_val in registers.items():
            match = _REGEX_REG_PUBSUB_NAME_ID.match(reg_name)
            if match:
                _pubsub, port_name = match.groups()
                try:
                    if int(reg_val) == subject_id:
                        names[node_id] = port_name
                except ValueConversionError:
                    _logger.warning("Register %r@%r contains an invalid port-ID value %r", reg_name, node_id, reg_val)
    _logger.debug("Names of subject %r per node: %r", subject_id, names)
    for node_id, port_name in names.items():
        for reg_name, reg_val in registers_per_node[node_id].items():
            match = _REGEX_REG_PUBSUB_NAME_TYPE.match(reg_name)
            if match and match.group(2) == port_name:
                try:
                    result.add(str(reg_val))
                except ValueConversionError:
                    _logger.warning("Register %r@%r contains an invalid data type name %r", reg_name, node_id, reg_val)
    return result


_logger = logging.getLogger(__name__)


def _unittest_register_dtypes_by_id() -> None:
    from tests.dsdl import ensure_compiled_dsdl

    ensure_compiled_dsdl()
    from pycyphal.application.register import ValueProxy, Natural16, String

    assert _register_dtypes_by_id({}, 123) == set()
    regs: dict[int, dict[str, ValueProxy]] = {
        0: {
            "uavcan.pub.aa.id": ValueProxy(Natural16([1000])),
            "uavcan.pub.aa.type": ValueProxy(String("ns.A.1.1")),
            # aa
            "uavcan.sub.bb.id": ValueProxy(Natural16([2000])),
            "uavcan.sub.bb.type": ValueProxy(String("ns.B.1.1")),
            # bb
            "uavcan.sub.typeless.id": ValueProxy(Natural16([3000])),
            # bad ID
            "uavcan.pub.bad_id.id": ValueProxy(String("not a number")),
            # bad type
            "uavcan.pub.bad_type.id": ValueProxy(Natural16([2000])),
            "uavcan.pub.bad_type.type": ValueProxy(Natural16([2000])),
        },
        1: {
            "uavcan.sub.cc.id": ValueProxy(Natural16([2000])),
            "uavcan.sub.cc.type": ValueProxy(String("ns.B.1.1")),
            "uavcan.pub.aa.id": ValueProxy(Natural16([1000])),
            "uavcan.pub.aa.type": ValueProxy(String("ns.A.2.2")),
        },
        3: {},
    }
    assert _register_dtypes_by_id(regs, 1000) == {"ns.A.1.1", "ns.A.2.2"}
    assert _register_dtypes_by_id(regs, 2000) == {"ns.B.1.1"}  # Bad type ignored.
    assert _register_dtypes_by_id(regs, 3000) == set()  # Typeless ignored.
    assert _register_dtypes_by_id(regs, 9000) == set()  # Not found
