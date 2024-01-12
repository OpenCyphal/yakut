# Copyright (c) 2019 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

from __future__ import annotations
import os
import sys
import time
import typing
import dataclasses
import pytest
from .subprocess import Subprocess


@dataclasses.dataclass(frozen=True)
class TransportConfig:
    """
    Either "expression" or "environment" can be used to initialize the node.
    The configurations should be nearly equivalent.
    """

    expression: str
    environment: dict[str, str]


TransportFactory = typing.Callable[[typing.Optional[int]], TransportConfig]
"""
This factory constructs arguments for the CLI instructing it to use a particular transport configuration.
The factory takes one argument - the node-ID - which can be None (anonymous).
"""

SERIAL_BROKER_PORT = 50905


def _generate() -> typing.Iterator[typing.Callable[[], typing.Iterator[TransportFactory]]]:
    """
    Sensible transport configurations supported by the CLI to test against.
    Don't forget to extend when adding support for new transports.
    """

    def mk_env(node_id: int | None, **items: typing.Any) -> dict[str, str]:
        return {
            **{k: str(v) for k, v in items.items()},
            **({"UAVCAN__NODE__ID": str(node_id)} if node_id is not None else {}),
        }

    if sys.platform == "linux":  # pragma: no branch

        def sudo(cmd: str, ensure_success: bool = True) -> None:
            c = f"sudo {cmd}"
            r = os.system(c)
            if ensure_success and 0 != r:  # pragma: no cover
                raise RuntimeError(f"Command {c!r} failed with exit code {r}")

        sudo("modprobe can")
        sudo("modprobe can_raw")
        sudo("modprobe vcan")
        for idx in range(3):
            iface = f"vcan{idx}"
            sudo(f"ip link add dev {iface} type vcan", ensure_success=False)
            sudo(f"ip link set     {iface} mtu 72")
            sudo(f"ip link set up  {iface}")

        def vcan() -> typing.Iterator[TransportFactory]:
            yield lambda nid: TransportConfig(
                expression=f"CAN(can.media.socketcan.SocketCANMedia('vcan0',64),local_node_id={nid})",
                environment=mk_env(
                    nid,
                    UAVCAN__CAN__IFACE="socketcan:vcan0",
                    UAVCAN__CAN__MTU=64,
                ),
            )

        def vcan_tmr() -> typing.Iterator[TransportFactory]:
            # In anonymous mode, transfers with >8/32 bytes may fail for some transports. This is intentional.
            yield lambda nid: TransportConfig(
                expression=(
                    ",".join(
                        f"CAN(can.media.socketcan.SocketCANMedia('vcan{idx}',{mtu}),local_node_id={nid})"
                        for idx, mtu in enumerate([8, 32, 64])
                    )
                ),
                environment=mk_env(
                    nid,
                    UAVCAN__CAN__IFACE="socketcan:vcan0 socketcan:vcan1 socketcan:vcan2",
                    UAVCAN__CAN__MTU="64",
                ),
            )

        yield vcan
        yield vcan_tmr

    serial_endpoint = f"socket://127.0.0.1:{SERIAL_BROKER_PORT}"

    def launch_serial_broker() -> Subprocess:
        out = Subprocess("ncat", "--broker", "--listen", "--verbose", f"--source-port={SERIAL_BROKER_PORT}")
        # The sleep is needed to let the broker initialize before starting the tests to avoid connection error.
        # This is only relevant for Windows. See details: https://github.com/OpenCyphal/yakut/issues/26
        time.sleep(2)
        if not out.alive:
            status, _stdout, stderr = out.wait(1.0)
            raise RuntimeError(f"Cyphal/serial broker could not be launched. Exit status: {status}; stderr:\n" + stderr)
        return out

    def serial_tunneled_via_tcp() -> typing.Iterator[TransportFactory]:
        broker = launch_serial_broker()
        assert broker.alive
        yield lambda nid: TransportConfig(
            expression=f"Serial('{serial_endpoint}',local_node_id={nid})",
            environment=mk_env(
                nid,
                UAVCAN__SERIAL__IFACE=serial_endpoint,
            ),
        )
        assert broker.alive
        time.sleep(1.0)  # Ensure all clients have disconnected to avoid warnings in the test logs.
        assert broker.alive
        broker.wait(5.0, interrupt=True)

    def udp_loopback() -> typing.Iterator[TransportFactory]:
        yield lambda nid: (
            TransportConfig(
                expression=f"UDP('127.0.0.1',{nid})",
                environment=mk_env(
                    nid,
                    UAVCAN__UDP__IFACE="127.0.0.1",
                ),
            )
        )

    def heterogeneous_udp_serial() -> typing.Iterator[TransportFactory]:
        broker = launch_serial_broker()
        assert broker.alive
        yield lambda nid: TransportConfig(
            expression=(
                ",".join(
                    [
                        f"Serial('{serial_endpoint}',{nid})",
                        f"UDP('127.0.0.1',{nid})",
                    ]
                )
            ),
            environment=mk_env(
                nid,
                UAVCAN__SERIAL__IFACE=serial_endpoint,
                UAVCAN__UDP__IFACE="127.0.0.1",
            ),
        )
        assert broker.alive
        time.sleep(1.0)  # Ensure all clients have disconnected to avoid warnings in the test logs.
        assert broker.alive
        broker.wait(5.0, interrupt=True)

    yield serial_tunneled_via_tcp
    yield udp_loopback
    yield heterogeneous_udp_serial


@pytest.fixture(params=_generate())
def transport_factory(request: typing.Any) -> typing.Iterable[TransportFactory]:
    yield from request.param()
