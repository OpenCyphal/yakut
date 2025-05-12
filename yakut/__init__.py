# Copyright (c) 2020 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

# Disabling unused ignores because we need to support different versions of importlib.resources.
# mypy: warn_unused_ignores=False
# pylint: disable=wrong-import-position

import typing


def _read_package_file(name: str) -> str:
    from importlib.resources import files  # type: ignore

    return (files(__name__) / name).read_text(encoding="utf8")  # type: ignore


__version__: str = _read_package_file("VERSION").strip()
__version_info__: typing.Tuple[int, ...] = tuple(map(int, __version__.split(".")[:3]))
__author__ = "OpenCyphal"
__email__ = "consortium@opencyphal.org"
__copyright__ = f"Copyright (c) 2020 {__author__} <{__email__}>"
__license__ = "MIT"

from .main import main as main, subcommand as subcommand, Purser as Purser, pass_purser as pass_purser
from .main import asynchronous as asynchronous, get_logger as get_logger
from . import cmd as cmd
