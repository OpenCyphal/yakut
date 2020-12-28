# Copyright (c) 2020 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

import pathlib

# Please maintain these carefully if you're changing the project's directory structure.
TEST_DIR = pathlib.Path(__file__).resolve().parent
ROOT_DIR = TEST_DIR.parent

DEPS_DIR = TEST_DIR / "deps"
assert DEPS_DIR.is_dir()
