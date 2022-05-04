# Copyright (c) 2019 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

from __future__ import annotations
import sys
from typing import Any, Callable, TYPE_CHECKING
import decimal
from functools import lru_cache
import click
import pycyphal
import yakut
from yakut.enum_param import EnumParam
from yakut.param.formatter import Formatter, FormatterHints
from yakut.util import convert_transfer_metadata_to_builtin
from yakut import dtype_loader

if TYPE_CHECKING:
    from pycyphal.application import Node


_RESOLVER_MIN_RESPONSE_TIMEOUT = 1.0

_logger = yakut.get_logger(__name__)


def _validate_request_fields(ctx: click.Context, param: click.Parameter, value: str) -> Any:
    from yakut.yaml import EvaluableLoader

    eval_context: dict[str, Any] = {}  # Add useful members later.
    try:
        fields = EvaluableLoader(eval_context).load(value)
    except Exception as ex:
        raise click.BadParameter(f"Could not parse the request object fields: {ex}", ctx=ctx, param=param)
    return fields


@yakut.subcommand(aliases="q")
@click.argument("server_node_id", metavar="SERVER_NODE_ID", type=int, required=True)
@click.argument("service", metavar="SERVICE", type=str, required=True)
@click.argument("request_fields", metavar="FIELDS", type=str, callback=_validate_request_fields, default="{}")
@click.option(
    "--timeout",
    "-T",
    type=float,
    default=pycyphal.presentation.DEFAULT_SERVICE_REQUEST_TIMEOUT,
    show_default=True,
    metavar="SECONDS",
    help=f"Request timeout; how long to wait for the response before giving up.",
)
@click.option(
    "--priority",
    "-P",
    default=pycyphal.presentation.DEFAULT_PRIORITY,
    type=EnumParam(pycyphal.transport.Priority),
    help=f"Priority of the request transfer. [default: {pycyphal.presentation.DEFAULT_PRIORITY.name}]",
)
@click.option(
    "--with-metadata/--no-metadata",
    "+M/-M",
    default=False,
    show_default=True,
    help="When enabled, the response object is prepended with an extra field named `_meta_`.",
)
@yakut.pass_purser
@yakut.asynchronous()
async def call(
    purser: yakut.Purser,
    server_node_id: int,
    service: str,
    request_fields: Any,
    timeout: float,
    priority: pycyphal.transport.Priority,
    with_metadata: bool,
) -> None:
    """
    Invoke an RPC-service using the specified request object and print the response.
    The local node will also publish on standard subjects like Heartbeat and provide some standard RPC-services.

    The first positional argument is the server node-ID.

    The second positional argument specifies which service to invoke on the server, which can be done in two ways:
    1. specify the numerical service-ID and its type separated by colon;
    2. specify the name of the service only and let Yakut retrieve the type information from the server.
    The syntax of the available options is as follows:

    \b
        [SERVICE_ID:]TYPE_NAME[.MAJOR[.MINOR]]
        SERVICE_NAME[:TYPE_NAME[.MAJOR[.MINOR]]]

    The short data type name is case-insensitive for convenience.
    In the data type name, "/" or "\\" can be used instead of "." for convenience and filesystem autocompletion.
    If the data type is specified without the service-ID, a fixed service-ID shall be defined for this data type.
    Missing version numbers default to the latest available.
    The two formats are differentiated automatically using heuristics.

    The third positional argument specifies the values of the request object fields in YAML format
    (or JSON, which is a subset of YAML).
    Missing fields will be left at their default values.
    If omitted, this argument defaults to an empty object: `{}`.
    For more info about the format see pycyphal.dsdl.update_from_builtin().

    The output will be printed as a key-value mapping of one element where the key is the service-ID
    and the value is the received response object (optionally with metadata).

    Examples:

    \b
        yakut call 42 uavcan.node.getinfo +M -T3 -Pe
        yakut call 42 least_squares 'points: [{x: 10, y: 1}, {x: 20, y: 2}]'
        yakut call 42 least_squares:sirius_cyber_corp.PerformLinearLeastSquaresFit '[[10, 1], [20, 2]]'
    """
    try:
        from pycyphal.application import Node
    except ImportError as ex:
        from yakut.cmd.compile import make_usage_suggestion

        raise click.ClickException(make_usage_suggestion(ex.name))

    _logger.debug(
        "server_node_id=%s, service=%r, request_fields=%r, timeout=%.6f, priority=%s, with_metadata=%s",
        server_node_id,
        service,
        request_fields,
        timeout,
        priority,
        with_metadata,
    )
    finalizers: list[Callable[[], None]] = []
    try:
        formatter = purser.make_formatter(FormatterHints(single_document=True))

        # The cached factory is needed to postpone node initialization as much as possible because it disturbs
        # the network and the networking hardware (if any) and is usually costly.
        @lru_cache(None)
        def get_node() -> Node:
            node = purser.get_node("call", allow_anonymous=False)
            finalizers.append(node.close)
            return node

        service_id, dtype = await _resolve(
            service,
            server_node_id,
            get_node,
            response_timeout=max(_RESOLVER_MIN_RESPONSE_TIMEOUT, timeout),
        )
        if not pycyphal.dsdl.is_service_type(dtype):
            raise click.ClickException(f"{pycyphal.dsdl.get_model(dtype)} is not a service type") from None
        request = pycyphal.dsdl.update_from_builtin(dtype.Request(), request_fields)
        _logger.info("Request object: %r", request)

        client = get_node().make_client(dtype, server_node_id, service_id)
        finalizers.append(client.close)
        client.response_timeout = timeout
        client.priority = priority

        get_node().start()
        await _run(client, request, formatter, with_metadata=with_metadata)
    finally:
        pycyphal.util.broadcast(finalizers[::-1])()


async def _run(
    client: pycyphal.presentation.Client[Any],
    request: Any,
    formatter: Formatter,
    with_metadata: bool,
) -> None:
    request_ts_transport: pycyphal.transport.Timestamp | None = None

    def on_transfer_feedback(fb: pycyphal.transport.Feedback) -> None:
        nonlocal request_ts_transport
        request_ts_transport = fb.first_frame_transmission_timestamp

    client.output_transport_session.enable_feedback(on_transfer_feedback)

    request_ts_application = pycyphal.transport.Timestamp.now()
    result = await client.call(request)
    response_ts_application = pycyphal.transport.Timestamp.now()
    if result is None:  # TODO this should exit with yakut.util.EXIT_CODE_UNSUCCESSFUL
        raise click.ClickException(f"The request has timed out after {client.response_timeout:0.1f} seconds")
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

    bi: dict[str, Any] = {}  # We use updates to ensure proper dict ordering: metadata before data
    if with_metadata:
        qnt = decimal.Decimal("0.000001")
        bi.update(
            convert_transfer_metadata_to_builtin(
                transfer,
                dtype=client.dtype,
                rtt=(transfer.timestamp.monotonic - request_ts_transport.monotonic).quantize(qnt),
            )
        )
    bi.update(pycyphal.dsdl.to_builtin(response))

    sys.stdout.write(formatter({client.port_id: bi}))
    sys.stdout.flush()


async def _resolve(
    raw_spec: str,
    server_node_id: int,
    node_provider: Callable[[], Node],
    *,
    response_timeout: float,
) -> tuple[int, Any]:
    """
    Decentralized discovery: if service-ID and type are given by the user, simply load the specified type and return.
    Otherwise we have to query the server node to find out the type and/or ID of the service.
    """
    specs = raw_spec.split(":")
    if not 1 <= len(specs) <= 2:
        click.BadParameter(f"Service specifier invalid: {raw_spec!r}")

    if len(specs) == 2:
        dtype = dtype_loader.load_dtype(specs[1])
        try:
            return int(specs[0]), dtype
        except ValueError:
            pass
        _logger.info(
            "Querying server node %r for service-ID information; locally specified type is %r", server_node_id, dtype
        )
        resolved = await _resolve_service_id_type(
            node_provider().presentation,
            specs[0],
            server_node_id,
            response_timeout=response_timeout,
        )
        if not resolved:
            raise click.ClickException(
                f"Could not resolve service {specs[0]!r} via node {server_node_id}. "
                f"The remote node might be offline or it may not support automatic discovery. "
                f"Consider specifying the service-ID and the data type explicitly?"
            )
        service_id, dtype_name_remote = resolved
        _logger.debug("Using locally specified type %r; server uses %r", dtype, dtype_name_remote)
        return service_id, dtype

    (ty_or_srv,) = specs
    del specs
    possibly_dtype_name = ty_or_srv.count(".") >= 1
    if possibly_dtype_name:
        try:
            dtype = dtype_loader.load_dtype(ty_or_srv)
        except dtype_loader.LoadError:
            pass
        else:
            fpid = pycyphal.dsdl.get_fixed_port_id(dtype)
            if fpid is None:
                raise click.ClickException(f"Type {pycyphal.dsdl.get_model(dtype)} does not have a fixed port-ID")
            _logger.info("Using type %r with its fixed port-ID %r (network discovery not required)", dtype, fpid)
            return fpid, dtype

    _logger.info("Heuristic: %r does not appear to be a type name, assuming it to be a port name", ty_or_srv)
    resolved = await _resolve_service_id_type(
        node_provider().presentation,
        ty_or_srv,
        server_node_id,
        response_timeout=response_timeout,
    )
    if not resolved:
        raise click.ClickException(
            f"Could not resolve service {ty_or_srv!r} via node {server_node_id}. "
            f"The remote node might be offline or it may not support automatic discovery. "
            f"Consider specifying the service-ID and the data type explicitly?"
        )
    service_id, dtype_name = resolved
    _logger.info("Resolved from server %r: id=%r dtype=%r", server_node_id, service_id, dtype_name)
    if dtype_name is None:
        raise click.ClickException(
            f"Remote node {server_node_id} does not provide data type information for service {ty_or_srv}, "
            f"nor is the type specified locally."
        )
    # When the type is obtained from remote node, allow the minor version to be different.
    return service_id, dtype_loader.load_dtype(dtype_name, allow_minor_version_mismatch=True)


async def _resolve_service_id_type(
    pres: pycyphal.presentation.Presentation,
    port_name: str,
    server_node_id: int,
    *,
    response_timeout: float,
) -> tuple[int, str | None] | None:
    from pycyphal.application.register import ValueProxy
    from uavcan.register import Access_1, Name_1

    c_access = pres.make_client_with_fixed_service_id(Access_1, server_node_id)
    try:
        c_access.response_timeout = response_timeout
        req = Access_1.Request(name=Name_1(f"uavcan.srv.{port_name}.id"))
        resp = await c_access(req)
        if resp is None:
            _logger.info("Request to %r has timed out: %s", server_node_id, req)
            return None
        assert isinstance(resp, Access_1.Response)
        port_id = int(ValueProxy(resp.value))
        if not 0 <= port_id <= pycyphal.transport.ServiceDataSpecifier.SERVICE_ID_MASK:
            _logger.debug("Service %r at node %r is not configured", port_name, server_node_id)
            return None

        req = Access_1.Request(name=Name_1(f"uavcan.srv.{port_name}.type"))
        resp = await c_access(req)
        if resp is None:
            _logger.info("Request to %r has timed out: %s", server_node_id, req)
            return None
        assert isinstance(resp, Access_1.Response)
        dtype_name = str(ValueProxy(resp.value)) if resp.value.string else None
    finally:
        c_access.close()
    return port_id, dtype_name
