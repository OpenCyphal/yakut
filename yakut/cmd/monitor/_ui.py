# Copyright (c) 2021 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

from __future__ import annotations
import sys
import dataclasses
import functools
from typing import Optional, Iterable, Any, IO
from numbers import Number
import enum
import click


# errors=ignore is necessary to handle Unicode support limitations on Windows.
_TEXT_STREAM = click.get_text_stream("stdout", errors="ignore")


def refresh_screen(contents: str) -> None:
    if _isatty(sys.stdout):
        click.clear()
    else:
        _TEXT_STREAM.write("\n" * 3)
    # Synchronize clear with the following output since it is buffered separately.
    # Note that we MUST flush stdout, not _TEXT_STREAM, because it is buffered separately.
    sys.stdout.flush()
    click.echo(contents, file=_TEXT_STREAM, nl=False)


def _isatty(stream: IO[str]) -> bool:
    # noinspection PyBroadException
    try:
        return stream.isatty()
    except Exception:  # pylint: disable=broad-except
        return False


class Color(enum.Enum):
    BLACK = enum.auto()
    RED = enum.auto()
    GREEN = enum.auto()
    YELLOW = enum.auto()
    BLUE = enum.auto()
    MAGENTA = enum.auto()
    CYAN = enum.auto()
    WHITE = enum.auto()


@dataclasses.dataclass(frozen=True)
class Style:
    fg: Optional[Color] = None
    bg: Optional[Color] = None
    salience: int = 0  # -1 dim, +1 bold, +2 blink


class TableRenderer:
    """
    This class may be slow to instantiate. Do not instantiate inside the drawing loop.
    """

    def __init__(self, column_widths: Iterable[int], *, separate_columns: bool) -> None:
        self._canvas = Canvas()
        self._column_widths = list(column_widths)
        self._column_offsets = [0]
        for cw in self._column_widths:
            self._column_offsets.append(self._column_offsets[-1] + cw + int(separate_columns))

    def set_cell(self, row: int, column: int, data: Any, *, style: Optional[Style] = None) -> None:
        if isinstance(data, (bool, Number)):
            data = str(data).rjust(self._column_widths[column])
        self._canvas.put(row, self._column_offsets[column], data, style=style)

    def __setitem__(self, key: tuple[int, int], value: Any) -> None:
        row, col = key
        if isinstance(value, tuple):
            data, style = value
        else:
            data, style = value, None
        self.set_cell(row, col, data, style=style)

    def render(self, max_width_height: tuple[int, int]) -> str:
        # Make all rows equal length.
        m_row, m_col = self._canvas.extent
        for row in range(m_row):
            self._canvas.put(row, m_col, "")
        return self._canvas.render(max_width_height)


class Canvas:
    @dataclasses.dataclass(frozen=True)
    class _Block:
        column: int
        text: str
        style: Optional[Style]

    def __init__(self) -> None:
        self._rows: list[list[Canvas._Block]] = []

    @property
    def extent(self) -> tuple[int, int]:
        return len(self._rows), max((x.column + len(x.text)) for r in self._rows for x in r)

    def put(self, row: int, column: int, data: Any, *, style: Optional[Style] = None) -> int:
        while len(self._rows) <= row:
            self._rows.append([])
        text = str(data)
        bl = Canvas._Block(
            column=column,
            text=text,
            style=style,
        )
        self._rows[row].append(bl)
        return column + len(text)

    def render(self, max_width_height: tuple[int, int]) -> str:
        width, height = max_width_height
        out = "\n".join(self._render_row(r, width) for r in self._rows[:height]) + click.style("", reset=True)
        self._rows = []
        return out

    def _render_row(self, ln: list[Canvas._Block], max_width: int) -> str:
        col = 0
        out: list[str] = [self._begin_style(None)]
        for b in sorted(ln, key=lambda x: x.column):
            if b.column >= max_width:
                break
            out.append(" " * (b.column - col))
            margin = max_width - b.column
            assert margin > 0
            addition = b.text[:margin]
            out.append(self._begin_style(b.style))
            out.append(addition)
            col = b.column + len(addition)
        return "".join(out)

    @staticmethod
    @functools.lru_cache(None)
    def _begin_style(s: Optional[Style]) -> str:
        out = click.style("", reset=True)
        if s is not None:
            out += click.style(
                "",
                fg=(("bright_" * (s.salience > 0)) + s.fg.name.lower()) if s.fg else None,
                bg=s.bg.name.lower() if s.bg else None,
                dim=s.salience < 0,
                bold=s.salience > 0,
                blink=s.salience > 1,
                reset=False,
            )
        return out
