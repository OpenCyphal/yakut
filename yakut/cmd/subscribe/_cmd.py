# Copyright (c) 2019 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

from __future__ import annotations
import sys
import math
import asyncio
from typing import Any, Sequence, TYPE_CHECKING, Callable, Iterable
import logging
from functools import lru_cache
import click
import pydsdl
import pycyphal
from pycyphal.transport import TransferFrom
from pycyphal.presentation import Subscriber
import yakut
from yakut.param.formatter import Formatter
from yakut.util import convert_transfer_metadata_to_builtin
from yakut.subject_specifier_processor import process_subject_specifier, SubjectResolver
from ._sync import Synchronizer, SynchronizerFactory
from ._sync_unary import make_sync_unary

if TYPE_CHECKING:
    import pycyphal.application

_logger = yakut.get_logger(__name__)

SYNC_MONOCLUST_TOLERANCE_MINMAX_TS_FIELD = 1e-6, 10.0
"""
Assume that externally provided timestamp is accurate at least for high-frequency topics.
"""

SYNC_MONOCLUST_TOLERANCE_MINMAX_TS_ARRIVAL = 0.02, 60.0
"""
A large minimum is needed due to low arrival timestamping accuracy.
This may be especially bad on Windows where the timestamping resolution may be as low as ~16 ms,
so the minimum tolerance should not be lower than that.
"""


class Config:
    def __init__(self) -> None:
        self._synchronizer_factory: SynchronizerFactory | None = None

    def set_synchronizer_factory(self, val: SynchronizerFactory) -> None:
        if self._synchronizer_factory is not None:
            raise click.UsageError("Cannot use more than one synchronizer")
        self._synchronizer_factory = val
        _logger.debug("Using synchronizer factory: %r", val)

    def get_synchronizer_factory(self) -> SynchronizerFactory:
        if self._synchronizer_factory is None:
            from ._sync_monoclust import make_sync_monoclust
            from pycyphal.presentation.subscription_synchronizer import get_local_reception_timestamp

            self.set_synchronizer_factory(
                lambda subs: make_sync_monoclust(
                    subs,
                    f_key=get_local_reception_timestamp,
                    tolerance_minmax=SYNC_MONOCLUST_TOLERANCE_MINMAX_TS_ARRIVAL,
                )
            )
        assert self._synchronizer_factory is not None
        return self._synchronizer_factory


def _has_field(model: pydsdl.CompositeType, name: str, type_full_name: str) -> bool:
    for field in model.fields:
        dt = field.data_type
        if field.name == name and isinstance(dt, pydsdl.CompositeType) and dt.full_name == type_full_name:
            return True
    return False


def _ensure_timestamp_field_synchronization_is_possible(model: pydsdl.CompositeType) -> None:
    if not _has_field(model, "timestamp", "uavcan.time.SynchronizedTimestamp"):
        raise click.ClickException(
            f"Synchronization on timestamp field is not possible for {model} because there is no such field. "
            f"Please use another synchronization policy or use only timestamped data types."
        )


def _handle_option_synchronizer_monoclust_timestamp_field(
    ctx: click.Context,
    _param: click.Parameter,
    value: float | None,
) -> None:
    if value is not None:
        from pycyphal.presentation.subscription_synchronizer import get_timestamp_field
        from ._sync_monoclust import make_sync_monoclust

        value = float(value)
        tol = SYNC_MONOCLUST_TOLERANCE_MINMAX_TS_FIELD if not math.isfinite(value) else (value, value)
        _logger.debug("Configuring field timestamp monoclust synchronizer with tolerance=%r", tol)

        def fac(subs: Iterable[Subscriber[Any]]) -> Synchronizer:
            subs = list(subs)
            for s in subs:
                _ensure_timestamp_field_synchronization_is_possible(pycyphal.dsdl.get_model(s.dtype))
            return make_sync_monoclust(subs, f_key=get_timestamp_field, tolerance_minmax=tol)

        ctx.ensure_object(Config).set_synchronizer_factory(fac)


def _handle_option_synchronizer_monoclust_timestamp_arrival(
    ctx: click.Context,
    _param: click.Parameter,
    value: float | None,
) -> None:
    if value is not None:
        from pycyphal.presentation.subscription_synchronizer import get_local_reception_timestamp
        from ._sync_monoclust import make_sync_monoclust

        value = float(value)
        tol = SYNC_MONOCLUST_TOLERANCE_MINMAX_TS_ARRIVAL if not math.isfinite(value) else (value, value)
        _logger.debug("Configuring arrival timestamp monoclust synchronizer; tolerance=%r", tol)
        ctx.ensure_object(Config).set_synchronizer_factory(
            lambda subs: make_sync_monoclust(subs, f_key=get_local_reception_timestamp, tolerance_minmax=tol)
        )


def _handle_option_synchronizer_transfer_id(ctx: click.Context, _param: click.Parameter, value: bool) -> None:
    if value:
        from ._sync_transfer_id import make_sync_transfer_id

        _logger.debug("Configuring transfer-ID synchronizer")
        ctx.ensure_object(Config).set_synchronizer_factory(make_sync_transfer_id)


@yakut.subcommand(aliases="sub")
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
@click.option(
    "--redraw",
    "--no-scroll",
    "-R",
    is_flag=True,
    help="Clear terminal output before printing output. This option only has effect if stdout is a tty.",
)
@click.option(
    "--sync-monoclust",
    "--sync-mc",
    callback=_handle_option_synchronizer_monoclust_timestamp_field,
    expose_value=False,
    type=float,
    is_flag=False,
    flag_value=float("nan"),
    help=f"""
Use the monotonic clustering synchronizer with the message timestamp field as the clustering key.
All data types shall be timestamped for this to work.
The optional value is the synchronization tolerance in seconds; autodetect if not specified.
""",
)
@click.option(
    "--sync-monoclust-arrival",
    "--sync-mca",
    callback=_handle_option_synchronizer_monoclust_timestamp_arrival,
    expose_value=False,
    type=float,
    is_flag=False,
    flag_value=float("nan"),
    help=f"""
Use the monotonic clustering synchronizer with the local arrival timestamp as the clustering key.
Works with all data types but may perform poorly depending on the timing and system latency.
The optional value is the synchronization tolerance in seconds; autodetect if not specified.
""",
)
@click.option(
    "--sync-transfer-id",
    "--sync-tid",
    callback=_handle_option_synchronizer_transfer_id,
    expose_value=False,
    is_flag=True,
    help=f"""
Use the transfer-ID synchronizer.
Messages that originate from the same node AND share the same transfer-ID will be grouped together.
""",
)
@yakut.pass_purser
@yakut.asynchronous(interrupted_ok=True)
async def subscribe(
    purser: yakut.Purser,
    subject: tuple[str, ...],
    with_metadata: bool,
    count: int | None,
    redraw: bool,
) -> None:
    """
    Subscribe to specified subjects and print messages to stdout.
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
    If no synchronizer is specified, Yakut will choose one automatically.

    Each received object or synchronized group is emitted to stdout as a key-value mapping,
    where the number of elements equals the number of subjects the command is asked to subscribe to;
    the keys are subject-IDs and values are the received message objects.

    Examples:

    \b
        yakut sub 33:uavcan.si.unit.angle.Scalar --with-metadata --count=1
        yakut sub 33 42 5789 --sync-monoclust-arrival=0.1
        yakut sub uavcan.node.Heartbeat
    """
    config = click.get_current_context().ensure_object(Config)
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
        if len(subscribers) > 1:
            synchronizer = config.get_synchronizer_factory()(subscribers)
        elif len(subscribers) == 1:
            synchronizer = make_sync_unary([subscribers[0]])
        else:
            _logger.warning("Nothing to do because no subjects are specified")
            return

        # The node is closed through the finalizers at exit.
        # Note that we can't close the node before closing the subscribers to avoid resource errors inside PyCyphal.
        node = get_node()
        if node.id is not None:
            _logger.info("It is recommended to use an anonymous node with this command")
        node.start()
        try:
            await _run(synchronizer, formatter, with_metadata=with_metadata, count=count, redraw=redraw)
        finally:
            if _logger.isEnabledFor(logging.INFO):
                _logger.info("%s", node.presentation.transport.sample_statistics())
                for sub in subscribers:
                    _logger.info("% 4s: %s", sub.port_id, sub.sample_statistics())
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


async def _run(synchronizer: Synchronizer, formatter: Formatter, with_metadata: bool, count: int, redraw: bool) -> None:
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

    def process_group(group: tuple[tuple[tuple[Any, TransferFrom], Subscriber[Any]], ...]) -> None:
        nonlocal count
        outer: dict[int, dict[str, Any]] = {}
        # noinspection PyTypeChecker
        for (msg, meta), subscriber in group:
            assert isinstance(meta, TransferFrom) and isinstance(subscriber, Subscriber)
            bi: dict[str, Any] = {}  # We use updates to ensure proper dict ordering: metadata before data
            if with_metadata:
                bi.update(convert_transfer_metadata_to_builtin(meta, **get_extra_metadata(subscriber)))
            bi.update(pycyphal.dsdl.to_builtin(msg))
            outer[subscriber.port_id] = bi

        if redraw:
            click.clear()
        print(formatter(outer))  # Use print to properly handle end-of-line for both TTY and files on all platforms
        count -= 1
        if count <= 0:
            _logger.debug("Reached the specified synchronized group count, stopping")
            raise _Break

    try:
        await synchronizer(process_group)
    except _Break:
        pass


class _Break(Exception):
    pass
