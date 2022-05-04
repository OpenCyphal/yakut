# Copyright (c) 2020 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

from __future__ import annotations
import os
import sys
import asyncio
import functools
from typing import TYPE_CHECKING, Iterable, Optional, Any, Callable, Awaitable
import logging
from pathlib import Path
from shutil import get_terminal_size
import click
import yakut
from yakut.param.transport import transport_factory_option, TransportFactory, Transport
from yakut.param.formatter import formatter_factory_option, FormatterFactory, Formatter, FormatterHints
from yakut.param.node import node_factory_option, NodeFactory

if TYPE_CHECKING:
    import pycyphal.application


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

        self._registry: Optional[pycyphal.application.register.Registry] = None
        self._transport: Optional[Transport] = None
        self._node: Optional["pycyphal.application.Node"] = None

    @property
    def paths(self) -> list[Path]:
        return list(self._paths)

    def make_formatter(self, hints: FormatterHints = FormatterHints()) -> Formatter:
        return self._f_formatter(hints)

    def get_registry(self) -> pycyphal.application.register.Registry:
        """
        Commands should never construct registry on their own!
        Doing so is likely to create divergent configurations that are not exposed via the Register Interface.
        Instead, use this factory: it will create a registry instance at the first invocation and then it will be
        shared with all components.

        :raises: :class:`ImportError` if the standard DSDL namespace ``uavcan`` is not available.
        """
        if self._registry is None:
            from pycyphal.application import make_registry

            self._registry = make_registry()
        return self._registry

    def get_transport(self) -> Transport:
        if self._transport is None:  # pragma: no branch
            self._transport = self._f_transport()
        if self._transport is not None:
            return self._transport
        click.get_current_context().fail("Transport not configured, or the standard DSDL namespace is not compiled")

    def get_node(self, name_suffix: str, allow_anonymous: bool) -> "pycyphal.application.Node":
        if self._node is None:  # pragma: no branch
            tr = self.get_transport()
            self._node = self._f_node(tr, name_suffix=name_suffix, allow_anonymous=allow_anonymous)
        return self._node


pass_purser = click.make_pass_decorator(Purser)


class AliasedGroup(click.Group):
    """
    This class is inspired by "click-aliases" from Robbin Bonthond published at
    https://github.com/click-contrib/click-aliases/blob/master/click_aliases/__init__.py
    under the terms of the MIT license.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._commands: dict[str, set[str]] = {}
        self._aliases: dict[str, str] = {}

    def command(self, *args: Any, **kwargs: Any) -> Any:
        aliases = AliasedGroup._mk_aliases(kwargs.pop("aliases", []))
        decorator: Any = super().command(*args, **kwargs)
        if not aliases:
            return decorator

        def _decorator(f: Any) -> Any:
            cmd: Any = decorator(f)
            if aliases:
                self._commands[cmd.name] = aliases
                for alias in aliases:
                    self._aliases[alias] = cmd.name
            return cmd

        return _decorator

    def group(self, *args: Any, **kwargs: Any) -> Any:
        aliases = AliasedGroup._mk_aliases(kwargs.pop("aliases", []))
        decorator: Any = super().group(*args, **kwargs)
        if not aliases:
            return decorator

        def _decorator(f: Any) -> Any:
            cmd: Any = decorator(f)
            if aliases:
                self._commands[cmd.name] = aliases
                for alias in aliases:
                    self._aliases[alias] = cmd.name
            return cmd

        return _decorator

    def get_command(self, ctx: click.Context, cmd_name: str) -> Any:
        cmd_name = self._aliases.get(cmd_name, cmd_name)
        return super().get_command(ctx, cmd_name)

    def resolve_command(
        self, ctx: click.Context, args: list[Any]
    ) -> tuple[str | None, click.Command | None, list[str]]:
        """
        This is a workaround for this bug in v7 and v8: https://github.com/pallets/click/issues/1422.
        If this is not overridden, then abbreviated commands cause the automatic envvar prefix to be constructed
        incorrectly, such that instead of the full command name the abbreviated name is used.
        For example, if the user invokes `yakut co` meaning `yakut compile`,
        the auto-constructed envvar prefix would be `YAKUT_CO_` instead of `YAKUT_COMPILE_`.
        """
        _, cmd, out_args = super().resolve_command(ctx, args)
        return (cmd.name if cmd else None), cmd, out_args

    def format_commands(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        rows: list[tuple[str, str]] = []
        sub_commands = self.list_commands(ctx)
        max_len = max(len(cmd) for cmd in sub_commands)
        limit = formatter.width - 6 - max_len
        for subcmd in sub_commands:
            cmd = self.get_command(ctx, subcmd)
            if cmd is not None and not getattr(cmd, "hidden", False):
                if subcmd in self._commands:
                    subcmd = ",".join([subcmd] + list(sorted(self._commands[subcmd])))
                rows.append((subcmd, cmd.get_short_help_str(limit)))
        if rows:
            with formatter.section("Commands (with aliases)"):
                formatter.write_dl(rows)

    @staticmethod
    def _mk_aliases(item: Any) -> set[str]:
        if isinstance(item, str):
            return {item}
        if isinstance(item, (list, tuple, set)) and all(isinstance(x, str) for x in item):
            return set(item)
        raise TypeError(f"Bad aliases: {item}")


_ENV_VAR_PATH = "YAKUT_PATH"


@click.command(
    cls=AliasedGroup,
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
def _click_main(
    ctx: click.Context,
    verbose: int,
    path: tuple[str, ...],
    formatter_factory: FormatterFactory,
    transport_factory: TransportFactory,
    node_factory: NodeFactory,
) -> None:
    """
    \b
           ____                   ______            __          __
          / __ `____  ___  ____  / ____/_  ______  / /_  ____  / /
         / / / / __ `/ _ `/ __ `/ /   / / / / __ `/ __ `/ __ `/ /
        / /_/ / /_/ /  __/ / / / /___/ /_/ / /_/ / / / / /_/ / /
        `____/ .___/`___/_/ /_/`____/`__, / .___/_/ /_/`__,_/_/
            /_/                     /____/_/

    Yakut is a cross-platform command-line utility for diagnostics and management of Cyphal networks.
    It is designed for use either directly by humans or from automation scripts.
    Ask questions at https://forum.opencyphal.org

    Any long option can be provided via environment variable prefixed with `YAKUT_`
    such that an option `--foo-bar` for command `baz`, if not provided as a command-line argument,
    will be read from `YAKUT_BAZ_FOO_BAR`.
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


def main() -> None:  # https://click.palletsprojects.com/en/8.1.x/exceptions/
    from yakut.ui import show_error

    status: Any = 1
    # noinspection PyBroadException
    try:
        status = _click_main.main(prog_name="yakut", standalone_mode=False)

    except SystemExit as ex:
        status = ex.code

    except (KeyboardInterrupt, click.Abort) as ex:
        status = 127
        _logger.info("Interrupted")
        _logger.debug("%s: %s", type(ex).__name__, ex, exc_info=True)

    except click.ClickException as ex:
        status = ex.exit_code
        try:
            click.secho("", err=True, fg="red", bold=True, reset=False, nl=False)
            ex.show()
        finally:
            click.secho("", err=True, nl=False)

    except Exception as ex:  # pylint: disable=broad-except
        show_error(f"{type(ex).__name__}: {ex}")
        _logger.debug("EXCEPTION %s: %s", type(ex).__name__, ex, exc_info=True)

    except BaseException as ex:  # pylint: disable=broad-except
        show_error(f"Internal error, please report: {ex}")
        _logger.error("%s: %s", type(ex).__name__, ex, exc_info=True)

    _logger.debug("EXIT %r", status)
    sys.exit(status)


subcommand: Callable[..., Callable[..., Any]] = _click_main.command  # type: ignore


def asynchronous(*, interrupted_ok: bool = False) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Any]]:
    def impl(f: Callable[..., Awaitable[Any]]) -> Callable[..., Any]:
        def handle_task_exception(_loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
            message = context.get("message", "Unhandled exception in event loop")
            exc = context.get("exception")
            exc_info: Any = (type(exc), exc, exc.__traceback__) if exc else False
            _logger.debug("Task exception during shutdown: %s", message, exc_info=exc_info)

        # This is similar to asyncio.run().
        # The difference is that we configure logging differently to avoid unhelpful stack traces during shutdown.
        # Appearance of such errors is not the expected behavior and should be fixed, but the user need not
        # know about these errors as they are unlikely to affect the behavior of the application.
        # See https://github.com/OpenCyphal/yakut/issues/40
        def proxy(*args: Any, **kwargs: Any) -> Any:
            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)
                return loop.run_until_complete(f(*args, **kwargs))
            except KeyboardInterrupt:
                if not interrupted_ok:
                    raise
            finally:
                _logger.debug("Event loop finalization with exc=%r", sys.exc_info())
                try:
                    loop.set_exception_handler(handle_task_exception)  # Reduce severity of exception reports

                    # Suppress finalization errors from PyCyphal https://github.com/OpenCyphal/pycyphal/issues/227
                    pycyphal_logger = logging.getLogger("pycyphal")
                    if not pycyphal_logger.isEnabledFor(logging.INFO):  # Do not suppress if verbose
                        pycyphal_logger.setLevel(logging.CRITICAL)

                    orphans = asyncio.all_tasks(loop)
                    if orphans:
                        for ts in orphans:
                            ts.cancel()
                        for e in loop.run_until_complete(asyncio.gather(*orphans, return_exceptions=True)):
                            if isinstance(e, BaseException) and not isinstance(e, asyncio.CancelledError):
                                handle_task_exception(loop, {"exception": e})
                finally:
                    asyncio.set_event_loop(None)
                    loop.close()

        return functools.update_wrapper(proxy, f)

    return impl


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
