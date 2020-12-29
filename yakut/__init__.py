# Copyright (c) 2020 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

import pathlib

__version__ = (pathlib.Path(__file__).parent / "VERSION").read_text().strip()
__version_info__ = tuple(map(int, __version__.split(".")[:3]))
__author__ = "UAVCAN Consortium"
__email__ = "consortium@uavcan.org"
__copyright__ = f"Copyright (c) 2020 {__author__} <{__email__}>"
__license__ = "MIT"

from .main import main as main, subcommand as subcommand, Purser as Purser, pass_purser as pass_purser
from .main import asynchronous as asynchronous
from . import cmd as cmd
