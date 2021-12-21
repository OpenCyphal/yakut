# Copyright (c) 2019 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

import sys
import typing
import logging
import contextlib
import click
import pyuavcan
from pyuavcan.presentation import Presentation, Subscriber
import yakut
from yakut.param.formatter import Formatter
from yakut.util import convert_transfer_metadata_to_builtin, construct_port_id_and_type


_M = typing.TypeVar("_M", bound=pyuavcan.dsdl.CompositeObject)


_logger = yakut.get_logger(__name__)


@yakut.subcommand()
@click.argument("subject", type=str, nargs=-1)
@click.option(
    "--with-metadata/--no-metadata",
    "+M/-M",
    default=True,
    show_default=True,
    help="When enabled, each message object is prepended with an extra field named `_metadata_`.",
)
@click.option(
    "--count",
    "-N",
    type=int,
    metavar="CARDINAL",
    help=f"""
Exit automatically after this many messages (or synchronous message groups) have been received. No limit by default.
""",
)
@yakut.pass_purser
@yakut.asynchronous
async def subscribe(
    purser: yakut.Purser,
    subject: typing.Tuple[str, ...],
    with_metadata: bool,
    count: typing.Optional[int],
) -> None:
    """
    Subscribe to specified subjects and print messages into stdout.
    This command does not instantiate a local node and does not disturb the network in any way,
    so many instances can be cheaply executed concurrently.
    It is recommended to use anonymous transport (i.e., without a node-ID).

    The arguments are a list of message data type names prepended with the subject-ID;
    the subject-ID may be omitted if the data type defines a fixed one:

    \b
        [SUBJECT_ID:]TYPE_NAME.MAJOR.MINOR

    If multiple subjects are specified, a synchronous subscription will be used.
    It is useful for subscribing to a group of coupled subjects like lockstep sensor feeds,
    but it will not work for subjects that are temporally unrelated or published at different rates.

    Each object emitted into stdout is a key-value mapping where the number of elements equals the number
    of subjects the command is asked to subscribe to;
    the keys are subject-IDs and values are the received message objects.

    In data type names forward or backward slashes can be used instead of ".";
    version numbers can be also separated using underscores.
    This is done to allow the user to rely on filesystem autocompletion when typing the command.

    Examples:

    \b
        yakut sub 33:uavcan.si.unit.angle.Scalar.1.0 --no-metadata
    """
    _logger.debug("subject=%r, with_metadata=%r, count=%r", subject, with_metadata, count)
    if not subject:
        _logger.info("Nothing to do because no subjects are specified")
        return
    if count is not None and count <= 0:
        _logger.info("Nothing to do because count=%s", count)
        return

    count = count if count is not None else sys.maxsize
    formatter = purser.make_formatter()

    transport = purser.get_transport()
    if transport.local_node_id is not None:
        _logger.info("It is recommended to use an anonymous transport with this command.")

    with contextlib.closing(Presentation(transport)) as presentation:
        subscriber = _make_subscriber(subject, presentation)
        try:
            await _run(subscriber, formatter, with_metadata=with_metadata, count=count)
        finally:
            if _logger.isEnabledFor(logging.INFO):
                _logger.info("%s", presentation.transport.sample_statistics())
                _logger.info("%s", subscriber.sample_statistics())


def _make_subscriber(subjects: typing.Sequence[str], presentation: Presentation) -> Subscriber[_M]:
    group = [construct_port_id_and_type(ds) for ds in subjects]
    assert len(group) > 0
    if len(group) == 1:
        ((subject_id, dtype),) = group
        return presentation.make_subscriber(dtype, subject_id)
    raise NotImplementedError(
        "Multi-subject subscription is not yet implemented. See https://github.com/UAVCAN/pyuavcan/issues/65"
    )


async def _run(subscriber: Subscriber[_M], formatter: Formatter, with_metadata: bool, count: int) -> None:
    async for msg, transfer in subscriber:
        assert isinstance(transfer, pyuavcan.transport.TransferFrom)
        outer: typing.Dict[int, typing.Dict[str, typing.Any]] = {}

        bi: typing.Dict[str, typing.Any] = {}  # We use updates to ensure proper dict ordering: metadata before data
        if with_metadata:
            bi.update(convert_transfer_metadata_to_builtin(transfer))
        bi.update(pyuavcan.dsdl.to_builtin(msg))
        outer[subscriber.port_id] = bi

        print(formatter(outer))

        count -= 1
        if count <= 0:
            _logger.debug("Reached the specified message count, stopping")
            break
