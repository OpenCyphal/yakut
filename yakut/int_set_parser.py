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
    Discrete elements (, or ;):   1,56;-3
    Intervals [lo,hi) (- or ...): 10-23,-5--7,-10..-2
    Exclusion with ! prefix:      5-9,!6,!5...7
    Arbitrary combination:        -9--5;+4,!-8..-5
    JSON/YAML compatibility:      [1,53,78]
""".strip()


def parse_int_set(text: str) -> set[int] | int:
    """
    Unpacks the integer set notation.
    Accepts JSON-list (subset of YAML) of integers at input, too.
    A single scalar is returned as-is unless there is a separator at the end ("125,") or JSON list is used.
    Raises :class:`IntSetError` on syntax error.
    Usage:

    >>> parse_int_set("")
    set()
    >>> parse_int_set("123"), parse_int_set("[123]"), parse_int_set("123,")
    (123, {123}, {123})
    >>> parse_int_set("-0"), parse_int_set("[-0]"), parse_int_set("-0,")
    (0, {0}, {0})
    >>> sorted(parse_int_set("0..0x0A"))    # Half-open interval with .. or ... or -
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]
    >>> sorted(parse_int_set("-9...-5,"))
    [-9, -8, -7, -6]
    >>> sorted(parse_int_set("-9--5; +4, !-8..-5"))     # Exclusion with ! prefix
    [-9, 4]
    >>> sorted(parse_int_set("-10..+10,!-9-+9"))    # Valid separators are , and ;
    [-10, 9]
    >>> sorted(parse_int_set("6-6"))
    []
    >>> sorted(parse_int_set("[1,53,78]"))
    [1, 53, 78]
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

    collapse = not _RE_JSON_LIST.match(text)
    incl: set[int] = set()
    excl: set[int] = set()
    for item in _RE_SPLIT.split(_RE_JSON_LIST.sub(r"\1", text)):
        item = item.strip()
        if not item:
            collapse = False
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
                target_set |= set(range(lo, hi))
                continue
        raise IntSetError(f"Item {item!r} of the integer set {text!r} could not be parsed")

    result: set[int] | int = incl - excl
    assert isinstance(result, set)
    if collapse and len(result) == 1:
        (result,) = result
    _logger.debug("Int set %r parsed as %r", text, result)
    return result


_RE_JSON_LIST = re.compile(r"^\s*\[([^]]*)]\s*$")
_RE_SPLIT = re.compile(r"[,;]")
_RE_RANGE = re.compile(r"([+-]?\w+)(?:-|\.\.\.?)([+-]?\w+)")
