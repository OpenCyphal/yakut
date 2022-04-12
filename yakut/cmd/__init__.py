# Copyright (c) 2020 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

import sys
import pycyphal.util

# BY CONVENTION, the COMMAND and the MODULE it is defined in should be NAMED IDENTICALLY.
pycyphal.util.import_submodules(sys.modules[__name__])
