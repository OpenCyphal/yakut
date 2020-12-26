# Copyright (c) 2019 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

from __future__ import annotations
import math
import typing
import asyncio
import logging
import contextlib
import click
import pyuavcan
import u
from u.yaml import YAMLLoader
from u.helpers import EnumParam


_MIN_SEND_TIMEOUT = 0.1
"""
With a slow garbage-collected language like Python, having a smaller timeout does not make practical sense.
This may be made configurable later.
"""

_logger = logging.getLogger(__name__)


def _validate_message_spec(
    ctx: click.Context,
    param: click.Parameter,
    value: typing.Tuple[str, ...],
) -> typing.List[typing.Tuple[str, str]]:
    if len(value) % 2 != 0:
        raise click.BadParameter(
            f"Message specifier shall have an even number of paired arguments (found {len(value)} arguments)",
            ctx=ctx,
            param=param,
        )
    # noinspection PyTypeChecker
    return [value[i : i + 2] for i in range(0, len(value), 2)]


@u.subcommand()
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
@u.pass_purser
def publish(
    purser: u.Purser,
    message: typing.Sequence[typing.Tuple[str, str]],
    period: float,
    count: int,
    priority: pyuavcan.transport.Priority,
) -> None:
    """
    Publish messages on the specified subjects.
    The local node will also publish heartbeat and respond to GetInfo, unless it is configured to be anonymous.

    The command accepts a list of space-separated pairs like:

    \b
        [SUBJECT_ID.]TYPE_NAME.MAJOR.MINOR  YAML_FIELDS

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
        u pub uavcan.diagnostic.Record.1.1 '{text: "Hello world!", severity: {value: 4}}' -N3 -T0.1 -P hi
        u pub 33.uavcan/si/unit/angle/Scalar_1_0 'radian: 2.31' uavcan.diagnostic.Record.1.1 'text: "2.31 rad"'
    """
    try:
        import pyuavcan.application
    except ImportError as ex:
        from u.cmd import compile

        raise click.UsageError(compile.make_usage_suggestion(ex.name))

    _logger.debug("period=%s, count=%s, priority=%s, message=%s", period, count, priority, message)
    assert all((isinstance(a, str) and isinstance(b, str)) for a, b in message)
    assert isinstance(period, float) and isinstance(count, int) and isinstance(priority, pyuavcan.transport.Priority)
    if period < 1e-9 or not math.isfinite(period):
        raise click.BadParameter("Period shall be a positive real number of seconds")
    if count <= 0:
        _logger.info("Nothing to do because count=%s", count)
        return

    send_timeout = max(_MIN_SEND_TIMEOUT, period)
    node = purser.get_node("publish", allow_anonymous=True)
    assert isinstance(node, pyuavcan.application.Node)
    with contextlib.closing(node):
        publications = [
            Publication(
                subject_spec=subj,
                field_spec=fields,
                presentation=node.presentation,
                priority=priority,
                send_timeout=send_timeout,
            )
            for subj, fields in message
        ]
        if _logger.isEnabledFor(logging.INFO):
            _logger.info(
                "Ready to start publishing with period %.3fs, send timeout %.3fs, count %d, at %s:\n%s",
                period,
                send_timeout,
                count,
                priority,
                "\n".join(map(str, publications)) or "<nothing>",
            )
        try:  # Even if the publication set is empty, we still have to publish the heartbeat.
            _run(node, count=count, period=period, publications=publications)
        finally:
            if _logger.isEnabledFor(logging.INFO):
                _logger.info("%s", node.presentation.transport.sample_statistics())
                for s in node.presentation.transport.output_sessions:
                    ds = s.specifier.data_specifier
                    if isinstance(ds, pyuavcan.transport.MessageDataSpecifier):
                        _logger.info("Subject %d: %s", ds.subject_id, s.sample_statistics())


@u.asynchronous
async def _run(node: object, count: int, period: float, publications: typing.Sequence[Publication]) -> None:
    import pyuavcan.application

    assert isinstance(node, pyuavcan.application.Node)
    node.start()

    sleep_until = asyncio.get_event_loop().time()
    for c in range(count):
        out = await asyncio.gather(*[p.publish() for p in publications])
        assert len(out) == len(publications)
        assert all(isinstance(x, bool) for x in out)
        if not all(out):
            timed_out = [publications[idx] for idx, res in enumerate(out) if not res]
            _logger.error("The following publications have timed out:\n" + "\n".join(map(str, timed_out)))

        sleep_until += period
        sleep_duration = sleep_until - asyncio.get_event_loop().time()
        _logger.info("Published group %6d of %6d; sleeping for %.3f seconds", c + 1, count, sleep_duration)
        await asyncio.sleep(sleep_duration)


class Publication:
    _YAML_LOADER = YAMLLoader()

    def __init__(
        self,
        subject_spec: str,
        field_spec: str,
        presentation: pyuavcan.presentation.Presentation,
        priority: pyuavcan.transport.Priority,
        send_timeout: float,
    ):
        from u.util import construct_port_id_and_type

        subject_id, dtype = construct_port_id_and_type(subject_spec)
        content = self._YAML_LOADER.load(field_spec)

        self._message = pyuavcan.dsdl.update_from_builtin(dtype(), content)
        self._publisher = presentation.make_publisher(dtype, subject_id)
        self._publisher.priority = priority
        self._publisher.send_timeout = send_timeout

    async def publish(self) -> bool:
        return await self._publisher.publish(self._message)

    def __repr__(self) -> str:
        return pyuavcan.util.repr_attributes(self, self._message, self._publisher)
