# Copyright (c) 2019 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

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
from pyuavcan.transport import Transport, OutputSessionSpecifier
from pyuavcan.presentation import OutgoingTransferIDCounter
from u.paths import OUTPUT_TRANSFER_ID_MAP_DIR, OUTPUT_TRANSFER_ID_MAP_MAX_AGE


_ENV_VAR_HEARTBEAT_VSSC = "U_HEARTBEAT_VSSC"
_ENV_VAR_NODE_INFO_FIELDS = "U_NODE_INFO_FIELDS"

_logger = logging.getLogger(__name__)


@dataclasses.dataclass()
class NodeFactory:
    """
    Constructs a node instance. The instance must be start()ed by the caller afterwards.
    """

    heartbeat_vssc: typing.Optional[int] = None
    node_info_fields: typing.Dict[str, typing.Any] = dataclasses.field(
        default_factory=lambda: {
            "protocol_version": {
                "major": pyuavcan.UAVCAN_SPECIFICATION_VERSION[0],
                "minor": pyuavcan.UAVCAN_SPECIFICATION_VERSION[1],
            },
            "software_version": {
                "major": pyuavcan.__version_info__[0],
                "minor": pyuavcan.__version_info__[1],
            },
        }
    )

    def __call__(self, transport: Transport, name_suffix: str, allow_anonymous: bool) -> object:
        """
        We use ``object`` for return type instead of Node because the Node class requires generated code
        to be generated.
        """
        _logger.debug("Constructing node using %r with %r and name %r", self, transport, name_suffix)
        if not re.match(r"[a-z][a-z0-9_]*[a-z0-9]", name_suffix):  # pragma: no cover
            raise ValueError(f"Internal error: Poorly chosen node name suffix: {name_suffix!r}")

        try:
            from pyuavcan import application
            from pyuavcan.application import heartbeat_publisher
        except ImportError as ex:
            from u.cmd import compile

            raise click.UsageError(compile.make_usage_suggestion(ex.name))

        try:
            node_info = pyuavcan.dsdl.update_from_builtin(application.NodeInfo(), self.node_info_fields)
        except (ValueError, TypeError) as ex:
            raise click.UsageError(f"Node info fields are not valid: {ex}") from ex
        node_info.name = node_info.name or f"org.uavcan.pyuavcan.cli.{name_suffix}"
        _logger.debug("Node info: %r", node_info)

        presentation = pyuavcan.presentation.Presentation(transport)
        node = application.Node(presentation, info=node_info)
        try:
            # Configure the heartbeat publisher.
            if self.heartbeat_vssc is not None:
                try:
                    node.heartbeat_publisher.vendor_specific_status_code = self.heartbeat_vssc
                except ValueError:
                    raise click.UsageError(f"Invalid vendor-specific status code: {self.heartbeat_vssc}")
            else:
                node.heartbeat_publisher.vendor_specific_status_code = os.getpid() % 100
            _logger.debug("Node heartbeat: %r", node.heartbeat_publisher.make_message())

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
                    # noinspection PyTypeChecker
                    presentation.output_transfer_id_map.update(tid_map)  # type: ignore
                    tid_map_restored = True
            if not tid_map_restored:
                _logger.debug("Could not restore output TID map from %s", path)

            _logger.info("Constructed node: %s", node)
            return node
        except Exception:
            node.close()
            raise


def node_factory_option(f: typing.Callable[..., typing.Any]) -> typing.Callable[..., typing.Any]:
    factory = NodeFactory()

    def validate_heartbeat_vssc(ctx: click.Context, param: click.Parameter, value: str) -> None:
        _ = ctx, param
        factory.heartbeat_vssc = int(value)

    def validate(ctx: click.Context, param: click.Parameter, value: str) -> NodeFactory:
        from u.yaml import YAMLLoader

        fields = YAMLLoader().load(value)
        if not isinstance(fields, dict):
            raise click.BadParameter(f"Expected a dict, got {type(fields).__name__}", ctx=ctx, param=param)

        factory.node_info_fields.update(fields)
        return factory

    f = click.option(
        "--heartbeat-vssc",
        "--vssc",
        envvar=_ENV_VAR_HEARTBEAT_VSSC,
        type=int,
        expose_value=False,
        callback=validate_heartbeat_vssc,
        help=f"""
Specify the vendor-specific status code (VSSC) of the local node.
This option will have no effect if the local node is anonymous.
Another way to specify this option is via environment variable {_ENV_VAR_HEARTBEAT_VSSC}.
The default is (PID % 100) of the current process.
""",
    )(f)
    f = click.option(
        "--node-info-fields",
        "node_factory",
        default="{}",
        metavar="YAML",
        envvar=_ENV_VAR_NODE_INFO_FIELDS,
        type=str,
        callback=validate,
        help=f"""
Allows overriding the default values of the uavcan.node.GetInfo response returned by the node.
Another way to specify this option is via environment variable {_ENV_VAR_NODE_INFO_FIELDS}.
The defaults are (the default node name depends on the subcommand):

\b
{factory.node_info_fields}
""",
    )(f)
    return f


def _restore_output_transfer_id_map(
    file_path: pathlib.Path,
) -> typing.Dict[OutputSessionSpecifier, OutgoingTransferIDCounter]:
    try:
        with open(str(file_path), "rb") as f:
            tid_map = pickle.load(f)
    except Exception as ex:
        _logger.info("Output TID map: Could not restore from file %s: %s: %s", file_path, type(ex).__name__, ex)
        return {}

    mtime_abs_diff = abs(file_path.stat().st_mtime - time.time())
    if mtime_abs_diff > OUTPUT_TRANSFER_ID_MAP_MAX_AGE:
        _logger.debug("Output TID map: File %s is valid but too old: mtime age diff %.0f s", file_path, mtime_abs_diff)
        return {}

    if isinstance(tid_map, dict) and all(isinstance(v, OutgoingTransferIDCounter) for v in tid_map.values()):
        return tid_map
    else:
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
