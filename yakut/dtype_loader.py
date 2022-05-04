# Copyright (c) 2019 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

from __future__ import annotations
import re
from typing import Any, Type
import logging
import importlib

_logger = logging.getLogger(__name__)


class LoadError(Exception):
    pass


class FormatError(LoadError):
    pass


class NotFoundError(LoadError):
    pass


def load_dtype(name: str, allow_minor_version_mismatch: bool = False) -> Type[Any]:
    r"""
    Parses a data specifier string of the form ``full_data_type_name[.major_version[.minor_version]]``.
    Name separators may be replaced with ``/`` or ``\`` for compatibility with file system paths.
    Missing version numbers substituted with the latest one available.
    The short data type name is case-insensitive.

    :param name: Examples: ``uavcan.heartbeat``, ``uavcan.Heartbeat.1``, ``uavcan.HEARTBEAT.1.0``.

    :param allow_minor_version_mismatch:
        If the minor version is specified and there is no matching data type,
        repeat the search with the minor version omitted.
    """
    parsed = _parse(name)
    if not parsed:
        raise FormatError(f"Data type name format not understood: {name!r}")
    name_components, major, minor = parsed
    _logger.debug("Parsed %r: name_components=%r, major=%r, minor=%r", name, name_components, major, minor)
    try:
        result = _load(name_components, major, minor)
    except NotFoundError:
        if allow_minor_version_mismatch and minor is not None:
            result = _load(name_components, major, None)
        else:
            raise
    _logger.debug("Loaded %r as %r", name, result)
    return result


def _load(name_components: list[str], major: int | None, minor: int | None) -> Type[Any]:
    from yakut.cmd.compile import make_usage_suggestion

    namespaces, short_name = name_components[:-1], name_components[-1]
    try:
        mod = None
        for comp in namespaces:
            name = (mod.__name__ + "." + comp) if mod else comp  # type: ignore
            try:
                mod = importlib.import_module(name)
            except ImportError:  # We seem to have hit a reserved word; try with an underscore.
                mod = importlib.import_module(name + "_")
    except ImportError as ex:
        raise NotFoundError(make_usage_suggestion(namespaces[0])) from ex
    assert mod
    matches = sorted(
        (
            (x.groups(), getattr(mod, x.string))
            for x in filter(None, map(_RE_SHORT_TYPE_NAME_IDENTIFIER.match, dir(mod)))
            if (
                short_name.lower() == x.group(1).lower()
                and (major is None or int(x.group(2)) == major)
                and (minor is None or int(x.group(3)) == minor)
            )
        ),
        reverse=True,
    )
    _logger.debug("Identifiers in %r matching %s.%s.%s: %r", mod, short_name, major, minor, matches)
    if not matches:
        raise NotFoundError(
            f"Could not locate "
            f"{short_name}.{major if major is not None else '*'}.{minor if minor is not None else '*'} "
            f"in module {mod.__name__!r}"
        )
    return matches[0][1]  # type: ignore


def _parse(name: str) -> tuple[list[str], int | None, int | None] | None:
    m = _RE_PARSE.match(name)
    if not m:
        return None
    full_name, major, minor = m.groups()
    return list(_RE_SPLIT_NAME_COMPONENTS.split(full_name)), _version_or_nothing(major), _version_or_nothing(minor)


def _version_or_nothing(inp: str) -> int | None:
    return None if inp is None else int(inp)


_RE_PARSE = re.compile(
    r"^"
    r"([a-zA-Z_][a-zA-Z0-9_]*(?:[./\\][a-zA-Z_][a-zA-Z0-9_]*)+)"
    r"(?:[./\\](\d+))?"  # major version
    r"(?:[./\\](\d+))?"  # minor version
    r"$",
)
_RE_SPLIT_NAME_COMPONENTS = re.compile(r"\W")
_RE_SHORT_TYPE_NAME_IDENTIFIER = re.compile(r"([a-zA-Z_][a-zA-Z0-9_]*)_(\d+)_(\d+)")


def _unittest_re() -> None:
    m = _RE_PARSE.match("uavcan.node.Heartbeat.1.0")
    assert m and ("uavcan.node.Heartbeat", "1", "0") == m.groups()
    m = _RE_PARSE.match("uavcan/node\\Heartbeat/1\\0")
    assert m and ("uavcan/node\\Heartbeat", "1", "0") == m.groups()
    m = _RE_PARSE.match("uavcan.node.Heartbeat.1")
    assert m and ("uavcan.node.Heartbeat", "1", None) == m.groups()
    m = _RE_PARSE.match("uavcan.node.Heartbeat")
    assert m and ("uavcan.node.Heartbeat", None, None) == m.groups()
    m = _RE_PARSE.match("uavcan.Heartbeat")
    assert m and ("uavcan.Heartbeat", None, None) == m.groups()

    assert not _RE_PARSE.match("uavcan.node.Heartbeat.1.1.0")
    assert not _RE_PARSE.match("uavcan")


def _unittest_parse() -> None:
    assert (["uavcan", "node", "Heartbeat"], 1, 0) == _parse("uavcan.node.Heartbeat.1.0")
    assert (["uavcan", "node", "Heartbeat"], 1, None) == _parse("uavcan.node.Heartbeat.1")
    assert (["uavcan", "node", "Heartbeat"], None, None) == _parse("uavcan.node.Heartbeat")
    assert (["uavcan", "Heartbeat"], None, None) == _parse("uavcan.Heartbeat")
