# Copyright (c) 2020 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

import typing


def _read_package_file(name: str) -> str:
    try:
        from importlib.resources import files

        return (files(__name__) / name).read_text(encoding="utf8")
    except ImportError:  # This is for the old Pythons; read_text is deprecated in 3.11
        from importlib.resources import read_text

        return read_text(__name__, name, encoding="utf8")


__version__: str = _read_package_file("VERSION").strip()
__version_info__: typing.Tuple[int, ...] = tuple(map(int, __version__.split(".")[:3]))
__author__ = "OpenCyphal"
__email__ = "consortium@opencyphal.org"
__copyright__ = f"Copyright (c) 2020 {__author__} <{__email__}>"
__license__ = "MIT"

from .main import main as main, subcommand as subcommand, Purser as Purser, pass_purser as pass_purser
from .main import asynchronous as asynchronous, get_logger as get_logger
from . import cmd as cmd
