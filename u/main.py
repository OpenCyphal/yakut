# Copyright (c) 2020 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

import os
import sys
import typing
import logging
import click
import u


_logger = logging.getLogger(__name__.replace("__", ""))
_LOG_FORMAT = "%(asctime)s %(process)07d %(levelname)-5.5s %(name)s: %(message)s"
logging.basicConfig(format=_LOG_FORMAT)  # Using the default log level; it will be overridden later.


@click.group()
@click.version_option(version=u.__version__)
@click.option("--verbose", "-v", count=True, help="Show verbose log messages. Specify twice for extra verbosity.")
@click.option(
    "--path",
    "-P",
    multiple=True,
    type=click.Path(resolve_path=True),
    help=f"""
In order to use compiled DSDL namespaces,
the directories that contain the compilation outputs need to be specified using this option before invoking the U-tool.
The current working directory does not need to be specified explicitly.

An alternative way to specify the DSDL look-up directories is to use the environment variable U_PATH,
where multiple entries can be listed like in the standard PATH variable.

Examples:

\b
    u  --path ../public_regulated_data_types  --path ~/my_namespaces  pub ...

\b
    export U_PATH="../public_regulated_data_types:~/my_namespaces"
    u pub ...
""",
)
def main(verbose: int, path: typing.Tuple[str, ...]) -> None:
    """
    \b
         __   __   _______   __   __   _______   _______   __   __
        |  | |  | /   _   ` |  | |  | /   ____| /   _   ` |  ` |  |
        |  | |  | |  |_|  | |  | |  | |  |      |  |_|  | |   `|  |
        |  |_|  | |   _   | `  `_/  / |  |____  |   _   | |  |`   |
        `_______/ |__| |__|  `_____/  `_______| |__| |__| |__| `__|
            |      |            |         |      |         |
        ----o------o------------o---------o------o---------o-------

    U-tool is a cross-platform command-line utility for diagnostics and management of UAVCAN networks.
    It is designed for use either directly by humans or from automation scripts.

    The U-tool is built on top of PyUAVCAN -- a Python library implementing the UAVCAN stack
    for high-level operating systems (GNU/Linux, Windows, macOS)
    supporting different transport protocols (UAVCAN/UDP, UAVCAN/CAN, etc).

    Ask questions at https://forum.uavcan.org
    """
    _configure_logging(verbose)  # This should be done in the first order to ensure that we log things correctly.

    for p in (os.getcwd(), *path):
        _logger.debug("New path item: %s", p)
        sys.path.append(str(p))


subcommand = main.command


def _configure_logging(verbosity_level: int) -> None:
    log_level = {
        0: logging.WARNING,
        1: logging.INFO,
        2: logging.DEBUG,
    }.get(verbosity_level or 0, logging.DEBUG)

    logging.root.setLevel(log_level)

    try:
        import coloredlogs

        # The level spec applies to the handler, not the root logger! This is different from basicConfig().
        coloredlogs.install(level=log_level, fmt=_LOG_FORMAT)
    except Exception as ex:  # pragma: no cover
        _logger.exception("Could not set up coloredlogs: %r", ex)
