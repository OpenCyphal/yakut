# Copyright (c) 2022 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

from __future__ import annotations
import time
import json
import typing
from tests.subprocess import Subprocess, execute_cli
from tests.dsdl import OUTPUT_DIR
from tests.transport import TransportFactory


def _unittest_monoclust_ts_field_auto(transport_factory: TransportFactory, compiled_dsdl: typing.Any) -> None:
    _ = compiled_dsdl
    proc_sub = Subprocess.cli(
        "--format=json",
        "sub",
        "1000:uavcan.si.sample.mass.Scalar",
        "2000:uavcan.si.sample.mass.Scalar",
        "--no-metadata",
        "--count=3",
        "--sync-monoclust",  # Automatic tolerance setting.
        environment_variables={
            "YAKUT_TRANSPORT": transport_factory(10).expression,
            "YAKUT_PATH": str(OUTPUT_DIR),
        },
    )
    time.sleep(10.0)
    proc_pub = Subprocess.cli(
        "-v",
        "pub",
        "1000:uavcan.si.sample.mass.Scalar",
        "!$ n * 1e6",
        "2000:uavcan.si.sample.mass.Scalar",
        "!$ (n + 0.4) * 1e6",  # Introduce intentional divergence to ensure the tolerance is not too tight.
        environment_variables={
            "YAKUT_TRANSPORT": transport_factory(11).expression,
            "YAKUT_PATH": str(OUTPUT_DIR),
        },
    )
    out_sub = proc_sub.wait(30.0)[1].splitlines()
    proc_pub.wait(10.0, interrupt=True)
    msgs = list(map(json.loads, out_sub))
    assert msgs == [
        {
            "1000": {"timestamp": {"microsecond": 000000}, "kilogram": 0.0},
            "2000": {"timestamp": {"microsecond": 400000}, "kilogram": 0.0},
        },
        {
            "1000": {"timestamp": {"microsecond": 1_000000}, "kilogram": 0.0},
            "2000": {"timestamp": {"microsecond": 1_400000}, "kilogram": 0.0},
        },
        {
            "1000": {"timestamp": {"microsecond": 2_000000}, "kilogram": 0.0},
            "2000": {"timestamp": {"microsecond": 2_400000}, "kilogram": 0.0},
        },
    ]


def _unittest_monoclust_ts_field_manual(transport_factory: TransportFactory, compiled_dsdl: typing.Any) -> None:
    _ = compiled_dsdl
    proc_sub = Subprocess.cli(
        "--format=json",
        "sub",
        "1000:uavcan.si.sample.mass.Scalar",
        "2000:uavcan.si.sample.mass.Scalar",
        "--no-metadata",
        "--sync-monoclust=0.25",  # Fixed tolerance setting; count not limited
        environment_variables={
            "YAKUT_TRANSPORT": transport_factory(10).expression,
            "YAKUT_PATH": str(OUTPUT_DIR),
        },
    )
    time.sleep(10.0)
    proc_pub = Subprocess.cli(
        "-v",
        "pub",
        "1000:uavcan.si.sample.mass.Scalar",
        "!$ n * 1.00 * 1e6",
        "2000:uavcan.si.sample.mass.Scalar",
        "!$ n * 1.09 * 1e6",  # Timestamps will diverge after 3 publication cycles.
        environment_variables={
            "YAKUT_TRANSPORT": transport_factory(11).expression,
            "YAKUT_PATH": str(OUTPUT_DIR),
        },
    )
    time.sleep(9)
    out_sub = proc_sub.wait(5.0, interrupt=True)[1].splitlines()
    proc_pub.wait(10.0, interrupt=True)
    msgs = list(map(json.loads, out_sub))
    print("msgs:", *msgs, sep="\n\t")
    assert msgs == [
        {
            "1000": {"timestamp": {"microsecond": 000000}, "kilogram": 0.0},
            "2000": {"timestamp": {"microsecond": 000000}, "kilogram": 0.0},
        },
        {
            "1000": {"timestamp": {"microsecond": 1_000_000}, "kilogram": 0.0},
            "2000": {"timestamp": {"microsecond": 1_090_000}, "kilogram": 0.0},
        },
        {
            "1000": {"timestamp": {"microsecond": 2_000_000}, "kilogram": 0.0},
            "2000": {"timestamp": {"microsecond": 2_180_000}, "kilogram": 0.0},
        },
    ]


def _unittest_monoclust_ts_field_type_not_timestamped(
    transport_factory: TransportFactory, compiled_dsdl: typing.Any
) -> None:
    _ = compiled_dsdl
    code, stdout, stderr = execute_cli(
        "sub",
        "1000:uavcan.si.unit.mass.Scalar",
        "2000:uavcan.si.unit.mass.Scalar",
        "--sync-monoclust",  # Require timestamp field matching but the data types have no such field
        environment_variables={
            "YAKUT_TRANSPORT": transport_factory(10).expression,
            "YAKUT_PATH": str(OUTPUT_DIR),
        },
        timeout=10.0,
        ensure_success=False,
    )
    assert code > 0
    assert not stdout
    assert "timestamp" in stderr
    assert "synchro" in stderr


def _unittest_monoclust_ts_arrival_auto(transport_factory: TransportFactory, compiled_dsdl: typing.Any) -> None:
    _ = compiled_dsdl
    proc_sub = Subprocess.cli(
        "--format=json",
        "sub",
        "1000:uavcan.primitive.String",
        "2000:uavcan.primitive.String",
        "--no-metadata",
        "--count=3",
        "--sync-monoclust-arrival",  # Automatic tolerance setting.
        environment_variables={
            "YAKUT_TRANSPORT": transport_factory(10).expression,
            "YAKUT_PATH": str(OUTPUT_DIR),
        },
    )
    time.sleep(3.0)
    proc_pub = Subprocess.cli(
        "-v",
        "pub",
        "1000:uavcan.primitive.String",
        "!$ str(n)",
        "2000:uavcan.primitive.String",
        "!$ str(n)",
        environment_variables={
            "YAKUT_TRANSPORT": transport_factory(11).expression,
            "YAKUT_PATH": str(OUTPUT_DIR),
        },
    )
    out_sub = proc_sub.wait(30.0)[1].splitlines()
    proc_pub.wait(10.0, interrupt=True)
    msgs = list(map(json.loads, out_sub))
    assert msgs == [
        {"1000": {"value": "0"}, "2000": {"value": "0"}},
        {"1000": {"value": "1"}, "2000": {"value": "1"}},
        {"1000": {"value": "2"}, "2000": {"value": "2"}},
    ]


def _unittest_transfer_id(transport_factory: TransportFactory, compiled_dsdl: typing.Any) -> None:
    _ = compiled_dsdl
    proc_sub = Subprocess.cli(
        "--format=json",
        "sub",
        "1000:uavcan.primitive.String",
        "2000:uavcan.primitive.String",
        "--no-metadata",
        "--count=3",
        "--sync-transfer-id",
        environment_variables={
            "YAKUT_TRANSPORT": transport_factory(10).expression,
            "YAKUT_PATH": str(OUTPUT_DIR),
        },
    )
    time.sleep(3.0)
    proc_pub = Subprocess.cli(
        "-v",
        "pub",
        "1000:uavcan.primitive.String",
        "!$ str(n)",
        "2000:uavcan.primitive.String",
        "!$ str(n)",
        environment_variables={
            "YAKUT_TRANSPORT": transport_factory(11).expression,
            "YAKUT_PATH": str(OUTPUT_DIR),
        },
    )
    out_sub = proc_sub.wait(30.0)[1].splitlines()
    proc_pub.wait(10.0, interrupt=True)
    msgs = list(map(json.loads, out_sub))
    assert msgs == [
        {"1000": {"value": "0"}, "2000": {"value": "0"}},
        {"1000": {"value": "1"}, "2000": {"value": "1"}},
        {"1000": {"value": "2"}, "2000": {"value": "2"}},
    ]
