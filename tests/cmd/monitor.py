#!/usr/bin/env python
# Copyright (c) 2021 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

from typing import Any, Callable, Awaitable
import asyncio
import itertools
import pytest
import pyuavcan
from pyuavcan.transport.serial import SerialTransport
from tests.subprocess import Subprocess
from tests.dsdl import OUTPUT_DIR


@pytest.mark.asyncio
async def _unittest_monitor(compiled_dsdl: Any, serial_broker: str) -> None:
    _ = compiled_dsdl
    asyncio.get_running_loop().slow_callback_duration = 10.0

    task_nodes = asyncio.create_task(_run_nodes(serial_broker))
    try:
        await asyncio.sleep(10.0)
    finally:
        task_nodes.cancel()
        await asyncio.sleep(3.0)


async def _run_nodes(serial_iface: str) -> None:
    from pyuavcan.application import make_registry, make_node, NodeInfo, Node
    from uavcan.node import Mode_1_0 as Mode, Health_1_0 as Health, Version_1_0 as Version
    from uavcan.primitive import String_1_0
    import uavcan.register

    async def subscription_sink(_msg: Any, _meta: pyuavcan.transport.TransferFrom) -> None:
        pass

    def instantiate(info: NodeInfo, node_id: int, mode: int, health: int, vssc: int) -> Node:
        reg = make_registry(
            environment_variables={
                "UAVCAN__SERIAL__IFACE": serial_iface,
                "UAVCAN__NODE__ID": str(node_id),
                "UAVCAN__PUB__SPAM__ID": "2222",
                "UAVCAN__SUB__SPAM__ID": "2222",
            }
        )
        node = make_node(info, reg)
        node.heartbeat_publisher.mode = mode
        node.heartbeat_publisher.health = health
        node.heartbeat_publisher.vendor_specific_status_code = vssc
        node.start()
        return node

    nodes = [
        instantiate(
            NodeInfo(
                hardware_version=Version(1, 2),
                software_version=Version(3, 4),
                software_vcs_revision_id=0x0DDC0FFEEBADF00D,
                unique_id=bytes(range(16)),
                name="org.uavcan.test.foo",
                software_image_crc=[0xDEADDEADDECEA5ED],
            ),
            1111,
            mode=Mode.MAINTENANCE,
            health=Health.ADVISORY,
            vssc=1,
        ),
        instantiate(
            NodeInfo(
                software_version=Version(163, 12),
                unique_id=bytes(range(16)[::-1]),
                name="org.uavcan.test.bar",
                software_image_crc=[0xACCE551B1E],
            ),
            3333,
            mode=Mode.SOFTWARE_UPDATE,
            health=Health.WARNING,
            vssc=2,
        ),
        instantiate(
            NodeInfo(
                software_vcs_revision_id=0x0BADBADBADBADBAD,
                unique_id=b"z" * 16,
                name="org.uavcan.test.baz",
            ),
            1234,
            mode=Mode.INITIALIZATION,
            health=Health.CAUTION,
            vssc=3,
        ),
        instantiate(
            NodeInfo(
                unique_id=b" " * 16,
                name="org.uavcan.test.zoo",
            ),
            3210,
            mode=Mode.OPERATIONAL,
            health=Health.NOMINAL,
            vssc=4,
        ),
    ]
    pub = nodes[0].make_publisher(String_1_0, "spam")
    nodes[1].make_subscriber(String_1_0, "spam").receive_in_background(subscription_sink)
    nodes[2].make_subscriber(String_1_0, "spam").receive_in_background(subscription_sink)
    reg_client_a = nodes[1].make_client(uavcan.register.List_1_0, 1111)
    reg_client_b = nodes[1].make_client(uavcan.register.List_1_0, 3210)
    print("NODES STARTED")
    try:
        for i in itertools.count():
            assert await pub.publish(String_1_0(f"Hello world! This is message number #{i+1}."))
            if (i % 2000) > 1000:
                if i % 2 == 0:
                    await reg_client_a.call(uavcan.register.List_1_0.Request(i % 11))
                if i % 5 == 0:
                    await reg_client_b.call(uavcan.register.List_1_0.Request(i % 11))
            await asyncio.sleep(0.001)
    finally:
        print("STOPPING THE NODES...")
        for n in nodes:
            n.close()
        print("NODES STOPPED")


async def _run_collision(serial_iface: str) -> None:
    from pyuavcan.application import make_registry, make_node, NodeInfo

    reg = make_registry(
        environment_variables={
            "UAVCAN__SERIAL__IFACE": serial_iface,
            "UAVCAN__NODE__ID": "1234",
        }
    )
    node = make_node(NodeInfo(), reg)
    try:
        node.start()
        await asyncio.sleep(2 ** 32)
    finally:
        node.close()


async def _run_zombie(serial_iface: str) -> None:
    from uavcan.primitive import Empty_1_0

    tr = SerialTransport(serial_iface, 2571)
    pres = pyuavcan.presentation.Presentation(tr)
    try:
        pub = pres.make_publisher(Empty_1_0, 99)
        while True:
            await pub.publish(Empty_1_0())
            await asyncio.sleep(0.5)
    finally:
        pres.close()


async def _run_anonymous(serial_iface: str) -> None:
    from pyuavcan.application import make_registry, make_node, NodeInfo
    from uavcan.primitive import String_1_0

    reg = make_registry(
        environment_variables={
            "UAVCAN__SERIAL__IFACE": serial_iface,
            "UAVCAN__PUB__SPAM__ID": "2222",
        }
    )
    node = make_node(NodeInfo(), reg)
    try:
        node.start()
        pub = node.make_publisher(String_1_0, "spam")
        while True:
            await asyncio.sleep(1.0)
            await pub.publish(String_1_0("I am here incognito."))
    finally:
        node.close()


async def _delay(target: Awaitable[None], delay: float, duration: float) -> None:
    await asyncio.sleep(delay)
    print("LAUNCHING", target)
    try:
        await asyncio.wait_for(target, duration)
    except asyncio.TimeoutError:
        pass
    print("FINISHED", target)


async def _main() -> None:
    """
    This is intended to aid in manual testing of the UI.
    Run this file having launched the serial broker beforehand and visually validate the behavior of the tool.

    This is how you can record the screen if you want a gif or something:

        ffmpeg -video_size 1900x800 -framerate 10 -f x11grab -i :0.0+0,117 -tune stillimage output.mp4
        ffmpeg -i output.mp4 output.gif

    Docs on ffmpeg: https://trac.ffmpeg.org/wiki/Capture/Desktop
    """
    serial_iface = "socket://127.0.0.1:50905"
    await asyncio.gather(
        _delay(_run_nodes(serial_iface), 0.0, 30.0),
        _delay(_run_collision(serial_iface), 9.0, 5.0),
        _delay(_run_zombie(serial_iface), 6.0, 10.0),
        _delay(_run_anonymous(serial_iface), 3.0, 10.0),
    )


if __name__ == "__main__":
    asyncio.run(_main())
