# Copyright (c) 2019 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

from __future__ import annotations
import sys
import asyncio
from typing import Any, Sequence, TYPE_CHECKING, Callable, Iterable
import logging
from functools import lru_cache
import click
import pycyphal
from pycyphal.presentation import Subscriber, subscription_synchronizer
import yakut
from yakut.param.formatter import Formatter
from yakut.util import convert_transfer_metadata_to_builtin
from yakut.subject_specifier_processor import process_subject_specifier, SubjectResolver

if TYPE_CHECKING:
    import pycyphal.application

_logger = yakut.get_logger(__name__)


@yakut.subcommand()
@click.argument("subject", type=str, nargs=-1)
@click.option(
    "--with-metadata/--no-metadata",
    "+M/-M",
    default=False,
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
    subject: tuple[str, ...],
    with_metadata: bool,
    count: int | None,
) -> None:
    """
    Subscribe to specified subjects and print messages into stdout.
    It is recommended to make this node anonymous (i.e., without a node-ID)
    to avoid additional traffic on the network from this tool.

    The arguments are a list of message data type names prepended with the subject-ID;
    the subject-ID may be omitted if the data type defines a fixed one;
    or the type can be omitted to engage automatic type discovery
    (discovery may fail if the local node is anonymous as it will be unable to issue RPC-service requests).
    The accepted forms are:

    \b
        SUBJECT_ID:TYPE_NAME[.MAJOR[.MINOR]]
        TYPE_NAME[.MAJOR[.MINOR]]
        SUBJECT_ID

    If multiple subjects are specified, a synchronous subscription will be used.
    It is intended for subscribing to a group of coupled subjects like lockstep sensor feeds or other coupled objects.
    More on subscription synchronization is available in the PyCyphal docs.

    Each received object or synchronized group is emitted to stdout as a key-value mapping,
    where the number of elements equals the number of subjects the command is asked to subscribe to;
    the keys are subject-IDs and values are the received message objects.

    Examples:

    \b
        yakut sub 33:uavcan.si.unit.angle.Scalar --with-metadata --count=1
        yakut sub 33 42 5789
        yakut sub uavcan.node.Heartbeat
    """
    try:
        from pycyphal.application import Node
    except ImportError as ex:
        from yakut.cmd.compile import make_usage_suggestion

        raise click.ClickException(make_usage_suggestion(ex.name))

    finalizers: list[Callable[[], None]] = []
    try:
        _logger.debug("subject=%r, with_metadata=%r, count=%r", subject, with_metadata, count)
        if count is not None and count <= 0:
            _logger.warning("Nothing to do because count=%s", count)
            return

        count = count if count is not None else sys.maxsize
        formatter = purser.make_formatter()

        # Node construction should be delayed as much as possible to avoid unnecessary interference
        # with the bus and hardware. This is why we use the factory here instead of constructing the node eagerly.
        @lru_cache(None)
        def get_node() -> Node:
            node = purser.get_node("subscribe", allow_anonymous=True)
            finalizers.append(node.close)
            return node

        subscribers: list[Subscriber[Any]] = await _make_subscribers(subject, get_node)
        finalizers += [s.close for s in subscribers]

        synchronizer: subscription_synchronizer.Synchronizer
        if len(subscribers) == 0:
            _logger.warning("Nothing to do because no subjects are specified")
            return
        if len(subscribers) == 1:
            synchronizer = _UnarySynchronizer(subscribers[0])
        else:
            # TODO FIXME parameterize synchronizer instantiation; automatic tolerance
            from pycyphal.presentation.subscription_synchronizer import monotonic_clustering

            synchronizer = monotonic_clustering.MonotonicClusteringSynchronizer(
                subscribers, subscription_synchronizer.get_local_reception_timestamp, 1.0
            )
        finalizers.append(synchronizer.close)

        with get_node() as node:
            if node.id is not None:
                _logger.info("It is recommended to use an anonymous node with this command")
            try:
                await _run(synchronizer, formatter, with_metadata=with_metadata, count=count)
            finally:
                if _logger.isEnabledFor(logging.INFO):
                    _logger.info("%s", node.presentation.transport.sample_statistics())
                    for sub in subscribers:
                        _logger.info("% 4s: %s", sub.port_id, sub.sample_statistics())
                synchronizer.close()
    finally:
        pycyphal.util.broadcast(finalizers[::-1])()
        await asyncio.sleep(0.1)  # let background tasks finalize before leaving the loop


async def _make_subscribers(
    specifiers: Sequence[str],
    node_provider: Callable[[], "pycyphal.application.Node"],
) -> list[Subscriber[Any]]:
    subject_resolver: SubjectResolver | None = None

    def get_resolver() -> SubjectResolver:
        nonlocal subject_resolver
        if subject_resolver is None:
            node = node_provider()
            if node.id is None:
                raise click.ClickException(
                    f"Cannot use automatic discovery because the local node is anonymous, "
                    f"so it cannot access the introspection services on remote nodes. "
                    f"You need to either fully specify the subjects explicitly or assign a local node-ID."
                )
            subject_resolver = SubjectResolver(node)
        return subject_resolver

    try:
        id_types = [await process_subject_specifier(ds, get_resolver) for ds in specifiers]
        # Construct the node only after we have verified that the specifiers are valid and dtypes/ids are resolved.
        return [node_provider().make_subscriber(dtype, subject_id) for subject_id, dtype in id_types]
    finally:
        if subject_resolver:
            subject_resolver.close()


async def _run(
    synchronizer: subscription_synchronizer.Synchronizer,
    formatter: Formatter,
    with_metadata: bool,
    count: int,
) -> None:
    metadata_cache: dict[object, dict[str, Any]] = {}

    def get_extra_metadata(sub: Subscriber[Any]) -> dict[str, Any]:
        try:
            return metadata_cache[sub]
        except LookupError:  # This may be expensive so we only do it once.
            model = pycyphal.dsdl.get_model(sub.dtype)
            metadata_cache[sub] = {
                "dtype": str(model),
            }
        return metadata_cache[sub]

    async for synchronized_group in synchronizer:
        outer: dict[int, dict[str, Any]] = {}
        # noinspection PyTypeChecker
        for (msg, meta), subscriber in synchronized_group:
            assert isinstance(meta, pycyphal.transport.TransferFrom) and isinstance(subscriber, Subscriber)
            bi: dict[str, Any] = {}  # We use updates to ensure proper dict ordering: metadata before data
            if with_metadata:
                bi.update(convert_transfer_metadata_to_builtin(meta, **get_extra_metadata(subscriber)))
            bi.update(pycyphal.dsdl.to_builtin(msg))
            outer[subscriber.port_id] = bi

        sys.stdout.write(formatter(outer))
        sys.stdout.write("\r\n")
        sys.stdout.flush()
        count -= 1
        if count <= 0:
            _logger.debug("Reached the specified synchronized group count, stopping")
            break


class _UnarySynchronizer(subscription_synchronizer.Synchronizer):  # type: ignore
    def __init__(self, subscriber: Subscriber[Any]) -> None:
        super().__init__([subscriber])

    async def receive_for(self, timeout: float) -> tuple[tuple[Any, pycyphal.transport.TransferFrom], ...] | None:
        res = await self._subscribers[0].receive_for(timeout)
        return (res,) if res is not None else None

    def receive_in_background(self, handler: Callable[..., None]) -> None:
        raise NotImplementedError("Just read the instructions")
