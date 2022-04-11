# Copyright (c) 2020 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

from __future__ import annotations
import time
import json
import typing
import pytest
import pycyphal
import yakut
import yakut.yaml
from tests.subprocess import execute_cli, Subprocess
from tests.dsdl import OUTPUT_DIR
from tests.transport import TransportFactory


def _unittest_pub_sub_regular(transport_factory: TransportFactory, compiled_dsdl: typing.Any) -> None:
    _ = compiled_dsdl
    env = {
        "YAKUT_TRANSPORT": transport_factory(None).expression,
        "YAKUT_PATH": str(OUTPUT_DIR),
    }
    proc_sub_heartbeat = Subprocess.cli(
        "--format=json",
        "sub",
        "uavcan.node.Heartbeat.1.0",
        environment_variables=env,
    )
    proc_sub_diagnostic = Subprocess.cli(
        "--format=json",
        "sub",
        "4321:uavcan.diagnostic.Record.1.1",
        "--count=3",
        environment_variables=env,
    )
    proc_sub_diagnostic_wrong_pid = Subprocess.cli(
        "--format=yaml",
        "sub",
        "uavcan.diagnostic.Record.1.1",
        "--count=3",
        environment_variables=env,
    )
    proc_sub_temperature = Subprocess.cli(
        "--format=json",
        "sub",
        "555:uavcan.si.sample.temperature.Scalar.1.0",
        "--count=3",
        "--no-metadata",
        environment_variables=env,
    )
    time.sleep(1.0)  # Time to let the background processes finish initialization

    proc_pub = Subprocess.cli(
        "-v",
        "--heartbeat-vssc=54",
        "--heartbeat-priority=high",
        "--node-info",
        "{software_image_crc: [0xdeadbeef]}",
        f"--transport={transport_factory(51).expression}",  # Takes precedence over the environment variable.
        "pub",
        "4321:uavcan.diagnostic.Record.1.1",
        '{severity: 6, timestamp: 123456, text: "Hello world!"}',  # Use shorthand init for severity, timestamp
        "1234:uavcan.diagnostic.Record.1.1",
        '{text: "Goodbye world."}',
        "555:uavcan.si.sample.temperature.Scalar.1.0",
        "{kelvin: 123.456}",
        "--count=3",
        "--period=2",
        "--priority=slow",
        environment_variables=env,
    )
    time.sleep(3.0)  # Time to let the publisher boot up properly.

    # Request GetInfo from the publisher we just launched.
    _, stdout, _ = execute_cli(
        f"--transport={transport_factory(52).expression}",
        f"--path={OUTPUT_DIR}",
        "call",
        "51",
        "uavcan.node.GetInfo.1.0",
        "--no-metadata",
        "--timeout=5",
        timeout=10.0,
    )
    parsed = yakut.yaml.Loader().load(stdout)
    assert parsed[430]["protocol_version"] == {
        "major": pycyphal.CYPHAL_SPECIFICATION_VERSION[0],
        "minor": pycyphal.CYPHAL_SPECIFICATION_VERSION[1],
    }
    assert parsed[430]["software_version"] == {
        "major": yakut.__version_info__[0],
        "minor": yakut.__version_info__[1],
    }
    assert parsed[430]["software_image_crc"] == [0xDEADBEEF]
    assert parsed[430]["name"] == "org.opencyphal.yakut.publish"

    proc_pub.wait(10.0)
    time.sleep(1.0)  # Time to sync up

    # Parse the output from the subscribers and validate it.
    out_sub_heartbeat = proc_sub_heartbeat.wait(1.0, interrupt=True)[1].splitlines()
    out_sub_diagnostic = proc_sub_diagnostic.wait(1.0, interrupt=True)[1].splitlines()
    out_sub_temperature = proc_sub_temperature.wait(1.0, interrupt=True)[1].splitlines()

    heartbeats = list(map(json.loads, out_sub_heartbeat))
    diagnostics = list(map(json.loads, out_sub_diagnostic))
    temperatures = list(map(json.loads, out_sub_temperature))

    print("heartbeats:", *heartbeats, sep="\n\t")
    print("diagnostics:", *diagnostics, sep="\n\t")
    print("temperatures:", *temperatures, sep="\n\t")

    assert 1 <= len(heartbeats) <= 20
    for m in heartbeats:
        src_nid = m["7509"]["_metadata_"]["source_node_id"]
        if src_nid == 51:  # The publisher
            assert "high" in m["7509"]["_metadata_"]["priority"].lower()
            assert m["7509"]["_metadata_"]["transfer_id"] >= 0
            assert m["7509"]["uptime"] in range(10)
            assert m["7509"]["vendor_specific_status_code"] == 54
        elif src_nid == 52:  # The caller (GetInfo)
            assert "nominal" in m["7509"]["_metadata_"]["priority"].lower()
            assert m["7509"]["_metadata_"]["transfer_id"] >= 0
            assert m["7509"]["uptime"] in range(4)
        else:
            assert False

    assert len(diagnostics) == 3
    for m in diagnostics:
        assert "slow" in m["4321"]["_metadata_"]["priority"].lower()
        assert m["4321"]["_metadata_"]["transfer_id"] >= 0
        assert m["4321"]["_metadata_"]["source_node_id"] == 51
        assert m["4321"]["timestamp"]["microsecond"] == 123456
        assert m["4321"]["text"] == "Hello world!"

    assert len(temperatures) == 3
    assert all(map(lambda mt: mt["555"]["kelvin"] == pytest.approx(123.456), temperatures))

    assert proc_sub_diagnostic_wrong_pid.alive
    assert proc_sub_diagnostic_wrong_pid.wait(1.0, interrupt=True)[1].strip() == ""


def _unittest_slow_cli_pub_sub_anon(transport_factory: TransportFactory, compiled_dsdl: typing.Any) -> None:
    _ = compiled_dsdl
    env = {
        "YAKUT_TRANSPORT": transport_factory(None).expression,
        "YAKUT_PATH": str(OUTPUT_DIR),
    }
    proc_sub_heartbeat = Subprocess.cli(
        "-v",
        "--format=json",
        "sub",
        "uavcan.node.Heartbeat.1.0",
        environment_variables=env,
    )
    proc_sub_diagnostic_with_meta = Subprocess.cli(
        "-v",
        "--format=json",
        "sub",
        "uavcan.diagnostic.Record.1.1",
        environment_variables=env,
    )
    proc_sub_diagnostic_no_meta = Subprocess.cli(
        "-v",
        "--format=json",
        "sub",
        "uavcan.diagnostic.Record.1.1",
        "--no-metadata",
        environment_variables=env,
    )

    time.sleep(3.0)  # Time to let the background processes finish initialization

    if transport_factory(None).can_transmit:
        proc = Subprocess.cli(
            "pub",
            "uavcan.diagnostic.Record.1.1",
            "{}",
            "--count=2",
            "--period=2",
            environment_variables=env,
        )
        proc.wait(timeout=8)

        time.sleep(2.0)  # Time to sync up

        assert (
            proc_sub_heartbeat.wait(1.0, interrupt=True)[1].strip() == ""
        ), "Anonymous nodes must not broadcast heartbeat"

        diagnostics = list(
            json.loads(s) for s in proc_sub_diagnostic_with_meta.wait(1.0, interrupt=True)[1].splitlines()
        )
        print("diagnostics:", diagnostics)
        # Remember that anonymous transfers over redundant transports are NOT deduplicated.
        # Hence, to support the case of redundant transports, we use 'greater or equal' here.
        assert len(diagnostics) >= 2
        for m in diagnostics:
            assert "nominal" in m["8184"]["_metadata_"]["priority"].lower()
            assert m["8184"]["_metadata_"]["transfer_id"] >= 0
            assert m["8184"]["_metadata_"]["source_node_id"] is None
            assert m["8184"]["timestamp"]["microsecond"] == 0
            assert m["8184"]["text"] == ""

        diagnostics = list(json.loads(s) for s in proc_sub_diagnostic_no_meta.wait(1.0, interrupt=True)[1].splitlines())
        print("diagnostics:", diagnostics)
        assert len(diagnostics) >= 2  # >= because see above
        for m in diagnostics:
            assert m["8184"]["timestamp"]["microsecond"] == 0
            assert m["8184"]["text"] == ""
    else:
        proc = Subprocess.cli(
            "-v",
            "pub",
            "uavcan.diagnostic.Record.1.1",
            "{}",
            "--count=2",
            "--period=2",
            environment_variables=env,
        )
        assert 0 < proc.wait(timeout=8, log=False)[0]
