# Copyright (c) 2019 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

from __future__ import annotations
import re
import logging

_logger = logging.getLogger(__name__)


class IntSetError(ValueError):
    pass


INT_SET_USER_DOC = """
Integer set notation examples:

\b
    discrete elements (comma or semicolon): 1,56;-3
    closed ranges (minus or tilde):         10-23,-5--7,-10~-2
    exclusion with ! prefix:                5-9,!6,!5~7
    arbitrary combination:                  -9--5;+4,!-8~-5
""".strip()


def parse_int_set(input: str) -> set[int]:
    """
    Unpacks the integer set notation.
    Raises :class:`IntSetError` on syntax error.
    Usage:

    >>> sorted(parse_int_set(""))
    []
    >>> sorted(parse_int_set("123"))
    [123]
    >>> sorted(parse_int_set("123,"))
    [123]
    >>> sorted(parse_int_set("-0"))
    [0]
    >>> sorted(parse_int_set("0~0x0A"))             # Closed range with ~ or -
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    >>> sorted(parse_int_set("-9--5,"))
    [-9, -8, -7, -6, -5]
    >>> sorted(parse_int_set("-9--5; +4, !-8~-5"))  # Exclusion with ! prefix
    [-9, 4]
    >>> sorted(parse_int_set("-10~+10,!-9-+9"))     # Valid separators are , and ;
    [-10, 10]
    >>> sorted(parse_int_set("6-5"))
    []
    >>> parse_int_set("123,456,9-") # doctest:+IGNORE_EXCEPTION_DETAIL
    Traceback (most recent call last):
    ...
    IntSetError: ...
    """

    def try_parse(val: str) -> int | None:
        try:
            return int(val, 0)
        except ValueError:
            return None

    incl: set[int] = set()
    excl: set[int] = set()
    for item in _RE_SPLIT.split(input):
        item = item.strip()
        if not item:
            continue
        if item.startswith("!"):
            target_set = excl
            item = item[1:]
        else:
            target_set = incl
        x = try_parse(item)
        if x is not None:
            target_set.add(x)
            continue
        match = _RE_RANGE.match(item)
        if match:
            lo, hi = map(try_parse, match.groups())
            if lo is not None and hi is not None:
                target_set |= set(range(lo, hi + 1))
                continue
        raise IntSetError(f"Item {item!r} of the integer set {input!r} could not be parsed")

    result = incl - excl
    _logger.debug("Int set %r parsed as %r", input, result)
    return result


_RE_SPLIT = re.compile(r"[,;]")
_RE_RANGE = re.compile(r"([+-]?\w+)[-~]([+-]?\w+)")
