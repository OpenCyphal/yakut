# Copyright (c) 2019 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

from __future__ import annotations
import typing
import inspect
import logging
import pyuavcan
from pyuavcan.transport import Transport as Transport
import click
from yakut.paths import OUTPUT_TRANSFER_ID_MAP_DIR, OUTPUT_TRANSFER_ID_MAP_MAX_AGE


TransportFactory = typing.Callable[[], typing.Optional[Transport]]
"""
The result is None if no transport configuration was provided when invoking the command.
"""

_logger = logging.getLogger(__name__)


def transport_factory_option(f: typing.Callable[..., typing.Any]) -> typing.Callable[..., typing.Any]:
    def validate(ctx: click.Context, param: object, value: typing.Optional[str]) -> TransportFactory:
        _ = ctx, param
        _logger.debug("Transport expression: %r", value)

        def factory() -> typing.Optional[Transport]:
            # Try constructing from the expression if provided:
            if value:
                try:
                    result = construct_transport(value)
                except Exception as ex:
                    raise click.BadParameter(f"Could not initialize transport {value!r}: {ex!r}") from ex
                _logger.info("Transport %r constructed from expression %r", result, value)
                return result
            # If no expression is given, construct from the registers passed via environment variables:
            try:
                from pyuavcan.application import make_transport
                from pyuavcan.application.register import parse_environment_variables
            except (ImportError, AttributeError):
                _logger.info(
                    "Transport initialization expression is not provided and constructing the transport "
                    "from registers is not possible because the standard DSDL namespace is not compiled"
                )
                return None
            registers = parse_environment_variables()
            result = make_transport(registers)
            if result is not None:
                _logger.info("Transport %r constructed from registers %r", result, list(registers))
            return result

        return factory

    doc = f"""
Override the network interface configuration, including the local node-ID.
This option is only relevant for commands that access the network, like pub/sub/call/etc.; other commands ignore it.

By default, if this option is not given (neither via --transport nor YAKUT_TRANSPORT),
commands that access the network deduce the transport configuration from standard registers passed via
environment variables, such as UAVCAN__NODE__ID__NATURAL16, UAVCAN__UDP__IP__STRING, UAVCAN__SERIAL__PORT__STRING,
and so on.
The full list of the registers that configure the transport is available in the documentation for PyUAVCAN:
https://pyuavcan.readthedocs.io, "make_transport()".
However, this method requires that the standard DSDL namespace "uavcan" is compiled (see command "yakut compile").

If this expression is given, the registers are ignored, and the transport instance is constructed by evaluating it.
Upon evaluation, the expression should yield either a single transport instance or a sequence thereof.
In the latter case, the multiple transports will be joined under the same redundant transport instance,
which may be heterogeneous (e.g., UDP+Serial).
This method does not require any DSDL to be compiled at all.

To see supported transports and how they should be initialized, run `yakut doc`.
Also, read the PyUAVCAN documentation at https://pyuavcan.readthedocs.io.

The expression does not need to explicitly reference the `pyuavcan.transport` module
because its contents are wildcard-imported for convenience.
Further, when specifying a transport class, the suffix `Transport` may be omitted;
e.g., `UDPTransport` and `UDP` are equivalent.

Examples showcasing loopback, CAN, and heterogeneous UDP+Serial:

\b
    Loopback(None)
    CAN(can.media.socketcan.SocketCANMedia('vcan0',64),42)
    UDP('127.42.0.123',None),Serial("/dev/ttyUSB0",None)

To avoid issues caused by resetting the transfer-ID counters between invocations,
the tool stores the output transfer-ID map on disk keyed by the node-ID.
On this computer, the path is `{OUTPUT_TRANSFER_ID_MAP_DIR}`.
The map files can be removed to reset all transfer-ID counters to zero.
Files that are more than {OUTPUT_TRANSFER_ID_MAP_MAX_AGE} seconds old are not used.
"""
    f = click.option(
        "--transport",
        "-i",
        "transport_factory",
        envvar="YAKUT_TRANSPORT",
        type=str,
        metavar="EXPRESSION",
        callback=validate,
        help=doc,
    )(f)
    return f


def construct_transport(expression: str) -> Transport:
    context = _make_evaluation_context()
    trs = _evaluate_transport_expr(expression, context)
    _logger.debug("Transport expression evaluation result: %r", trs)
    if len(trs) == 1:
        return trs[0]  # Non-redundant transport
    if len(trs) > 1:
        from pyuavcan.transport.redundant import RedundantTransport

        rt = RedundantTransport()
        for t in trs:
            rt.attach_inferior(t)
        assert rt.inferiors == trs
        return rt
    raise ValueError("No transports specified")


def _evaluate_transport_expr(expression: str, context: typing.Dict[str, typing.Any]) -> typing.List[Transport]:
    out = eval(expression, context)  # pylint: disable=eval-used
    if isinstance(out, Transport):
        return [out]
    if isinstance(out, (list, tuple)) and all(isinstance(x, Transport) for x in out):
        return list(out)
    raise ValueError(
        f"The expression {expression!r} yields an instance of {type(out).__name__!r}. "
        f"Expected an instance of pyuavcan.transport.Transport or a list thereof."
    )


def _make_evaluation_context() -> typing.Dict[str, typing.Any]:
    import os

    def handle_import_error(parent_module_name: str, ex: ImportError) -> None:
        try:
            tr = parent_module_name.split(".")[2]
        except LookupError:
            tr = parent_module_name
        _logger.debug("Transport %r is not available due to the missing dependency %r", tr, ex.name)

    # This import is super slow, so we do it as late as possible.
    # Doing this when generating command-line arguments would be disastrous for performance.
    # noinspection PyTypeChecker
    pyuavcan.util.import_submodules(pyuavcan.transport, error_handler=handle_import_error)

    # Populate the context with all references that may be useful for the transport expression.
    context: typing.Dict[str, typing.Any] = {
        "pyuavcan": pyuavcan,
        "os": os,
    }

    # Expose pre-imported transport modules for convenience.
    for name, module in inspect.getmembers(pyuavcan.transport, inspect.ismodule):
        if not name.startswith("_"):
            context[name] = module

    # Pre-import transport classes.
    for cls in pyuavcan.util.iter_descendants(Transport):
        if not cls.__name__.startswith("_") and cls is not Transport:
            name = cls.__name__.rpartition(Transport.__name__)[0]
            assert name
            context[name] = cls
            context[cls.__name__] = cls

    _logger.debug("Transport expression evaluation context (on the next line):\n%r", context)
    return context
