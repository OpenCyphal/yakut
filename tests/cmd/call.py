# Copyright (c) 2020 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

from __future__ import annotations
import json
import asyncio
import typing
import pyuavcan
import pytest
from tests.subprocess import Subprocess, execute_cli
from tests.dsdl import OUTPUT_DIR
from tests.transport import TransportFactory
from yakut.param.transport import construct_transport


@pytest.mark.asyncio
async def _unittest_call_custom(transport_factory: TransportFactory, compiled_dsdl: typing.Any) -> None:
    asyncio.get_running_loop().slow_callback_duration = 5.0

    _ = compiled_dsdl
    env = {
        "YAKUT_TRANSPORT": transport_factory(88).expression,
        "YAKUT_PATH": str(OUTPUT_DIR),
    }

    from sirius_cyber_corp import PerformLinearLeastSquaresFit_1_0

    # Set up the server that we will be testing the client against.
    server_transport = construct_transport(transport_factory(22).expression)
    server_presentation = pyuavcan.presentation.Presentation(server_transport)
    server = server_presentation.get_server(PerformLinearLeastSquaresFit_1_0, 222)
    last_metadata: typing.Optional[pyuavcan.presentation.ServiceRequestMetadata] = None

    async def handle_request(
        request: PerformLinearLeastSquaresFit_1_0.Request,
        metadata: pyuavcan.presentation.ServiceRequestMetadata,
    ) -> PerformLinearLeastSquaresFit_1_0.Response:
        nonlocal last_metadata
        last_metadata = metadata
        print("REQUEST OBJECT  :", request)
        print("REQUEST METADATA:", metadata)
        sum_x = sum(map(lambda p: p.x, request.points))  # type: ignore
        sum_y = sum(map(lambda p: p.y, request.points))  # type: ignore
        a = sum_x * sum_y - len(request.points) * sum(map(lambda p: p.x * p.y, request.points))  # type: ignore
        b = sum_x * sum_x - len(request.points) * sum(map(lambda p: p.x ** 2, request.points))  # type: ignore
        slope = a / b
        y_intercept = (sum_y - slope * sum_x) / len(request.points)
        response = PerformLinearLeastSquaresFit_1_0.Response(slope=slope, y_intercept=y_intercept)
        print("RESPONSE OBJECT:", response)
        return response

    # Invoke the service and then run the server for a few seconds to let it process the request.
    proc = Subprocess.cli(
        "-v",
        "--format=json",
        "call",
        "22",
        "222:sirius_cyber_corp.PerformLinearLeastSquaresFit.1.0",
        "points: [{x: 10, y: 1}, {x: 20, y: 2}]",
        "--priority=SLOW",
        "--with-metadata",
        environment_variables=env,
    )
    await server.serve_for(handle_request, 3.0)
    result, stdout, _ = proc.wait(5.0)
    assert result == 0
    assert last_metadata is not None
    assert last_metadata.priority == pyuavcan.transport.Priority.SLOW
    assert last_metadata.client_node_id == 88

    # Finalize to avoid warnings in the output.
    server.close()
    server_presentation.close()
    await asyncio.sleep(1.0)

    # Parse the output and validate it.
    parsed = json.loads(stdout)
    print("PARSED RESPONSE:", parsed)
    assert parsed["222"]["_metadata_"]["priority"] == "slow"
    assert parsed["222"]["_metadata_"]["source_node_id"] == 22
    assert parsed["222"]["slope"] == pytest.approx(0.1)
    assert parsed["222"]["y_intercept"] == pytest.approx(0.0)

    # Timed-out request.
    result, stdout, stderr = execute_cli(
        "call",
        "--timeout=0.1",
        "22",
        "222:sirius_cyber_corp.PerformLinearLeastSquaresFit.1.0",
        "points: [{x: 10, y: 1}, {x: 20, y: 2}]",
        environment_variables=env,
        ensure_success=False,
        log=False,
    )
    assert result == 1
    assert stdout == ""
    assert "timed out" in stderr


def _unittest_call_errors(compiled_dsdl: typing.Any) -> None:
    _ = compiled_dsdl
    env = {
        "YAKUT_PATH": str(OUTPUT_DIR),
    }

    # Non-service data type.
    result, stdout, stderr = execute_cli(
        "call",
        "22",
        "222:sirius_cyber_corp.PointXY.1.0",
        environment_variables=env,
        ensure_success=False,
        log=False,
    )
    assert result != 0
    assert stdout == ""
    assert "service type" in stderr

    # Non-existent data type.
    result, stdout, stderr = execute_cli(
        "call",
        "22",
        "222:sirius_cyber_corp.PointXY.1.0",
        ensure_success=False,
        log=False,
    )
    assert result != 0
    assert stdout == ""
    assert "yakut compile" in stderr

    # Invalid YAML.
    result, stdout, stderr = execute_cli(
        f"--path={OUTPUT_DIR}",
        "call",
        "22",
        "222:sirius_cyber_corp.PerformLinearLeastSquaresFit.1.0",
        ": }",
        ensure_success=False,
        log=False,
    )
    assert result != 0
    assert stdout == ""
    assert "parse" in stderr
    assert "request object" in stderr
