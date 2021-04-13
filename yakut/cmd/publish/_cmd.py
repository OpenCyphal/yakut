# Copyright (c) 2021 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

from __future__ import annotations
import math
from typing import Tuple, List, Sequence, Callable, Any, Dict, TYPE_CHECKING
import logging
import functools
import contextlib
import click
import pyuavcan
import yakut
from yakut.helpers import EnumParam
from yakut.yaml import EvaluableLoader
from yakut.util import construct_port_id_and_type
from ._executor import Executor, Publication

_MIN_SEND_TIMEOUT = 0.1
"""
With a slow garbage-collected language like Python, having a smaller timeout does not make practical sense.
This may be made configurable later.
"""

_logger = yakut.get_logger(__name__)


def _validate_message_spec(
    ctx: click.Context,
    param: click.Parameter,
    value: Tuple[str, ...],
) -> List[Tuple[str, str]]:
    if len(value) % 2 != 0:
        raise click.BadParameter(
            f"Message specifier shall have an even number of paired arguments (found {len(value)} arguments)",
            ctx=ctx,
            param=param,
        )
    return [(s, f) for s, f in (value[i : i + 2] for i in range(0, len(value), 2))]  # pylint: disable=R1721


@yakut.subcommand()
@click.argument(
    "message",
    type=str,
    callback=_validate_message_spec,
    metavar="SUBJECT FIELDS [SUBJECT FIELDS]...",
    nargs=-1,
)
@click.option(
    "--period",
    "-T",
    type=float,
    default=1.0,
    show_default=True,
    metavar="SECONDS",
    help=f"""
Message publication period.
All messages are published synchronously, so the period setting applies to all specified subjects.
The send timeout equals the period as long as it is not less than {_MIN_SEND_TIMEOUT} seconds.
""",
)
@click.option(
    "--count",
    "-N",
    type=int,
    default=1,
    show_default=True,
    metavar="CARDINAL",
    help=f"Number of publication cycles before exiting normally.",
)
@click.option(
    "--priority",
    "-P",
    default=pyuavcan.presentation.DEFAULT_PRIORITY,
    type=EnumParam(pyuavcan.transport.Priority),
    help=f"Priority of published message transfers. [default: {pyuavcan.presentation.DEFAULT_PRIORITY.name}]",
)
@yakut.pass_purser
def publish(
    purser: yakut.Purser,
    message: Sequence[Tuple[str, str]],
    period: float,
    count: int,
    priority: pyuavcan.transport.Priority,
) -> None:
    """
    Publish messages on the specified subjects.
    Unless the local transport is configured in anonymous node,
    the local node will also publish on standard subjects like Heartbeat and provide some standard RPC-services
    like GetInfo.

    The command accepts a list of space-separated pairs like:

    \b
        [SUBJECT_ID:]TYPE_NAME.MAJOR.MINOR  YAML_FIELDS

    The first element is a name like `uavcan.node.Heartbeat.1.0` prepended by the subject-ID.
    The subject-ID may be omitted if a fixed one is defined for the data type.

    The second element specifies the values of the message fields in YAML format (or JSON, which is a subset of YAML).
    Missing fields will be left at their default values;
    therefore, to publish a default-initialized message, the field specifier should be an empty dict: `{}`.
    For more info about the format see PyUAVCAN documentation on builtin-based representations.

    The number of such pairs can be arbitrary; all defined messages will be published synchronously.
    If no such pairs are specified, only the heartbeat will be published, unless the local node is anonymous.

    Forward or backward slashes can be used instead of ".";
    version numbers can be also separated using underscores.
    This is done to allow the user to rely on filesystem autocompletion when typing the command.

    Examples:

    \b
        yakut pub uavcan.diagnostic.Record.1.1 '{text: "Hello world!", severity: {value: 4}}' -N3 -T0.1 -P hi
        yakut pub 33:uavcan/si/unit/angle/Scalar_1_0 'radian: 2.31' uavcan.diagnostic.Record.1.1 'text: "2.31 rad"'
    """
    try:
        from pyuavcan.application import Node
    except ImportError as ex:
        from yakut.cmd.compile import make_usage_suggestion

        raise click.UsageError(make_usage_suggestion(ex.name))

    _logger.debug("period=%s, count=%s, priority=%s, message=%s", period, count, priority, message)
    assert all((isinstance(a, str) and isinstance(b, str)) for a, b in message)
    assert isinstance(period, float) and isinstance(count, int) and isinstance(priority, pyuavcan.transport.Priority)
    if period < 1e-9 or not math.isfinite(period):
        raise click.BadParameter("Period shall be a positive real number of seconds")
    if count <= 0:
        _logger.info("Nothing to do because count=%s", count)
        return

    send_timeout = max(_MIN_SEND_TIMEOUT, period)
    loader = EvaluableLoader(_get_user_expression_evaluation_context())

    def make_publication_factory(
        subject_spec: str, field_spec: str
    ) -> Callable[[pyuavcan.presentation.Presentation], Publication]:
        subject_id, dtype = construct_port_id_and_type(subject_spec)
        # Catch errors as early as possible.
        if issubclass(dtype, pyuavcan.dsdl.ServiceObject):
            raise click.BadParameter(f"Subject spec {subject_spec!r} refers to a service type")
        # noinspection PyTypeChecker
        if subject_id is None and pyuavcan.dsdl.get_fixed_port_id(dtype) is None:
            raise click.UsageError(
                f"Subject-ID is not provided and {pyuavcan.dsdl.get_model(dtype)} does not have a fixed one"
            )
        try:
            evaluator = loader.load_unevaluated(field_spec)
        except ValueError as ex:
            raise click.BadParameter(f"Invalid field spec {field_spec!r}: {ex}") from None
        _logger.debug("Publication spec appears valid: %r", subject_spec)
        return lambda presentation: Publication(
            subject_id=subject_id,
            dtype=dtype,
            evaluator=evaluator,
            presentation=presentation,
            priority=priority,
            send_timeout=send_timeout,
        )

    # This is to perform as much processing as possible before constructing the node.
    # Catching errors early allows us to avoid disturbing the network and peripherals unnecessarily.
    publication_factories = [make_publication_factory(*m) for m in message]

    node = purser.get_node("publish", allow_anonymous=True)
    executor = Executor(
        node=node,
        loader=loader,
        publications=(f(node.presentation) for f in publication_factories),
    )
    with contextlib.closing(executor):
        _logger.info(
            "Publishing %d subjects with period %.3fs, send timeout %.3fs, count %d, priority %s",
            len(publication_factories),
            period,
            send_timeout,
            count,
            priority.name,
        )
        # Even if the publication set is empty, we still have to publish the heartbeat.
        try:
            executor.run(count=count, period=period)
        finally:
            if _logger.isEnabledFor(logging.INFO):
                _logger.info("%s", node.presentation.transport.sample_statistics())
                for s in node.presentation.transport.output_sessions:
                    ds = s.specifier.data_specifier
                    if isinstance(ds, pyuavcan.transport.MessageDataSpecifier):
                        _logger.info("Subject %d: %s", ds.subject_id, s.sample_statistics())


@functools.lru_cache(None)
def _get_user_expression_evaluation_context() -> Dict[str, Any]:
    import os
    import math
    import time
    import random
    import inspect

    modules = [
        (random, True),
        (time, True),
        (math, True),
        (os, False),
        (pyuavcan, False),
    ]

    out: Dict[str, Any] = {}
    for mod, wildcard in modules:
        out[mod.__name__] = mod
        if wildcard:
            out.update(
                {name: member for name, member in inspect.getmembers(mod) if not name.startswith("_")},
            )

    _logger.debug("Expression context contains %d items (on the next line):\n%s", len(out), list(out))
    return out
