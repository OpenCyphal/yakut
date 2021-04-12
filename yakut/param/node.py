# Copyright (c) 2019 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

from __future__ import annotations
import os
import re
import time
import atexit
import pickle
import typing
import logging
import pathlib
import dataclasses
import click
import pyuavcan
from pyuavcan.transport import Transport, OutputSessionSpecifier, Priority
from pyuavcan.presentation import OutgoingTransferIDCounter
import yakut
from yakut.paths import OUTPUT_TRANSFER_ID_MAP_DIR, OUTPUT_TRANSFER_ID_MAP_MAX_AGE
from yakut.helpers import EnumParam

if typing.TYPE_CHECKING:
    import pyuavcan.application  # pylint: disable=ungrouped-imports

_logger = logging.getLogger(__name__)


@dataclasses.dataclass()
class NodeFactory:
    """
    Constructs a node instance. The instance must be start()ed by the caller afterwards.
    """

    heartbeat_vssc: typing.Optional[int] = None
    heartbeat_period: typing.Optional[float] = None
    heartbeat_priority: typing.Optional[Priority] = None

    node_info: typing.Dict[str, typing.Any] = dataclasses.field(
        default_factory=lambda: {
            "protocol_version": {
                "major": pyuavcan.UAVCAN_SPECIFICATION_VERSION[0],
                "minor": pyuavcan.UAVCAN_SPECIFICATION_VERSION[1],
            },
            "software_version": {
                "major": yakut.__version_info__[0],
                "minor": yakut.__version_info__[1],
            },
        }
    )

    def __call__(self, transport: Transport, name_suffix: str, allow_anonymous: bool) -> pyuavcan.application.Node:
        """
        We use ``object`` for return type instead of Node because the Node class requires generated code
        to be generated.
        """
        # pylint: disable=too-many-statements
        from yakut import Purser

        _logger.debug("Constructing node using %r with %r and name %r", self, transport, name_suffix)
        if not re.match(r"[a-z][a-z0-9_]*[a-z0-9]", name_suffix):  # pragma: no cover
            raise ValueError(f"Internal error: Poorly chosen node name suffix: {name_suffix!r}")

        try:
            from pyuavcan import application
        except ImportError as ex:
            from yakut.cmd.compile import make_usage_suggestion

            raise click.UsageError(make_usage_suggestion(ex.name))

        try:
            node_info = pyuavcan.dsdl.update_from_builtin(application.NodeInfo(), self.node_info)
        except (ValueError, TypeError) as ex:
            raise click.UsageError(f"Node info fields are not valid: {ex}") from ex
        if len(node_info.name) == 0:
            node_info.name = f"org.uavcan.yakut.{name_suffix}"
        _logger.debug("Node info: %r", node_info)

        ctx = click.get_current_context()
        assert isinstance(ctx, click.Context)
        purser = ctx.find_object(Purser)
        assert isinstance(purser, Purser)
        node = application.make_node(node_info, purser.get_registry(), transport=transport)
        try:
            # Configure the heartbeat publisher.
            try:
                if self.heartbeat_period is not None:
                    node.heartbeat_publisher.period = self.heartbeat_period
                if self.heartbeat_priority is not None:
                    node.heartbeat_publisher.priority = self.heartbeat_priority
                if self.heartbeat_vssc is not None:
                    node.heartbeat_publisher.vendor_specific_status_code = self.heartbeat_vssc
                else:
                    node.heartbeat_publisher.vendor_specific_status_code = os.getpid() % 100
            except ValueError as ex:
                raise click.UsageError(f"Invalid heartbeat parameters: {ex}") from ex
            _logger.debug(
                "Node heartbeat: %s, period: %s, priority: %s",
                node.heartbeat_publisher.make_message(),
                node.heartbeat_publisher.period,
                node.heartbeat_publisher.priority,
            )

            # Check the node-ID configuration.
            if not allow_anonymous and node.presentation.transport.local_node_id is None:
                raise click.UsageError(
                    "The specified transport is configured in anonymous mode, which cannot be used with this command."
                )

            # Configure the transfer-ID map.
            # Register save on exit even if we're anonymous because the local node-ID may be provided later.
            _register_output_transfer_id_map_save_at_exit(node.presentation)
            # Restore if we have a node-ID. If we don't, no restoration will take place even if the node-ID is
            # provided later. This behavior is acceptable for CLI; a regular UAVCAN application will not need
            # to deal with saving/restoration at all since this use case is specific to CLI only.
            path = _get_output_transfer_id_map_path(node.presentation.transport)
            tid_map_restored = False
            if path is not None:
                tid_map = _restore_output_transfer_id_map(path)
                if tid_map:
                    _logger.debug("Restored output TID map from %s: %r", path, tid_map)
                    node.presentation.output_transfer_id_map.update(tid_map)
                    tid_map_restored = True
            if not tid_map_restored:
                _logger.debug("Could not restore output TID map from %s", path)

            _logger.debug("Constructed node: %s", node)
            return node
        except Exception:
            node.close()
            raise


def node_factory_option(f: typing.Callable[..., typing.Any]) -> typing.Callable[..., typing.Any]:
    factory = NodeFactory()

    def validate_heartbeat_vssc(ctx: click.Context, param: click.Parameter, value: typing.Optional[str]) -> None:
        _ = ctx, param
        if value is not None:
            factory.heartbeat_vssc = int(value)

    def validate_heartbeat_period(ctx: click.Context, param: click.Parameter, value: typing.Optional[str]) -> None:
        _ = ctx, param
        if value is not None:
            factory.heartbeat_period = float(value)

    def validate_heartbeat_priority(
        ctx: click.Context, param: click.Parameter, value: typing.Optional[Priority]
    ) -> None:
        _ = ctx, param
        if value is not None:
            factory.heartbeat_priority = value

    def validate(ctx: click.Context, param: click.Parameter, value: str) -> NodeFactory:
        from yakut.yaml import Loader

        fields = Loader().load(value)
        if not isinstance(fields, dict):
            raise click.BadParameter(f"Expected a dict, got {type(fields).__name__}", ctx=ctx, param=param)

        factory.node_info.update(fields)
        return factory

    f = click.option(
        "--heartbeat-vssc",
        "--vssc",
        type=int,
        expose_value=False,
        callback=validate_heartbeat_vssc,
        help=f"""
The vendor-specific status code (VSSC) of the local node. The default is (PID % 100) of the current process.
""",
    )(f)
    f = click.option(
        "--heartbeat-period",
        type=float,
        metavar="SECONDS",
        callback=validate_heartbeat_period,
        expose_value=False,
        help=f"Heartbeat publication interval.",
    )(f)
    f = click.option(
        "--heartbeat-priority",
        type=EnumParam(Priority),
        callback=validate_heartbeat_priority,
        expose_value=False,
        help=f"Heartbeat publication priority.",
    )(f)
    f = click.option(
        "--node-info",
        "node_factory",
        envvar="YAKUT_NODE_INFO",
        default="{}",
        metavar="YAML",
        type=str,
        callback=validate,
        help="""
Override the default values of the uavcan.node.GetInfo response returned by the local node.
The protocol version cannot be overridden.
""",
    )(f)
    return f


def _restore_output_transfer_id_map(
    file_path: pathlib.Path,
) -> typing.Dict[OutputSessionSpecifier, OutgoingTransferIDCounter]:
    try:
        with open(str(file_path), "rb") as f:
            tid_map = pickle.load(f)
    except Exception as ex:  # pylint: disable=broad-except
        _logger.info(
            "Output TID map: Could not restore from file %s: %s: %s. No problem, will use defaults.",
            file_path,
            type(ex).__name__,
            ex,
        )
        return {}
    mtime_abs_diff = abs(file_path.stat().st_mtime - time.time())
    if mtime_abs_diff > OUTPUT_TRANSFER_ID_MAP_MAX_AGE:
        _logger.debug("Output TID map: File %s is valid but too old: mtime age diff %.0f s", file_path, mtime_abs_diff)
        return {}
    if isinstance(tid_map, dict) and all(isinstance(v, OutgoingTransferIDCounter) for v in tid_map.values()):
        return tid_map
    _logger.warning("Output TID map file %s contains invalid data of type %s", file_path, type(tid_map).__name__)
    return {}


def _register_output_transfer_id_map_save_at_exit(presentation: pyuavcan.presentation.Presentation) -> None:
    # We MUST sample the configuration early because if this is a redundant transport it may reset its
    # configuration (local node-ID) back to default after close().
    path = _get_output_transfer_id_map_path(presentation.transport)
    _logger.debug("Output TID map file for %s: %s", presentation.transport, path)

    def do_save_at_exit() -> None:
        if path is not None:
            tmp = f"{path}.{os.getpid()}.{time.time_ns()}.tmp"
            _logger.debug("Output TID map save: %s --> %s", tmp, path)
            with open(tmp, "wb") as f:
                pickle.dump(presentation.output_transfer_id_map, f)
            # We use replace for compatibility reasons. On POSIX, a call to rename() will be made, which is
            # guaranteed to be atomic. On Windows this may fall back to non-atomic copy, which is still
            # acceptable for us here. If the file ends up being damaged, we'll simply ignore it at next startup.
            os.replace(tmp, str(path))
            try:
                os.unlink(tmp)
            except OSError:
                pass

    atexit.register(do_save_at_exit)


def _get_output_transfer_id_map_path(transport: Transport) -> typing.Optional[pathlib.Path]:
    if transport.local_node_id is not None:
        path = OUTPUT_TRANSFER_ID_MAP_DIR / str(transport.local_node_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
    return None


def _unittest_output_tid_file_path() -> None:
    from pyuavcan.transport.redundant import RedundantTransport
    from pyuavcan.transport.loopback import LoopbackTransport

    def once(tr: Transport) -> typing.Optional[pathlib.Path]:
        return _get_output_transfer_id_map_path(tr)

    assert once(LoopbackTransport(None)) is None
    assert once(LoopbackTransport(123)) == OUTPUT_TRANSFER_ID_MAP_DIR / "123"

    red = RedundantTransport()
    assert once(red) is None
    red.attach_inferior(LoopbackTransport(4000))
    red.attach_inferior(LoopbackTransport(4000))
    assert once(red) == OUTPUT_TRANSFER_ID_MAP_DIR / "4000"

    red = RedundantTransport()
    red.attach_inferior(LoopbackTransport(None))
    red.attach_inferior(LoopbackTransport(None))
    assert once(red) is None
