# Copyright (c) 2021 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

from __future__ import annotations
import asyncio
from typing import TYPE_CHECKING, Callable, Any, Type
import threading
import pyuavcan
from pyuavcan.transport import Timestamp, AlienTransfer
import yakut

if TYPE_CHECKING:
    import pyuavcan.application  # pylint: disable=ungrouped-imports


class Iface:
    def __init__(self, node: pyuavcan.application.Node) -> None:
        self._loop = asyncio.get_event_loop()
        self._node = node
        self._clients: dict[
            tuple[Type[pyuavcan.dsdl.CompositeObject], int],
            pyuavcan.presentation.Client[pyuavcan.dsdl.CompositeObject],
        ] = {}
        self._subscriptions: list[Type[pyuavcan.dsdl.FixedPortCompositeObject]] = []
        self._lock = threading.RLock()
        self._trace_handlers: list[Callable[[Timestamp, AlienTransfer], None]] = []
        self._transport_error_handlers: list[Callable[[pyuavcan.transport.ErrorTrace], None]] = []
        self._tracer = node.presentation.transport.make_tracer()

        _logger.info("Starting packet capture on %r", self._node)
        node.presentation.transport.begin_capture(self._process_capture)

    def add_trace_handler(self, cb: Callable[[Timestamp, AlienTransfer], None]) -> None:
        self._trace_handlers.append(cb)

    def add_transport_error_handler(self, cb: Callable[[pyuavcan.transport.ErrorTrace], None]) -> None:
        self._transport_error_handlers.append(cb)

    def add_standard_subscription(self, dtype: Type[pyuavcan.dsdl.FixedPortCompositeObject]) -> None:
        """
        It is necessary to create subscriptions even if we're not going to use them directly to ensure that
        the network is informed about our interest in this data.
        For UAVCAN/CAN and UAVCAN/serial this may not matter but for UAVCAN/UDP this is important
        because we need to let the underlying layers publish the relevant IGMP states.
        """
        if dtype not in self._subscriptions:  # This is just to avoid excessive subscriptions.
            _logger.info("Subscribing to the fixed subject-ID of %r", dtype.__name__)
            self._node.make_subscriber(dtype).receive_in_background(self._dummy_subscription_handler)
            self._subscriptions.append(dtype)

    def try_request(
        self,
        dtype: Type[pyuavcan.dsdl.FixedPortServiceObject],
        server_node_id: int,
        request: pyuavcan.dsdl.CompositeObject,
    ) -> None:
        """
        The expectation is that the response will be read via the packet capture interface.
        If the local node is anonymous, nothing would happen.
        The request is always executed at the lowest priority level.
        """
        if self._node.id is None or self._node.id == server_node_id:
            return
        _logger.info("Requesting fixed service-ID of %r at %r", dtype.__name__, server_node_id)
        try:
            client = self._clients[dtype, server_node_id]
        except LookupError:
            self._clients[dtype, server_node_id] = self._node.make_client(dtype, server_node_id)
            client = self._clients[dtype, server_node_id]
            client.priority = pyuavcan.transport.Priority.OPTIONAL
            client.response_timeout = 5.0

        async def run() -> None:
            _ = await client.call(request)

        self._loop.create_task(run())

    def _process_capture(self, cap: pyuavcan.transport.Capture) -> None:
        # Locking is super critical! Captures may run in separate threads.
        with self._lock:
            trace = self._tracer.update(cap)
            if isinstance(trace, pyuavcan.transport.TransferTrace):
                self._loop.call_soon_threadsafe(
                    pyuavcan.util.broadcast(self._trace_handlers), trace.timestamp, trace.transfer
                )
            elif isinstance(trace, pyuavcan.transport.ErrorTrace):
                self._loop.call_soon_threadsafe(pyuavcan.util.broadcast(self._transport_error_handlers), trace)
            else:
                pass

    @staticmethod
    async def _dummy_subscription_handler(*_: Any) -> None:
        pass


_logger = yakut.get_logger(__name__)
