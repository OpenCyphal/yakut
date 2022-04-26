# Copyright (c) 2022 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

import sys
from typing import Callable
import click


ProgressCallback = Callable[[str], None]


def get_progress_callback() -> ProgressCallback:
    if sys.stderr.isatty():  # Add extra space after the text is to improve appearance when the text is shortened.
        return lambda text: click.secho(f"\r{text} \r", nl=False, file=sys.stderr, fg="green")
    return lambda _: None
