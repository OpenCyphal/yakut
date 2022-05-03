# Copyright (c) 2019 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

from __future__ import annotations
import sys
import dataclasses
import logging
from typing import Callable, Any, cast
from collections.abc import Mapping, Collection
import click


@dataclasses.dataclass(frozen=True)
class FormatterHints:
    single_document: bool = False
    """
    If true, document separators will not be emitted (if applicable).
    """


Formatter = Callable[[Any], str]
"""
The output represents a complete document with the terminating newline if such is necessary.
The caller need not add anything.
If sending this to stdout, do not use print() as-is because it will add an extra newline at the end.
"""

FormatterFactory = Callable[[FormatterHints], Formatter]


def formatter_factory_option(f: Callable[..., Any]) -> Callable[..., Any]:
    override: str | None = None

    def install_override(_ctx: click.Context, _param: click.Parameter, value: str) -> None:
        nonlocal override
        override = value or override

    def validate(ctx: click.Context, param: click.Parameter, value: str) -> FormatterFactory:
        try:
            return _FORMATTERS[(override or value).upper()]
        except LookupError:
            raise click.BadParameter(f"Invalid format name: {value!r}", ctx=ctx, param=param) from None

    doc = f"""
The format of data printed to stdout.
This option is only relevant for commands that produce data (sub, call, etc.).

The final representation of the output data is constructed from an intermediate "builtin-based" representation,
which is a simplified form that is stripped of the detailed DSDL type information, like JSON.
For more info please read the PyCyphal documentation on builtin-based representations.

Option "auto" (default) selects YAML if the output is shown on the terminal for the benefit of the user;
if the output is redirected (e.g., piped to another command or to a file),
JSON is selected to enable compatibility with jq and other 3rd-party stream processing tools.
It helps to remember that JSON is a subset of YAML.

YAML separates objects with `---`.
JSON and TSV (tab separated values) keep exactly one object per line.

TSV is intended for use with third-party software
such as computer algebra systems or spreadsheet processors.

TSVH is just TSV with the header included.

TSVFC is TSVH with extra column for curly braces and square brackets. These are extra format columns that help the
reader understand the structure of the data without looking at the headers.
"""
    f = click.option(
        "--format",
        "-F",
        "formatter_factory",
        envvar="YAKUT_FORMAT",
        type=click.Choice(list(_FORMATTERS.keys()), case_sensitive=False),
        callback=validate,
        default=list(_FORMATTERS.keys())[0],
        show_default=True,
        help=doc,
    )(f)

    def shortcut(opt: str) -> None:
        nonlocal f
        f = click.option(
            f"--{opt}",
            "-" + opt[0],
            flag_value=opt,
            callback=install_override,
            help=f"Same as --format={opt}",
            is_eager=True,
            expose_value=False,
        )(f)

    shortcut("yaml")
    shortcut("json")
    shortcut("tsvh")
    return f


def _make_yaml_formatter(hints: FormatterHints) -> Formatter:
    from yakut.yaml import Dumper

    dumper = Dumper(explicit_start=not hints.single_document)
    return dumper.dumps


def _make_json_formatter(_hints: FormatterHints) -> Formatter:
    # We prefer simplejson over the standard json because the native json lacks important capabilities:
    #  - simplejson preserves dict ordering, which is very important for UX.
    #  - simplejson supports Decimal.
    import simplejson as json  # type: ignore

    return lambda data: cast(str, json.dumps(data, ensure_ascii=False, separators=(",", ":"))) + _NEWLINE


def _insert_format_specifier(
    items: list[tuple[str, Any]],
    key: str,
    instance: Collection[Any] | Mapping[Any, Any],
    is_start: bool = True,
) -> None:
    is_list = isinstance(instance, Collection) and not isinstance(instance, str)
    is_dictionary = isinstance(instance, Mapping)
    if is_start:
        if is_dictionary:
            items.append((key + "{", "{"))
        elif is_list:
            items.append((key + "[", "["))
    else:
        if is_dictionary:
            items.append((key + "}", "}"))
        elif is_list:
            items.append((key + "]", "]"))


def _flatten_start(
    outer: Any,
    parent_key: str = "",
    sep: str = ".",
    with_format_specifiers: bool = False,
) -> dict[str, Any]:
    def flatten(data: Any, parent_key: str = "") -> dict[str, Any]:
        def add_item(items: list[tuple[str, Any]], new_key: str, v: Mapping[Any, Any] | Collection[Any]) -> None:
            if with_format_specifiers:
                _insert_format_specifier(items, new_key, v)
            if isinstance(v, Mapping) or (isinstance(v, Collection) and not isinstance(v, str)):
                for_extension = flatten(v, new_key)
                if for_extension is not None:
                    # noinspection PyTypeChecker
                    items.extend(for_extension.items())
            else:
                items.append((new_key, v))
            if with_format_specifiers:
                _insert_format_specifier(items, new_key, v, is_start=False)

        if isinstance(data, Mapping):
            items: list[tuple[str, Any]] = []
            for k, v in data.items():
                new_key = parent_key + sep + str(k) if parent_key else str(k)
                add_item(items, new_key, v)
            return dict(items)
        if isinstance(data, Collection) and not isinstance(data, str):
            items = []
            for i, v in enumerate(data):
                new_key = parent_key + sep + f"[{i}]" if parent_key else str(f"[{i}]")
                add_item(items, new_key, v)
            return dict(items)
        return {}

    return flatten(outer, parent_key)


def _make_tsv_formatter(hints: FormatterHints) -> Formatter:
    # TODO: if single_document, transpose the top-level dict to have the keys on the leftmost row.
    # Transpose lists in a similar manner.
    _ = hints  # TODO not used yet

    def tsv_format_function(data: Any) -> str:
        return "\t".join(str(v) for k, v in _flatten_start(data).items()) + _NEWLINE

    return tsv_format_function


def _make_tsvh_formatter_factory(with_format_specifiers: bool) -> FormatterFactory:
    def make_tsvh_formatter(hints: FormatterHints) -> Formatter:
        _ = hints  # TODO see above
        is_first_time = True

        def tsv_format_function_with_header(data: Any) -> str:
            nonlocal is_first_time
            if is_first_time:
                is_first_time = False
                return _NEWLINE.join(
                    (
                        "\t".join(
                            str(k)
                            for k, v in _flatten_start(data, with_format_specifiers=with_format_specifiers).items()
                        ),
                        "\t".join(
                            str(v)
                            for k, v in _flatten_start(data, with_format_specifiers=with_format_specifiers).items()
                        ),
                        "",
                    )
                )
            return (
                "\t".join(
                    str(v) for k, v in _flatten_start(data, with_format_specifiers=with_format_specifiers).items()
                )
                + _NEWLINE
            )

        return tsv_format_function_with_header

    return make_tsvh_formatter


def _make_auto(hints: FormatterHints) -> Formatter:
    fac = _make_yaml_formatter if sys.stdout.isatty() else _make_json_formatter
    _logger.debug("Automatically selected formatter: %r", fac)
    return fac(hints)


_FORMATTERS = {
    "AUTO": _make_auto,
    "YAML": _make_yaml_formatter,
    "JSON": _make_json_formatter,
    "TSV": _make_tsv_formatter,
    "TSVH": _make_tsvh_formatter_factory(with_format_specifiers=False),
    "TSVFC": _make_tsvh_formatter_factory(with_format_specifiers=True),
}

_NEWLINE = "\n"

_logger = logging.getLogger(__name__)


def _unittest_formatter() -> None:
    default_hints = FormatterHints()

    obj = {
        2345: {
            "abc": {
                "def": [123, 456],
            },
            "ghi": 789,
        }
    }
    assert (
        _FORMATTERS["YAML"](default_hints)(obj)
        == """---
2345:
  abc:
    def: [123, 456]
  ghi: 789
"""
    )
    assert _FORMATTERS["JSON"](default_hints)(obj) == '{"2345":{"abc":{"def":[123,456]},"ghi":789}}\n'
    assert _FORMATTERS["TSV"](default_hints)(obj) == "123\t456\t789\n"
    tsvh_formatter = _FORMATTERS["TSVH"](default_hints)
    # first time should include a header
    assert tsvh_formatter(obj) == "2345.abc.def.[0]\t2345.abc.def.[1]\t2345.ghi\n123\t456\t789\n"
    # subsequent calls shouldn't include a header
    assert tsvh_formatter(obj) == "123\t456\t789\n"
    from decimal import Decimal
    from math import nan

    obj = {
        142: {
            "_meta_": {
                "timestamp": {"system": Decimal("1640611164.396007"), "monotonic": Decimal("4765.594161")},
                "priority": "nominal",
                "transfer_id": 28,
                "source_node_id": 21,
            },
            "timestamp": {"microsecond": 309697890},
            "value": {
                "kinematics": {
                    "angular_position": {"radian": nan},
                    "angular_velocity": {"radian_per_second": 0.0},
                    "angular_acceleration": {"radian_per_second_per_second": 0.0},
                },
                "torque": {"newton_meter": nan},
            },
        }
    }
    tsvfc_formatter = _FORMATTERS["TSVFC"](default_hints)
    assert (
        tsvfc_formatter(obj) == "142{	142._meta_{	142._meta_.timestamp{"
        "	142._meta_.timestamp.system	142._meta_.timestamp.monotonic"
        "	142._meta_.timestamp}	142._meta_.priority	142._meta_.transfer_id"
        "	142._meta_.source_node_id	142._meta_}	142.timestamp{	142.timestamp.microsecond"
        "	142.timestamp}	142.value{	142.value.kinematics{	142.value.kinematics.angular_position{"
        "	142.value.kinematics.angular_position.radian	142.value.kinematics.angular_position}"
        "	142.value.kinematics.angular_velocity{	142.value.kinematics.angular_velocity.radian_per_second"
        "	142.value.kinematics.angular_velocity}	142.value.kinematics.angular_acceleration{"
        "	142.value.kinematics.angular_acceleration.radian_per_second_per_second"
        "	142.value.kinematics.angular_acceleration}	142.value.kinematics}	142.value.torque{"
        "	142.value.torque.newton_meter	142.value.torque}	142.value}	142}\n{	{	{"
        "	1640611164.396007	4765.594161	}	nominal	28	21	}"
        "	{	309697890	}	{	{	{	nan	}	{	0.0	}"
        "	{	0.0	}	}	{	nan	}	}	}\n"
    )
    assert (
        _FORMATTERS["TSV"](default_hints)(obj)
        == "1640611164.396007\t4765.594161\tnominal\t28\t21\t309697890\tnan\t0.0\t0.0\tnan\n"
    )

    assert (
        _FORMATTERS["TSVH"](default_hints)(obj)
        == "142._meta_.timestamp.system\t142._meta_.timestamp.monotonic\t142._meta_.priority\t"
        "142._meta_.transfer_id\t142._meta_.source_node_id\t142.timestamp.microsecond\t"
        "142.value.kinematics.angular_position.radian"
        "\t142.value.kinematics.angular_velocity.radian_per_second\t142.value.kinematics.angular_acceleration."
        "radian_per_second_per_second\t142.value.torque.newton_meter"
        "\n1640611164.396007\t4765.594161\tnominal\t2"
        "8\t21\t309697890\tnan\t0.0\t0.0\tnan\n"
    )
