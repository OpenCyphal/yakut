# Copyright (c) 2019 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

import sys
import typing
import decimal
import contextlib
import click
import pyuavcan
import yakut
from yakut.helpers import EnumParam
from yakut.param.formatter import Formatter
from yakut.util import convert_transfer_metadata_to_builtin, construct_port_id_and_type


_S = typing.TypeVar("_S", bound=pyuavcan.dsdl.ServiceObject)


_logger = yakut.get_logger(__name__)


def _validate_request_fields(ctx: click.Context, param: click.Parameter, value: str) -> typing.Any:
    from yakut.yaml import EvaluableLoader

    eval_context: typing.Dict[str, typing.Any] = {}  # Add useful members later.
    try:
        fields = EvaluableLoader(eval_context).load(value)
    except Exception as ex:
        raise click.BadParameter(f"Could not parse the request object fields: {ex}", ctx=ctx, param=param)
    return fields


@yakut.subcommand()
@click.argument("server_node_id", metavar="SERVER_NODE_ID", type=int, required=True)
@click.argument("service", metavar="SERVICE", type=str, required=True)
@click.argument("request_fields", metavar="FIELDS", type=str, callback=_validate_request_fields, default="{}")
@click.option(
    "--timeout",
    "-T",
    type=float,
    default=pyuavcan.presentation.DEFAULT_SERVICE_REQUEST_TIMEOUT,
    show_default=True,
    metavar="SECONDS",
    help=f"Request timeout; how long to wait for the response before giving up.",
)
@click.option(
    "--priority",
    "-P",
    default=pyuavcan.presentation.DEFAULT_PRIORITY,
    type=EnumParam(pyuavcan.transport.Priority),
    help=f"Priority of the request transfer. [default: {pyuavcan.presentation.DEFAULT_PRIORITY.name}]",
)
@click.option(
    "--with-metadata/--no-metadata",
    "+M/-M",
    default=False,
    show_default=True,
    help="When enabled, the response object is prepended with an extra field named `_metadata_`.",
)
@yakut.pass_purser
@yakut.asynchronous
async def call(
    purser: yakut.Purser,
    server_node_id: int,
    service: str,
    request_fields: typing.Any,
    timeout: float,
    priority: pyuavcan.transport.Priority,
    with_metadata: bool,
) -> None:
    """
    Invoke an RPC-service using the specified request object and print the response.
    Unless the local transport is configured in anonymous node,
    while waiting for the response the local node will also publish on standard subjects like
    Heartbeat and provide some standard RPC-services like GetInfo.

    The first positional argument is the server node-ID.
    The second is the pair of service-ID (which can be omitted if a fixed one is defined for the type)
    and the data type name of the form:

    \b
        [SERVICE_ID:]FULL_SERVICE_TYPE_NAME.MAJOR.MINOR

    In the data type name, forward or backward slashes can be used instead of ".";
    version numbers can be also separated using underscores.
    This is done to allow the user to rely on filesystem autocompletion when typing the command.

    The third positional argument specifies the values of the request object fields in YAML format
    (or JSON, which is a subset of YAML).
    Missing fields will be left at their default values.
    If omitted, this argument defaults to an empty object: `{}`.
    For more info about the format see PyUAVCAN documentation on builtin-based representations.

    The output will be printed as a key-value mapping of one element where the key is the service-ID
    and the value is the received response object.

    Examples:

    \b
        yakut call 42 uavcan.node.GetInfo.1.0 +M -T3 -Pe
        yakut call 42 123:sirius_cyber_corp.PerformLinearLeastSquaresFit.1.0 'points: [{x: 10, y: 1}, {x: 20, y: 2}]'
        yakut call 42 123:sirius_cyber_corp.PerformLinearLeastSquaresFit.1.0 '[[10, 1], [20, 2]]'
    """
    try:
        from pyuavcan.application import Node
    except ImportError as ex:
        from yakut.cmd.compile import make_usage_suggestion

        raise click.UsageError(make_usage_suggestion(ex.name))

    _logger.debug(
        "server_node_id=%s, service=%r, request_fields=%r, timeout=%.6f, priority=%s, with_metadata=%s",
        server_node_id,
        service,
        request_fields,
        timeout,
        priority,
        with_metadata,
    )

    service_id, dtype = construct_port_id_and_type(service)
    if not issubclass(dtype, pyuavcan.dsdl.ServiceObject):
        raise TypeError(f"Expected a service type; got {dtype.__name__}")

    request = pyuavcan.dsdl.update_from_builtin(dtype.Request(), request_fields)
    _logger.info("Request object: %r", request)

    formatter = purser.make_formatter()
    node = purser.get_node("call", allow_anonymous=False)
    assert isinstance(node, Node) and callable(formatter)
    with contextlib.closing(node):
        client = node.presentation.make_client(dtype, service_id, server_node_id)
        client.response_timeout = timeout
        client.priority = priority
        node.start()
        await _run(client, request, formatter, with_metadata=with_metadata)


async def _run(
    client: pyuavcan.presentation.Client[_S],
    request: pyuavcan.dsdl.CompositeObject,
    formatter: Formatter,
    with_metadata: bool,
) -> None:
    request_ts_transport: typing.Optional[pyuavcan.transport.Timestamp] = None

    def on_transfer_feedback(fb: pyuavcan.transport.Feedback) -> None:
        nonlocal request_ts_transport
        request_ts_transport = fb.first_frame_transmission_timestamp

    client.output_transport_session.enable_feedback(on_transfer_feedback)

    request_ts_application = pyuavcan.transport.Timestamp.now()
    result = await client.call(request)
    response_ts_application = pyuavcan.transport.Timestamp.now()
    if result is None:
        click.secho(f"The request has timed out after {client.response_timeout:0.1f} seconds", err=True, fg="red")
        sys.exit(1)
    if not request_ts_transport:  # pragma: no cover
        request_ts_transport = request_ts_application
        _logger.warning(
            "The transport implementation is misbehaving: feedback was never emitted; "
            "falling back to software timestamping. "
            "Please submit a bug report. Involved instances: client=%r, result=%r",
            client,
            result,
        )
    response, transfer = result
    transport_duration = transfer.timestamp.monotonic - request_ts_transport.monotonic
    application_duration = response_ts_application.monotonic - request_ts_application.monotonic
    _logger.info(
        "Request duration [second]: "
        "transport layer: %.6f, application layer: %.6f, application layer overhead: %.6f",
        transport_duration,
        application_duration,
        application_duration - transport_duration,
    )

    bi: typing.Dict[str, typing.Any] = {}  # We use updates to ensure proper dict ordering: metadata before data
    if with_metadata:
        qnt = decimal.Decimal("0.000001")
        bi.update(
            convert_transfer_metadata_to_builtin(
                transfer,
                roundtrip_time={
                    "transport_layer": (transfer.timestamp.monotonic - request_ts_transport.monotonic).quantize(qnt),
                    "application_layer": application_duration.quantize(qnt),
                },
            )
        )
    bi.update(pyuavcan.dsdl.to_builtin(response))

    print(formatter({client.port_id: bi}))
