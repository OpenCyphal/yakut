# Copyright (c) 2020 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

from __future__ import annotations
import json
import logging
import asyncio
import typing
import pytest
from tests.subprocess import Subprocess, execute_cli
from tests.dsdl import OUTPUT_DIR
from tests.transport import TransportFactory
from yakut.param.transport import construct_transport


_logger = logging.getLogger(__name__)


@pytest.mark.asyncio
async def _unittest_call_custom(transport_factory: TransportFactory, compiled_dsdl: typing.Any) -> None:
    asyncio.get_running_loop().slow_callback_duration = 5.0

    _ = compiled_dsdl
    env = {
        "YAKUT_TRANSPORT": transport_factory(88).expression,
        "YAKUT_PATH": str(OUTPUT_DIR),
        "PYCYPHAL_LOGLEVEL": "INFO",  # We don't want too much output in the logs.
    }

    import pycyphal.application
    import uavcan.node
    from sirius_cyber_corp import PerformLinearLeastSquaresFit_1

    # Set up the server that we will be testing the client against.
    server_node = pycyphal.application.make_node(
        uavcan.node.GetInfo_1.Response(),
        transport=construct_transport(transport_factory(22).expression),
    )
    server_node.start()
    server_node.registry["uavcan.srv.least_squares.id"] = pycyphal.application.register.ValueProxy(
        pycyphal.application.register.Natural16([222])
    )
    server = server_node.get_server(PerformLinearLeastSquaresFit_1, "least_squares")
    last_metadata: typing.Optional[pycyphal.presentation.ServiceRequestMetadata] = None

    async def handle_request(
        request: PerformLinearLeastSquaresFit_1.Request,
        metadata: pycyphal.presentation.ServiceRequestMetadata,
    ) -> PerformLinearLeastSquaresFit_1.Response:
        nonlocal last_metadata
        last_metadata = metadata
        print("REQUEST OBJECT  :", request)
        print("REQUEST METADATA:", metadata)
        sum_x = sum(map(lambda p: p.x, request.points))
        sum_y = sum(map(lambda p: p.y, request.points))
        a = sum_x * sum_y - len(request.points) * sum(map(lambda p: p.x * p.y, request.points))
        b = sum_x * sum_x - len(request.points) * sum(map(lambda p: p.x**2, request.points))
        slope = a / b
        y_intercept = (sum_y - slope * sum_x) / len(request.points)
        response = PerformLinearLeastSquaresFit_1.Response(slope=slope, y_intercept=y_intercept)
        print("RESPONSE OBJECT:", response)
        return response

    # Invoke the service without discovery and then run the server for a few seconds to let it process the request.
    proc = Subprocess.cli(
        "-j",
        "call",
        "22",
        "222:sirius_cyber_corp.performlinearleastsquaresfit",
        "points: [{x: 10, y: 1}, {x: 20, y: 2}]",
        "--priority=SLOW",
        "--with-metadata",
        environment_variables=env,
    )
    _logger.info("Checkpoint A")
    await server.serve_for(handle_request, 5.0)
    _logger.info("Checkpoint B")
    result, stdout, _ = proc.wait(5.0)
    _logger.info("Checkpoint C")
    assert result == 0
    assert last_metadata is not None
    assert last_metadata.priority == pycyphal.transport.Priority.SLOW
    assert last_metadata.client_node_id == 88
    # Parse the output and validate it.
    parsed = json.loads(stdout)
    print("PARSED RESPONSE:", parsed)
    assert parsed["222"]["_meta_"]["priority"] == "slow"
    assert parsed["222"]["_meta_"]["source_node_id"] == 22
    assert parsed["222"]["slope"] == pytest.approx(0.1)
    assert parsed["222"]["y_intercept"] == pytest.approx(0.0)

    # Invoke the service with ID discovery and static type.
    last_metadata = None
    proc = Subprocess.cli(
        "-j",
        "call",
        "22",
        "least_squares:sirius_cyber_corp.PERFORMLINEARLEASTSQUARESFIT",
        "points: [{x: 0, y: 0}, {x: 10, y: 3}]",
        "--priority=FAST",
        "--with-metadata",
        "--timeout=5",
        environment_variables=env,
    )
    _logger.info("Checkpoint A")
    await server.serve_for(handle_request, 10.0)  # The tested process may take a few seconds to start (see logs).
    _logger.info("Checkpoint B")
    result, stdout, _ = proc.wait(10.0)
    _logger.info("Checkpoint C")
    assert result == 0
    assert last_metadata is not None
    assert last_metadata.priority == pycyphal.transport.Priority.FAST
    assert last_metadata.client_node_id == 88
    # Parse the output and validate it.
    parsed = json.loads(stdout)
    print("PARSED RESPONSE:", parsed)
    assert parsed["222"]["_meta_"]["priority"] == "fast"
    assert parsed["222"]["_meta_"]["source_node_id"] == 22
    assert parsed["222"]["slope"] == pytest.approx(0.3)
    assert parsed["222"]["y_intercept"] == pytest.approx(0.0)

    # Invoke the service with full discovery.
    last_metadata = None
    proc = Subprocess.cli(
        "-j",
        "call",
        "22",
        "least_squares",  # Type not specified -- discovered.
        "points: [{x: 0, y: 0}, {x: 10, y: 4}]",
        "--with-metadata",
        "--timeout=5",
        environment_variables=env,
    )
    _logger.info("Checkpoint A")
    await server.serve_for(handle_request, 10.0)  # The tested process may take a few seconds to start (see logs).
    _logger.info("Checkpoint B")
    result, stdout, _ = proc.wait(10.0)
    _logger.info("Checkpoint C")
    assert result == 0
    assert last_metadata is not None
    assert last_metadata.priority == pycyphal.transport.Priority.NOMINAL
    assert last_metadata.client_node_id == 88
    # Parse the output and validate it.
    parsed = json.loads(stdout)
    print("PARSED RESPONSE:", parsed)
    assert parsed["222"]["_meta_"]["priority"] == "nominal"
    assert parsed["222"]["_meta_"]["source_node_id"] == 22
    assert parsed["222"]["slope"] == pytest.approx(0.4)
    assert parsed["222"]["y_intercept"] == pytest.approx(0.0)

    # Finalize to avoid warnings in the output.
    server.close()
    server_node.close()
    await asyncio.sleep(1.0)

    # Timed-out request.
    result, stdout, stderr = execute_cli(
        "call",
        "--timeout=0.1",
        "22",
        "222:sirius_cyber_corp.PerformLinearLeastSquaresFit",
        environment_variables=env,
        ensure_success=False,
        log=False,
    )
    assert result == 1
    assert stdout == ""
    assert "timed out" in stderr

    # Timed out discovery.
    result, stdout, stderr = execute_cli(
        "call",
        "--timeout=0.1",
        "22",
        "least_squares",
        environment_variables=env,
        ensure_success=False,
        log=False,
    )
    assert result == 1
    assert stdout == ""
    assert "resolve service" in stderr


@pytest.mark.asyncio
async def _unittest_call_fixed(transport_factory: TransportFactory, compiled_dsdl: typing.Any) -> None:
    asyncio.get_running_loop().slow_callback_duration = 5.0

    _ = compiled_dsdl
    env = {
        "YAKUT_TRANSPORT": transport_factory(88).expression,
        "YAKUT_PATH": str(OUTPUT_DIR),
        "PYCYPHAL_LOGLEVEL": "INFO",  # We don't want too much output in the logs.
    }

    import pycyphal.application
    import uavcan.node

    server_node = pycyphal.application.make_node(
        uavcan.node.GetInfo_1.Response(),
        transport=construct_transport(transport_factory(22).expression),
    )
    server_node.start()

    # Invoke a fixed port-ID service.
    proc = Subprocess.cli(
        "-j",
        "call",
        "22",
        "uavcan.node.GetInfo",
        "--timeout=5.0",
        environment_variables=env,
    )
    await asyncio.sleep(10.0)  # The tested process may take a few seconds to start (see logs).
    result, stdout, _ = proc.wait(10.0)
    assert 0 == result
    parsed = json.loads(stdout)
    print("PARSED RESPONSE:", parsed)
    assert parsed["430"]

    # Finalize to avoid warnings in the output.
    server_node.close()
    await asyncio.sleep(1.0)


def _unittest_call_errors(compiled_dsdl: typing.Any) -> None:
    _ = compiled_dsdl
    env = {
        "YAKUT_PATH": str(OUTPUT_DIR),
    }

    # Non-service data type.
    result, stdout, stderr = execute_cli(
        "call",
        "22",
        "222:sirius_cyber_corp.PointXY",
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
        "222:sirius_cyber_corp.PointXY",
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
        "222:sirius_cyber_corp.PerformLinearLeastSquaresFit.1",
        ": }",
        ensure_success=False,
        log=False,
    )
    assert result != 0
    assert stdout == ""
    assert "parse" in stderr
    assert "request object" in stderr
