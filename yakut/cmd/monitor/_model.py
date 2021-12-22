# Copyright (c) 2021 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

from __future__ import annotations
from typing import TYPE_CHECKING, Optional, Callable, Type, AbstractSet
import dataclasses
import math
import numpy as np
from numpy.typing import NDArray
import pyuavcan
from pyuavcan.transport import MessageDataSpecifier, ServiceDataSpecifier, Timestamp, AlienTransfer
import yakut
from ._iface import Iface

if TYPE_CHECKING:
    import uavcan.node
    import uavcan.node.port


@dataclasses.dataclass()
class PortSet:
    pub: AbstractSet[int] = dataclasses.field(default_factory=frozenset)
    sub: AbstractSet[int] = dataclasses.field(default_factory=frozenset)
    cln: AbstractSet[int] = dataclasses.field(default_factory=frozenset)
    srv: AbstractSet[int] = dataclasses.field(default_factory=frozenset)


@dataclasses.dataclass(frozen=True)
class NodeState:
    online: bool
    """
    Online means that the node is emitting any transfers whatsoever.
    """

    heartbeat: Optional[uavcan.node.Heartbeat_1_0]
    """
    An online node without a heartbeat is a zombie, which is an error condition because heartbeats are required
    for all nodes unconditionally.
    """
    info: Optional[uavcan.node.GetInfo_1_0.Response]

    ports: Optional[PortSet]
    """
    Defined only if the node keeps its uavcan.node.List publications up-to-date.
    """


class Avatar:  # pylint: disable=too-many-instance-attributes
    def __init__(
        self,
        iface: Iface,
        node_id: Optional[int],
        info: Optional[uavcan.node.GetInfo_1_0.Response] = None,
    ) -> None:
        import uavcan.node
        import uavcan.node.port

        self._node_id = node_id

        self._heartbeat: Optional[uavcan.node.Heartbeat_1_0] = None
        self._iface = iface
        self._info = info
        self._num_info_requests = 0

        self._ts_activity = -math.inf
        self._ts_heartbeat = -math.inf
        self._ts_port_list = -math.inf
        self._ts_info_request = -math.inf

        self._ports = PortSet()

        self._dispatch: dict[
            Type[pyuavcan.dsdl.FixedPortCompositeObject]
            | tuple[Type[pyuavcan.dsdl.FixedPortServiceObject], ServiceDataSpecifier.Role],
            Callable[[float, pyuavcan.dsdl.CompositeObject], None],
        ] = {
            (uavcan.node.GetInfo_1_0, ServiceDataSpecifier.Role.RESPONSE): self._on_info_response,
            uavcan.node.port.List_0_1: self._on_port_list,
            uavcan.node.Heartbeat_1_0: self._on_heartbeat,
        }

        self._iface.add_standard_subscription(uavcan.node.Heartbeat_1_0)
        self._iface.add_standard_subscription(uavcan.node.port.List_0_1)
        self._iface.add_trace_handler(self._on_trace)

    def _restart(self) -> None:
        self._info = None
        self._num_info_requests = 0
        self._ts_port_list = -math.inf

    def _on_info_response(self, ts: float, obj: pyuavcan.dsdl.CompositeObject) -> None:
        import uavcan.node

        _logger.info("%r: Received node info", self)
        assert isinstance(obj, uavcan.node.GetInfo_1_0.Response)
        _ = ts
        self._info = obj

    def _on_port_list(self, ts: float, obj: pyuavcan.dsdl.CompositeObject) -> None:
        import uavcan.node.port

        assert isinstance(obj, uavcan.node.port.List_0_1)
        self._ports.pub = expand_subjects(obj.publishers)
        self._ports.sub = expand_subjects(obj.subscribers)
        self._ports.cln = expand_mask(obj.clients.mask)
        self._ports.srv = expand_mask(obj.servers.mask)
        self._ts_port_list = ts

    def _on_heartbeat(self, ts: float, obj: pyuavcan.dsdl.CompositeObject) -> None:
        from uavcan.node import Heartbeat_1_0 as Heartbeat, GetInfo_1_0 as GetInfo

        assert isinstance(obj, Heartbeat)

        # We used to have a node-ID collision heuristic here that checked if the timestamp is oscillating back and
        # forth, as it would indicate that there are multiple nodes running on the same node-ID. While this
        # heuristic is correct, it is ineffective in practice because heartbeats of nodes with a lower uptime
        # would have lower transfer-ID values, which (unless the transport is cyclic-TID) would make the transfer
        # reassembler discard such new heartbeats from conflicting nodes as duplicates (already seen transfers).
        # It is therefore impossible to detect collisions at this layer (it is possible only below the transport
        # layer). Although it might *occasionally* work if the heartbeats are delayed or published irregularly.

        # Invalidate the node info if the uptime goes backwards or if we received a heartbeat after a long pause.
        restart = self._heartbeat and (
            (self._heartbeat.uptime > obj.uptime) or (ts - self._ts_heartbeat > Heartbeat.OFFLINE_TIMEOUT)
        )
        if restart:
            _logger.info("%r: Restart detected: %r", self, obj)
            self._restart()

        if not self._info and self._node_id is not None:
            timeout = 2 ** (self._num_info_requests + 2)
            if ts - self._ts_info_request >= timeout:
                _logger.debug("%r: Would request info; timeout=%.1f", self, timeout)
                self._num_info_requests += 1
                self._ts_info_request = ts
                self._iface.try_request(GetInfo, self._node_id, GetInfo.Request())

        self._heartbeat = obj
        self._ts_heartbeat = ts

    def _on_trace(self, ts: Timestamp, tr: AlienTransfer) -> None:
        from pyuavcan.dsdl import get_fixed_port_id

        own = tr.metadata.session_specifier.source_node_id == self._node_id
        if not own:
            return
        ds = tr.metadata.session_specifier.data_specifier
        self._ts_activity = float(ts.monotonic)

        # Snoop on transfers sent by our node. Even if we can't ask we can still learn things by listening.
        for ty, handler in self._dispatch.items():
            if isinstance(ty, tuple):
                ty, role = ty
                assert isinstance(ty, type) and isinstance(role, ServiceDataSpecifier.Role)
                if isinstance(ds, ServiceDataSpecifier) and ds.role == role and ds.service_id == get_fixed_port_id(ty):
                    rr = getattr(ty, role.name.capitalize())
                    assert issubclass(rr, pyuavcan.dsdl.CompositeObject)
                    obj = pyuavcan.dsdl.deserialize(rr, tr.fragmented_payload)
                    _logger.debug("%r: Service snoop: %r from %r", self, obj, tr)
                    if obj is not None:
                        handler(float(ts.monotonic), obj)
            elif isinstance(ty, type) and issubclass(ty, pyuavcan.dsdl.FixedPortCompositeObject):
                if isinstance(ds, MessageDataSpecifier) and ds.subject_id == get_fixed_port_id(ty):
                    obj = pyuavcan.dsdl.deserialize(ty, tr.fragmented_payload)
                    _logger.debug("%r: Message snoop: %r from %r", self, obj, tr)
                    if obj is not None:
                        handler(float(ts.monotonic), obj)
            else:
                assert False

    def update(self, ts: float) -> NodeState:
        from uavcan.node import Heartbeat_1_0 as Heartbeat
        from uavcan.node.port import List_0_1 as PortList

        if self._heartbeat and self._ts_activity - self._ts_heartbeat > Heartbeat.OFFLINE_TIMEOUT:
            _logger.info("%r: Much more recent activity than the last heartbeat, we've gone zombie", self)
            self._heartbeat = None

        online = (ts - max(self._ts_heartbeat, self._ts_activity)) <= Heartbeat.OFFLINE_TIMEOUT
        port_introspection_valid = (ts - self._ts_port_list) <= PortList.MAX_PUBLICATION_PERIOD * 2

        return NodeState(
            online=online,
            heartbeat=self._heartbeat,
            info=self._info,
            ports=self._ports if port_introspection_valid else None,
        )

    def __repr__(self) -> str:
        return str(pyuavcan.util.repr_attributes(self, node_id=self._node_id))


def expand_subjects(m: uavcan.node.port.SubjectIDList_0_1) -> AbstractSet[int]:
    if m.sparse_list is not None:
        return frozenset(int(x.value) for x in m.sparse_list)
    if m.mask:
        return expand_mask(m.mask)
    if m.total:
        return _COMPLETE_SUBJECT_SET
    assert False


def expand_mask(mask: NDArray[np.bool_]) -> AbstractSet[int]:
    return frozenset(x for x in range(len(mask)) if mask[x])


N_NODES = 65535  # The theoretical limit for all kinds of transports.
N_SUBJECTS = MessageDataSpecifier.SUBJECT_ID_MASK + 1
N_SERVICES = ServiceDataSpecifier.SERVICE_ID_MASK + 1

_COMPLETE_SUBJECT_SET = frozenset(range(N_SUBJECTS))
"""Made static for performance reasons."""

_logger = yakut.get_logger(__name__)
