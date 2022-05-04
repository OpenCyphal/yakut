# Copyright (c) 2022 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

from __future__ import annotations
import sys
from typing import Callable, Any
import click


ProgressCallback = Callable[[str], None]


class ProgressReporter:
    def __init__(self) -> None:
        self._widest = 0
        self._impl = _mk_impl()

    def __call__(self, text: str) -> None:
        self._widest = max(self._widest, len(text))
        # Add extra space after the text is to improve appearance when the text is shortened.
        self._impl(text.ljust(self._widest))

    def clear(self) -> None:
        """
        Call this once at the end to erase the progress line from the screen.
        Does nothing if no output was generated.
        """
        if self._widest > 0:
            self._impl(" " * self._widest)

    def __enter__(self) -> ProgressReporter:
        return self

    def __exit__(self, *_: Any) -> None:
        """
        Invokes :meth:`clear` upon leaving the context.
        """
        self.clear()


def _mk_impl() -> ProgressCallback:
    if sys.stderr.isatty():
        return lambda text: click.secho(f"\r{text}\r", nl=False, file=sys.stderr, fg="green")
    return lambda _: None


def show_error(msg: str) -> None:
    click.secho(msg, err=True, fg="red", bold=True)


def show_warning(msg: str) -> None:
    click.secho(msg, err=True, fg="yellow")
