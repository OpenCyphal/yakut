# Copyright (c) 2019 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

import sys
import typing
import dataclasses


SERIAL_PORT_NAME = "socket://localhost:50905"
"""
The test environment expects a TCP broker to be available at this endpoint.
For example::

    ncat --broker --listen -p 50905
"""


@dataclasses.dataclass(frozen=True)
class TransportConfig:
    expression: str
    can_transmit: bool


TransportFactory = typing.Callable[[typing.Optional[int]], TransportConfig]
"""
This factory constructs arguments for the CLI instructing it to use a particular transport configuration.
The factory takes one argument - the node-ID - which can be None (anonymous).
"""


def _make_transport_factories() -> typing.Iterable[TransportFactory]:
    """
    Sensible transport configurations supported by the CLI to test against.
    Don't forget to extend when adding support for new transports.
    """
    if sys.platform == "linux":
        # CAN via SocketCAN
        yield lambda nid: TransportConfig(
            expression=f"CAN(can.media.socketcan.SocketCANMedia('vcan0',64),local_node_id={nid})",
            can_transmit=True,
        )

        # Redundant CAN via SocketCAN
        yield lambda nid: TransportConfig(
            expression=(
                ",".join(
                    f"CAN(can.media.socketcan.SocketCANMedia('vcan{idx}',{mtu}),local_node_id={nid})"
                    for idx, mtu in enumerate([8, 32, 64])
                )
            ),
            can_transmit=True,
        )

    # Serial via TCP/IP tunnel (emulation)
    yield lambda nid: TransportConfig(
        expression=f"Serial('{SERIAL_PORT_NAME}',local_node_id={nid})",
        can_transmit=True,
    )

    # UDP/IP on localhost (cannot transmit if anonymous)
    yield lambda nid: TransportConfig(
        expression=f"UDP('127.0.0.{nid}')",
        can_transmit=True,
    ) if nid is not None else TransportConfig(
        expression="UDP('127.0.0.1',anonymous=True)",
        can_transmit=False,
    )

    # Redundant UDP+Serial. The UDP transport does not support anonymous transfers.
    yield lambda nid: TransportConfig(
        expression=(
            ",".join(
                [
                    f"Serial('{SERIAL_PORT_NAME}',local_node_id={nid})",
                    (f"UDP('127.0.0.{nid}')" if nid is not None else "UDP('127.0.0.1',anonymous=True)"),
                ]
            )
        ),
        can_transmit=nid is not None,
    )


TRANSPORT_FACTORIES = list(_make_transport_factories())
