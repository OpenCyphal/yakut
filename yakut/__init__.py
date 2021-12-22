# Copyright (c) 2020 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

import typing
from importlib.resources import read_text as _read_text

__version__: str = _read_text(__name__, "VERSION", encoding="utf8").strip()
__version_info__: typing.Tuple[int, ...] = tuple(map(int, __version__.split(".")[:3]))
__author__ = "UAVCAN Consortium"
__email__ = "consortium@uavcan.org"
__copyright__ = f"Copyright (c) 2020 {__author__} <{__email__}>"
__license__ = "MIT"

from .main import main as main, subcommand as subcommand, Purser as Purser, pass_purser as pass_purser
from .main import asynchronous as asynchronous, get_logger as get_logger
from . import cmd as cmd
