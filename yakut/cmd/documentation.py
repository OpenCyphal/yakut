# Copyright (c) 2019 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

import sys
import typing
import click
import yakut


_logger = yakut.get_logger(__name__)


@yakut.subcommand()
@click.argument("name", default="")
def documentation(name: str) -> None:
    """
    Show transport usage documentation from PyUAVCAN.
    Transports whose dependencies are not installed will not be shown.

    If the argument NAME is provided, the documentation will be shown only for entities whose name contains
    the specified string (case-insensitive), like "udp".

    Full documentation is available at https://pyuavcan.readthedocs.io
    """
    import pydoc
    import pyuavcan

    fill_width = click.get_terminal_size()[0] - 1

    # noinspection PyTypeChecker
    pyuavcan.util.import_submodules(pyuavcan.transport, error_handler=_handle_import_error)
    transport_base = pyuavcan.transport.Transport
    texts: typing.List[str] = []
    for cls in pyuavcan.util.iter_descendants(transport_base):
        if not cls.__name__.startswith("_") and cls is not transport_base:
            public_module = cls.__module__.split("._")[0]
            public_name = public_module + "." + cls.__name__
            if name.lower() in public_name.lower():
                texts.append(
                    "\n".join(
                        [
                            "-" * fill_width,
                            public_name.center(fill_width, " "),
                            "-" * fill_width,
                            cls.__doc__,
                            pydoc.text.document(cls.__init__),
                            "",
                        ]
                    )
                )
    if texts:
        click.echo_via_pager(texts)
    else:
        click.secho(f"There are no entries that match {name!r}", err=True, fg="red")
        sys.exit(1)


def _handle_import_error(name: str, ex: ImportError) -> None:
    _logger.info("Transport module %r is not available because: %r", name, ex)
