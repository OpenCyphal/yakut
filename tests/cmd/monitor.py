#!/usr/bin/env python
# Copyright (c) 2021 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

from typing import Any, Optional, Awaitable
import sys
import socket
import asyncio
import itertools
import logging
import pytest
import pycyphal
from pycyphal.transport.udp import UDPTransport
from tests.subprocess import Subprocess
import yakut

if sys.platform.startswith("win"):  # pragma: no cover
    pytest.skip("These are GNU/Linux-only tests", allow_module_level=True)


# noinspection SpellCheckingInspection
@pytest.mark.asyncio
async def _unittest_monitor_nodes() -> None:
    asyncio.get_running_loop().slow_callback_duration = 10.0
    asyncio.get_running_loop().set_exception_handler(lambda *_: None)

    task = asyncio.create_task(_run_nodes())
    try:
        cells = [x.split() for x in (await _monitor_and_get_last_screen(30.0, 42)).splitlines()]
    finally:
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
    assert cells[1][9] == "org.opencyphal.yakut.monitor"

    assert cells[2][0] == "1111"
    assert cells[2][1] == "mntn"
    assert cells[2][2] == "adviso"
    assert cells[2][6] == "1.2"
    assert cells[2][7] == "3.4.0ddc0ffeebadf00d.deaddeaddecea5ed"
    assert cells[2][8] == "000102030405060708090a0b0c0d0e0f"
    assert cells[2][9] == "org.opencyphal.test.foo"

    assert cells[3][0] == "1234"
    assert cells[3][1] == "init"
    assert cells[3][2] == "cautio"
    assert cells[3][9] == "org.opencyphal.test.baz"

    assert cells[4][0] == "3210"
    assert cells[4][1] == "oper"
    assert cells[4][2] == "nomina"
    assert cells[4][9] == "org.opencyphal.test.zoo"

    assert cells[5][0] == "3333"
    assert cells[5][1] == "swup"
    assert cells[5][2] == "warnin"
    assert cells[5][9] == "org.opencyphal.test.bar"

    # Same but the nodes go offline plus there is an anonymous node.
    tasks = [
        asyncio.create_task(_delay(_run_nodes(), 1.0, duration=5.0)),
        asyncio.create_task(_delay(_run_anonymous(), 1.0, duration=5.0)),
    ]
    cells = [x.split() for x in (await _monitor_and_get_last_screen(30.0, 42)).splitlines()]
    await asyncio.gather(*tasks)
    await asyncio.sleep(3.0)

    # Own node
    assert cells[1][0] == "42"
    assert cells[1][1] == "oper"
    assert cells[1][2] == "nomina"
    assert cells[1][4] != "offline"
    assert len(cells[1][8]) == 32
    assert cells[1][9] == "org.opencyphal.yakut.monitor"

    assert cells[2][0] == "1111"
    assert cells[2][4] == "offline"
    assert cells[2][9] == "org.opencyphal.test.foo"

    assert cells[3][0] == "1234"
    assert cells[3][4] == "offline"
    assert cells[3][9] == "org.opencyphal.test.baz"

    assert cells[4][0] == "3210"
    assert cells[4][4] == "offline"
    assert cells[4][9] == "org.opencyphal.test.zoo"

    assert cells[5][0] == "3333"
    assert cells[5][4] == "offline"
    assert cells[5][9] == "org.opencyphal.test.bar"

    assert cells[6][0] == "anon"
    assert cells[6][4] == "offline"

    await asyncio.sleep(3.0)


async def _monitor_and_get_last_screen(duration: float, node_id: Optional[int]) -> str:
    args = ["monitor"]
    if node_id is not None:
        args.append("--plug-and-play=allocation_table.db")
    proc = Subprocess.cli(
        *args,
        environment_variables={
            "UAVCAN__UDP__IFACE": "127.0.0.1",
            "UAVCAN__NODE__ID": str(node_id if node_id is not None else 0xFFFF),
        },
    )
    try:
        await asyncio.sleep(1.0)
        if not proc.alive:
            exit_code, _, _ = proc.wait(1.0)
            assert False, exit_code
        await asyncio.sleep(duration)
        if not proc.alive:
            exit_code, _, _ = proc.wait(1.0)
            assert False, exit_code

        _, stdout, stderr = proc.wait(10.0, interrupt=True)
        assert " ERR" not in stderr
        assert " CRI" not in stderr
        assert "Traceback" not in stderr

        screens = stdout.replace("\r", "").split("\n" * 3)
        assert len(screens) >= 1
        assert len(screens) < (duration * 0.5 + 10)
        last_screen = screens[-1]
        _logger.info("=== LAST SCREEN ===\n%s", last_screen)
        return last_screen
    except Exception:  # pragma: no cover
        proc.kill()
        raise


async def _run_nodes() -> None:
    from pycyphal.application import make_registry, make_node, NodeInfo, Node
    from uavcan.node import Mode_1 as Mode, Health_1 as Health, Version_1 as Version
    from uavcan.primitive import String_1
    import uavcan.register

    async def subscription_sink(_msg: Any, _meta: pycyphal.transport.TransferFrom) -> None:
        pass

    def instantiate(info: NodeInfo, node_id: int, mode: int, health: int, vssc: int) -> Node:
        reg = make_registry(
            environment_variables={
                "UAVCAN__UDP__IFACE": "127.0.0.1",
                "UAVCAN__NODE__ID": str(node_id),
                "UAVCAN__PUB__SPAM__ID": "2222",
                "UAVCAN__SUB__SPAM__ID": "2222",
                "UAVCAN__SUB__NULL__ID": "3333",
            }
        )
        node = make_node(info, reg)
        node.heartbeat_publisher.mode = mode  # type: ignore
        node.heartbeat_publisher.health = health  # type: ignore
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
                name="org.opencyphal.test.foo",
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
                name="org.opencyphal.test.bar",
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
                name="org.opencyphal.test.baz",
            ),
            1234,
            mode=Mode.INITIALIZATION,
            health=Health.CAUTION,
            vssc=3,
        ),
        instantiate(
            NodeInfo(
                unique_id=b" " * 16,
                name="org.opencyphal.test.zoo",
            ),
            3210,
            mode=Mode.OPERATIONAL,
            health=Health.NOMINAL,
            vssc=4,
        ),
    ]
    pub = nodes[0].make_publisher(String_1, "spam")
    pub.send_timeout = 5.0
    nodes[1].make_subscriber(String_1, "spam").receive_in_background(subscription_sink)
    nodes[2].make_subscriber(String_1, "spam").receive_in_background(subscription_sink)
    nodes[3].make_subscriber(String_1, "null").receive_in_background(subscription_sink)  # No publishers.
    reg_client_a = nodes[1].make_client(uavcan.register.List_1, 1111)
    reg_client_b = nodes[1].make_client(uavcan.register.List_1, 3210)
    _logger.info("NODES STARTED")
    try:
        for i in itertools.count():
            assert await pub.publish(String_1(f"Hello world! This is message number #{i+1}."))
            if (i % 2000) > 1000:
                if i % 2 == 0:
                    await reg_client_a.call(uavcan.register.List_1.Request(i % 11))
                if i % 5 == 0:
                    await reg_client_b.call(uavcan.register.List_1.Request(i % 11))
            await asyncio.sleep(0.2)
    except (asyncio.TimeoutError, asyncio.CancelledError, GeneratorExit):  # pragma: no cover
        pass
    finally:
        _logger.info("STOPPING THE NODES...")
        for n in nodes:
            n.close()
        _logger.info("NODES STOPPED")


async def _run_zombie() -> None:
    from uavcan.primitive import Empty_1

    tr = UDPTransport("127.0.0.1", 2571)
    pres = pycyphal.presentation.Presentation(tr)
    try:
        pub = pres.make_publisher(Empty_1, 99)
        pub.send_timeout = 5.0
        sub = pres.make_subscriber(Empty_1, 99)  # Ensure there's an RX socket on Windows.
        while True:
            assert await pub.publish(Empty_1())
            await asyncio.sleep(0.5)
            _ = await sub.receive_for(0.0)  # Avoid queue overrun.
    except (asyncio.TimeoutError, asyncio.CancelledError, GeneratorExit):  # pragma: no cover
        pass
    finally:
        pres.close()


async def _run_anonymous() -> None:
    from pycyphal.application import make_registry, make_node, NodeInfo
    from uavcan.primitive import String_1

    reg = make_registry(
        environment_variables={
            "UAVCAN__UDP__IFACE": "127.0.0.1",
            "UAVCAN__PUB__SPAM__ID": "2222",
        }
    )
    node = make_node(NodeInfo(), reg)
    try:
        node.start()
        pub = node.make_publisher(String_1, "spam")
        while True:
            await asyncio.sleep(1.0)
            await pub.publish(String_1("I am here incognito."))
    except (asyncio.TimeoutError, asyncio.CancelledError):  # pragma: no cover
        pass
    finally:
        node.close()


async def _inject_error() -> None:
    # To test, open Yakut monitor as shown below and run this script; the error count will increase:
    #   UAVCAN__UDP__IFACE="127.0.0.1" y mon
    bad_heartbeat = bytes.fromhex(
        "01046400ffff551d09000000000000000000008000001d7e00000000000032"
        "00000000"  # Correct CRC: 2b53e66a
    )
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        if sys.platform.lower().startswith("linux"):
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # type: ignore
        sock.bind(("127.0.0.1", 0))
        sock.sendto(bad_heartbeat, ("239.0.29.85", 9382))


async def _delay(target: Awaitable[None], delay: float, duration: Optional[float] = None) -> None:
    await asyncio.sleep(delay)
    _logger.info("LAUNCHING %s", target)
    try:
        if duration is None:
            await target
        else:
            await asyncio.wait_for(target, duration)
    except (asyncio.TimeoutError, asyncio.CancelledError):  # pragma: no cover
        pass
    _logger.info("FINISHED %s", target)


async def _main() -> None:  # pragma: no cover
    """
    This is intended to aid in manual testing of the UI.
    Run this file and visually validate the behavior of the tool.

    This is how you can record the screen if you want a gif or something:

        ffmpeg -video_size 1900x800 -framerate 10 -f x11grab -i :0.0+0,117 -tune stillimage output.mp4
        ffmpeg -i output.mp4 output.gif

    Docs on ffmpeg: https://trac.ffmpeg.org/wiki/Capture/Desktop
    """
    await asyncio.gather(
        _delay(_run_nodes(), 0.0, 30.0),
        _delay(_run_zombie(), 6.0, 10.0),
        _delay(_run_anonymous(), 3.0, 10.0),
        _delay(_inject_error(), 3.0),
    )


_logger = logging.getLogger(__name__)

if __name__ == "__main__":  # pragma: no cover
    asyncio.run(_main())
