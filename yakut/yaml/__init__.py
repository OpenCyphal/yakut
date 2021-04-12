# Copyright (c) 2019 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

"""
The YAML library we use is API-unstable at the time of writing. We can't just use the de-facto standard PyYAML
because it's kinda stuck in the past (no ordered dicts, no support for YAML v1.2). This facade shields the
rest of the code from breaking changes in the YAML library API or from migration to another library.
"""

from ._dumper import YAMLDumper as YAMLDumper
from ._loader import YAMLLoader as YAMLLoader

from ._eval_loader import EvaluableYAMLLoader as EvaluableYAMLLoader
from ._eval_loader import EmbeddedExpressionError as EmbeddedExpressionError
