#!/usr/bin/env python
# Copyright (c) 2021 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

from typing import Any, Optional, Awaitable
import os
import asyncio
import itertools
import pytest
import pyuavcan
from pyuavcan.transport.serial import SerialTransport
from tests.subprocess import Subprocess
from tests.dsdl import OUTPUT_DIR
import yakut


# noinspection SpellCheckingInspection
@pytest.mark.asyncio
async def _unittest_monitor_nodes(compiled_dsdl: Any, serial_broker: str) -> None:
    _ = compiled_dsdl
    asyncio.get_running_loop().slow_callback_duration = 10.0

    task = asyncio.create_task(_run_nodes(serial_broker))
    cells = [x.split() for x in (await _monitor_and_get_last_screen(serial_broker, 10.0, 42)).splitlines()]
    task.cancel()
    await asyncio.sleep(3.0)

    # Own node
    assert cells[1][0] == "42"
    assert cells[1][1] == "oper"
    assert cells[1][2] == "nomina"
    assert 1 <= len(cells[1][3]) <= 3
    assert 6 <= len(cells[1][4]) <= 15
    assert cells[1][5] == "1.0"
    assert cells[1][6] == "0.0"
    assert cells[1][7] == ".".join(map(str, yakut.__version_info__[:2]))
    assert len(cells[1][8]) == 32
    assert cells[1][9] == "org.uavcan.yakut.monitor"

    assert cells[2][0] == "1111"
    assert cells[2][1] == "mntn"
    assert cells[2][2] == "adviso"
    assert cells[2][6] == "1.2"
    assert cells[2][7] == "3.4.0ddc0ffeebadf00d.deaddeaddecea5ed"
    assert cells[2][8] == "000102030405060708090a0b0c0d0e0f"
    assert cells[2][9] == "org.uavcan.test.foo"

    assert cells[3][0] == "1234"
    assert cells[3][1] == "init"
    assert cells[3][2] == "cautio"
    assert cells[3][9] == "org.uavcan.test.baz"

    assert cells[4][0] == "3210"
    assert cells[4][1] == "oper"
    assert cells[4][2] == "nomina"
    assert cells[4][9] == "org.uavcan.test.zoo"

    assert cells[5][0] == "3333"
    assert cells[5][1] == "swup"
    assert cells[5][2] == "warnin"
    assert cells[5][9] == "org.uavcan.test.bar"

    # Same but the nodes go offline plus there is an anonymous node.
    tasks = [
        asyncio.create_task(_delay(_run_nodes(serial_broker), 1.0, duration=5.0)),
        asyncio.create_task(_delay(_run_anonymous(serial_broker), 1.0, duration=5.0)),
    ]
    cells = [x.split() for x in (await _monitor_and_get_last_screen(serial_broker, 15.0, 42)).splitlines()]
    await asyncio.gather(*tasks)
    await asyncio.sleep(3.0)

    # Own node
    assert cells[1][0] == "42"
    assert cells[1][1] == "oper"
    assert cells[1][2] == "nomina"
    assert cells[1][4] != "offline"
    assert len(cells[1][8]) == 32
    assert cells[1][9] == "org.uavcan.yakut.monitor"

    assert cells[2][0] == "1111"
    assert cells[2][4] == "offline"
    assert cells[2][9] == "org.uavcan.test.foo"

    assert cells[3][0] == "1234"
    assert cells[3][4] == "offline"
    assert cells[3][9] == "org.uavcan.test.baz"

    assert cells[4][0] == "3210"
    assert cells[4][4] == "offline"
    assert cells[4][9] == "org.uavcan.test.zoo"

    assert cells[5][0] == "3333"
    assert cells[5][4] == "offline"
    assert cells[5][9] == "org.uavcan.test.bar"

    assert cells[6][0] == "anon"
    assert cells[6][4] == "offline"

    await asyncio.sleep(3.0)


# noinspection SpellCheckingInspection
@pytest.mark.asyncio
async def _unittest_monitor_errors(compiled_dsdl: Any, serial_broker: str) -> None:
    _ = compiled_dsdl
    asyncio.get_running_loop().slow_callback_duration = 10.0
    asyncio.get_running_loop().set_exception_handler(lambda *_: None)

    # This time the monitor node is anonymous.
    task = asyncio.gather(
        _run_nodes(serial_broker),
        _run_zombie(serial_broker),
        _delay(_inject_error(serial_broker), 7.0),
    )
    cells = [x.split() for x in (await _monitor_and_get_last_screen(serial_broker, 12.0, None)).splitlines()]
    task.cancel()
    await asyncio.sleep(3.0)

    assert cells[1][0] == "1111"
    assert cells[1][9] == "?"  # Unable to query

    assert cells[2][0] == "1234"

    assert cells[3][0] == "2571"
    assert cells[3][4] == "zombie"

    assert cells[4][0] == "3210"

    assert cells[5][0] == "3333"

    # Error counter
    assert cells[-1][4] == "1"

    await asyncio.sleep(3.0)


async def _monitor_and_get_last_screen(serial_iface: str, duration: float, node_id: Optional[int]) -> str:
    stdout_file = "monitor_stdout"
    stdout = open(stdout_file, "wb")
    args = ["--verbose", "monitor"]
    if node_id is not None:
        args.append("--plug-and-play=allocation_table.db")
    proc = Subprocess.cli(
        *args,
        environment_variables={
            "YAKUT_PATH": str(OUTPUT_DIR),
            "UAVCAN__SERIAL__IFACE": serial_iface,
            "UAVCAN__NODE__ID": str(node_id if node_id is not None else 0xFFFF),
        },
        stdout=stdout,
    )
    try:
        await asyncio.sleep(1.0)
        assert proc.alive
        await asyncio.sleep(duration)
        assert proc.alive

        _, _, stderr = proc.wait(10.0, interrupt=True)
        assert " ERR" not in stderr
        assert " CRI" not in stderr
        assert "Traceback" not in stderr

        stdout.flush()
        os.fsync(stdout.fileno())
        stdout.close()
        with open(stdout_file, "r") as f:
            screens = f.read().split("\n" * 3)
            assert len(screens) > 1
            assert len(screens) < (duration * 0.5 + 10)
        last_screen = screens[-1]
        print("=== LAST SCREEN ===")
        print(last_screen)
        return last_screen
    except Exception:  # pragma: no cover
        proc.kill()
        raise


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
                "UAVCAN__SUB__NULL__ID": "3333",
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
    nodes[3].make_subscriber(String_1_0, "null").receive_in_background(subscription_sink)  # No publishers.
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
            await asyncio.sleep(0.01)
    except (asyncio.TimeoutError, asyncio.CancelledError):  # pragma: no cover
        pass
    finally:
        print("STOPPING THE NODES...")
        for n in nodes:
            n.close()
        print("NODES STOPPED")


async def _run_zombie(serial_iface: str) -> None:
    from uavcan.primitive import Empty_1_0

    tr = SerialTransport(serial_iface, 2571)
    pres = pyuavcan.presentation.Presentation(tr)
    try:
        pub = pres.make_publisher(Empty_1_0, 99)
        while True:
            await pub.publish(Empty_1_0())
            await asyncio.sleep(0.5)
    except (asyncio.TimeoutError, asyncio.CancelledError):  # pragma: no cover
        pass
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
    except (asyncio.TimeoutError, asyncio.CancelledError):  # pragma: no cover
        pass
    finally:
        node.close()


async def _inject_error(serial_iface: str) -> None:
    from serial import serial_for_url  # type: ignore

    p = serial_for_url(serial_iface)
    p.write(b"\x00 this is not a valid frame \x00")
    p.close()


async def _delay(target: Awaitable[None], delay: float, duration: Optional[float] = None) -> None:
    await asyncio.sleep(delay)
    print("LAUNCHING", target)
    try:
        if duration is None:
            await target
        else:
            await asyncio.wait_for(target, duration)
    except (asyncio.TimeoutError, asyncio.CancelledError):  # pragma: no cover
        pass
    print("FINISHED", target)


async def _main() -> None:  # pragma: no cover
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
        _delay(_run_zombie(serial_iface), 6.0, 10.0),
        _delay(_run_anonymous(serial_iface), 3.0, 10.0),
        _delay(_inject_error(serial_iface), 3.0),
    )


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(_main())
