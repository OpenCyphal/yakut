# Copyright (c) 2022 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

import dataclasses
from typing import Any
from yakut.progress import ProgressCallback as ProgressCallback


@dataclasses.dataclass
class Result:
    data_per_node: dict[int, Any] = dataclasses.field(default_factory=dict)
    errors: list[str] = dataclasses.field(default_factory=list)
    warnings: list[str] = dataclasses.field(default_factory=list)
