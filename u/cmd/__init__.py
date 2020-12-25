# Copyright (c) 2020 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

import sys
import pyuavcan.util

# pyuavcan.util.import_submodules(sys.modules[__name__])
from . import (
    doc,
    compile,
    accommodate,
)  # FIXME this is tentative, uncomment the above when all commands are implemented.
