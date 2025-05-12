# Copyright (c) 2020 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

from __future__ import annotations
import time
from tests.subprocess import Subprocess, execute_cli
from tests.transport import TransportFactory


def _unittest_accommodate_swarm(transport_factory: TransportFactory) -> None:
    # We spawn a lot of processes here, which might strain the test system a little, so beware. I've tested it
    # with 120 processes and it made my workstation (24 GB RAM ~4 GHz Core i7) struggle to the point of being
    # unable to maintain sufficiently real-time operation for the test to pass. Hm.
    used_node_ids = list(range(5))
    pubs = [
        Subprocess.cli(
            f"--transport={transport_factory(idx).expression}",
            "pub",
            "--period=0.4",
            "--count=60",
        )
        for idx in used_node_ids
    ]
    time.sleep(5)  # Some time is required for the nodes to start.
    _, stdout, _ = execute_cli(
        "-v",
        f"--transport={transport_factory(None).expression}",
        "accommodate",
        timeout=100.0,
    )
    assert int(stdout) not in used_node_ids
    for p in pubs:
        p.wait(100.0, interrupt=True)


def _unittest_accommodate_loopback() -> None:
    _, stdout, _ = execute_cli(
        "-v",
        "accommodate",
        timeout=30.0,
        environment_variables={"YAKUT_TRANSPORT": "Loopback(None),Loopback(None)"},
    )
    assert 0 <= int(stdout) < 2**64


def _unittest_accommodate_udp_localhost() -> None:
    _, stdout, _ = execute_cli(
        "-v",
        "accommodate",
        timeout=30.0,
        environment_variables={"YAKUT_TRANSPORT": 'UDP("127.0.0.1",None)'},
    )
    # Exclude zero from the set because an IP address with the host address of zero may cause complications.
    assert 1 <= int(stdout) <= 65534
