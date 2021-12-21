# Copyright (c) 2020 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

from __future__ import annotations
import os
import sys
from typing import TYPE_CHECKING, Iterable, Optional, Any, Callable, Awaitable
import logging
from pathlib import Path
from shutil import get_terminal_size
import click
import yakut
from yakut.param.transport import transport_factory_option, TransportFactory, Transport
from yakut.param.formatter import formatter_factory_option, FormatterFactory, Formatter
from yakut.param.node import node_factory_option, NodeFactory

if TYPE_CHECKING:
    import pyuavcan.application


def get_logger(name: str) -> logging.Logger:
    """
    This is a trivial wrapper over :func:`logging.getLogger` that removes private components from the logger name.
    For example, ``yakut.cmd.file_server._cmd`` becomes ``yakut.cmd.file_server`` (private submodule hidden).
    Also, double underscores are removed.
    All this is done to make the log messages appear nicer, since this is important for a CLI tool.
    """
    return logging.getLogger(name.replace("__", "").split("._", 1)[0])


_logger = get_logger("yakut")
# Some of the integration tests may parse the logs expecting its lines to follow this format.
# If you change this, you may break these tests.
_LOG_FORMAT = "%(asctime)s %(process)07d %(levelname)-3.3s %(name)s: %(message)s"
logging.basicConfig(format=_LOG_FORMAT)  # Using the default log level; it will be overridden later.


class Purser:
    def __init__(
        self,
        paths: Iterable[str | Path],
        formatter_factory: FormatterFactory,
        transport_factory: TransportFactory,
        node_factory: NodeFactory,
    ) -> None:
        self._paths = list(Path(x) for x in paths)
        self._f_formatter = formatter_factory
        self._f_transport = transport_factory
        self._f_node = node_factory

        self._registry: Optional[pyuavcan.application.register.Registry] = None
        self._transport: Optional[Transport] = None
        self._node: Optional["pyuavcan.application.Node"] = None

    @property
    def paths(self) -> list[Path]:
        return list(self._paths)

    def make_formatter(self) -> Formatter:
        return self._f_formatter()

    def get_registry(self) -> pyuavcan.application.register.Registry:
        """
        Commands should never construct registry on their own!
        Doing so is likely to create divergent configurations that are not exposed via the Register Interface.
        Instead, use this factory: it will create a registry instance at the first invocation and then it will be
        shared with all components.

        :raises: :class:`ImportError` if the standard DSDL namespace ``uavcan`` is not available.
        """
        if self._registry is None:
            from pyuavcan.application import make_registry

            self._registry = make_registry()
        return self._registry

    def get_transport(self) -> Transport:
        if self._transport is None:  # pragma: no branch
            self._transport = self._f_transport()
        if self._transport is not None:
            return self._transport
        click.get_current_context().fail("Transport not configured, or the standard DSDL namespace is not compiled")

    def get_node(self, name_suffix: str, allow_anonymous: bool) -> "pyuavcan.application.Node":
        if self._node is None:  # pragma: no branch
            tr = self.get_transport()
            self._node = self._f_node(tr, name_suffix=name_suffix, allow_anonymous=allow_anonymous)
        return self._node


pass_purser = click.make_pass_decorator(Purser)


class AbbreviatedGroup(click.Group):
    def get_command(self, ctx: click.Context, cmd_name: str) -> Optional[click.Command]:
        cmd_name = cmd_name.replace("_", "-")
        rv = click.Group.get_command(self, ctx, cmd_name)
        if rv is not None:
            return rv
        matches = [x for x in self.list_commands(ctx) if x.startswith(cmd_name)]
        if not matches:
            return None
        if len(matches) == 1:
            return click.Group.get_command(self, ctx, matches[0])
        ctx.fail(f"Abbreviated command {cmd_name!r} is ambiguous. Possible matches: {list(matches)}")


_ENV_VAR_PATH = "YAKUT_PATH"


@click.command(
    cls=AbbreviatedGroup,
    context_settings={
        "max_content_width": get_terminal_size()[0],
        "auto_envvar_prefix": "YAKUT",  # Specified here, not in __main__.py, otherwise doesn't work when installed.
    },
)
@click.version_option(version=yakut.__version__)
@click.option("--verbose", "-v", count=True, help="Emit verbose log messages. Specify twice for extra verbosity.")
@click.option(
    "--path",
    "-P",
    multiple=True,
    type=click.Path(resolve_path=True),
    help=f"""
In order to use compiled DSDL namespaces,
the directories that contain compilation outputs need to be specified using this option.
The current working directory does not need to be specified explicitly.

Examples:

\b
    yakut  --path ../public_regulated_data_types  --path ~/my_namespaces  pub ...

\b
    export {_ENV_VAR_PATH}="../public_regulated_data_types:~/my_namespaces"
    yakut pub ...
""",
)
@formatter_factory_option
@transport_factory_option
@node_factory_option
@click.pass_context
def main(
    ctx: click.Context,
    verbose: int,
    path: tuple[str, ...],
    formatter_factory: FormatterFactory,
    transport_factory: TransportFactory,
    node_factory: NodeFactory,
) -> None:
    """
    \b
         __   __   _______   __   __   _______   _______   __   __
        |  | |  | /   _   ` |  | |  | /   ____| /   _   ` |  ` |  |
        |  | |  | |  |_|  | |  | |  | |  |      |  |_|  | |   `|  |
        |  |_|  | |   _   | `  `_/  / |  |____  |   _   | |  |`   |
        `_______/ |__| |__|  `_____/  `_______| |__| |__| |__| `__|
            |      |            |         |      |         |
        ----o------o------------o---------o------o---------o-------

    Yakut is a cross-platform command-line utility for diagnostics and management of UAVCAN networks.
    It is designed for use either directly by humans or from automation scripts.
    Ask questions at https://forum.uavcan.org

    Any long option can be provided via environment variable prefixed with `YAKUT_`
    such that an option `--foo-bar` for command `baz`, if not provided as a command-line argument,
    will be read from `YAKUT_BAZ_FOO_BAR`.

    Any command can be abbreviated arbitrarily as long as the resulting abridged name is not ambiguous.
    For example, `publish`, `publ` and `pub` are all valid and equivalent.
    """
    _configure_logging(verbose)  # This should be done in the first order to ensure that we log things correctly.

    path = (os.getcwd(), *path)
    _logger.debug("Path: %r", path)
    for p in path:
        sys.path.append(str(p))

    ctx.obj = Purser(
        paths=path,
        formatter_factory=formatter_factory,
        transport_factory=transport_factory,
        node_factory=node_factory,
    )


subcommand: Callable[..., Callable[..., Any]] = main.command  # type: ignore


def asynchronous(f: Callable[..., Awaitable[Any]]) -> Callable[..., Any]:
    import asyncio
    from functools import update_wrapper

    def proxy(*args: Any, **kwargs: Any) -> Any:
        return asyncio.run(f(*args, **kwargs))

    return update_wrapper(proxy, f)


def _configure_logging(verbosity_level: int) -> None:
    log_level = {
        0: logging.WARNING,
        1: logging.INFO,
        2: logging.DEBUG,
    }.get(verbosity_level or 0, logging.DEBUG)

    logging.root.setLevel(log_level)

    try:
        import coloredlogs  # type: ignore

        # The level spec applies to the handler, not the root logger! This is different from basicConfig().
        coloredlogs.install(level=log_level, fmt=_LOG_FORMAT)
    except Exception as ex:  # pylint: disable=broad-except
        _logger.exception("Could not set up coloredlogs: %r", ex)  # pragma: no cover
