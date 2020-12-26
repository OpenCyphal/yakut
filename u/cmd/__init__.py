# Copyright (c) 2020 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

import sys
import pyuavcan.util

# BY CONVENTION, the COMMAND and the MODULE it is defined in should be NAMED IDENTICALLY.
pyuavcan.util.import_submodules(sys.modules[__name__])
