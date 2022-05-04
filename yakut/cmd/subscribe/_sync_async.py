# Copyright (c) 2022 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

from __future__ import annotations
import asyncio
from typing import Any, Iterable, Callable
import pycyphal
from pycyphal.transport import TransferFrom
from pycyphal.presentation import Subscriber
from ._sync import SynchronizerOutput, Synchronizer


def make_sync_async(subscribers: Iterable[Subscriber[Any]]) -> Synchronizer:
    """
    This synchronizer delivers one message at a time immediately without any synchronization,
    where all other messages and their metadata are set to None.
    """
    subscribers = list(subscribers)
    queue: asyncio.Queue[tuple[tuple[tuple[Any, TransferFrom] | None, Subscriber[Any]], ...]] = asyncio.Queue()

    def mk_handler(index: int) -> Callable[[Any, TransferFrom], None]:
        def hdl(msg: Any, meta: TransferFrom) -> None:
            assert isinstance(meta, TransferFrom)
            queue.put_nowait(
                tuple(
                    (
                        ((msg, meta) if idx == index else None),
                        sub,
                    )
                    for idx, sub in enumerate(subscribers)
                )
            )

        return hdl

    async def fun(output: SynchronizerOutput) -> None:
        try:
            for idx, sub in enumerate(subscribers):
                sub.receive_in_background(mk_handler(idx))
            while True:
                item = await queue.get()
                output(item)
        finally:
            pycyphal.util.broadcast((x.close for x in subscribers))()

    return fun


def _unittest_sync_async() -> None:
    from tests.dsdl import ensure_compiled_dsdl

    ensure_compiled_dsdl()

    from pycyphal.transport.loopback import LoopbackTransport
    from pycyphal.presentation import Presentation
    from uavcan.primitive.scalar import Integer8_1

    async def run() -> None:
        pre = Presentation(LoopbackTransport(10))
        sub_a = pre.make_subscriber(Integer8_1, 1000)
        sub_b = pre.make_subscriber(Integer8_1, 1001)
        pub_a = pre.make_publisher(sub_a.dtype, sub_a.port_id)
        pub_b = pre.make_publisher(sub_b.dtype, sub_b.port_id)
        try:
            syn = make_sync_async([sub_a, sub_b])
            results: list[tuple[tuple[tuple[Any, TransferFrom] | None, Subscriber[Any]], ...]] = []
            # noinspection PyTypeChecker
            tsk = asyncio.create_task(syn(results.append))
            try:
                await asyncio.sleep(0.1)
                assert not results

                await pub_a.publish(Integer8_1(50))
                await asyncio.sleep(0.1)
                ((((msg, meta), rx_sub_a), (none, rx_sub_b)),) = results  # type: ignore
                results.clear()
                assert rx_sub_a is sub_a and rx_sub_b is sub_b and none is None
                assert isinstance(msg, Integer8_1)
                assert msg.value == 50
                assert meta.source_node_id == 10

                await pub_a.publish(Integer8_1(51))
                await asyncio.sleep(0.1)
                ((((msg, meta), rx_sub_a), (none, rx_sub_b)),) = results  # type: ignore
                results.clear()
                assert rx_sub_a is sub_a and rx_sub_b is sub_b and none is None
                assert isinstance(msg, Integer8_1)
                assert msg.value == 51
                assert meta.source_node_id == 10

                await pub_b.publish(Integer8_1(52))
                await asyncio.sleep(0.1)
                (((none, rx_sub_a), ((msg, meta), rx_sub_b)),) = results  # type: ignore
                results.clear()
                assert rx_sub_a is sub_a and rx_sub_b is sub_b and none is None
                assert isinstance(msg, Integer8_1)
                assert msg.value == 52
                assert meta.source_node_id == 10

            finally:
                tsk.cancel()
        finally:
            sub_a.close()
            sub_b.close()
            pub_a.close()
            pub_b.close()
            pre.close()

    asyncio.run(run())
