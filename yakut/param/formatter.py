# Copyright (c) 2019 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

from __future__ import annotations
import typing
from collections.abc import Mapping, Collection
import click

Formatter = typing.Callable[[typing.Any], str]
FormatterFactory = typing.Callable[[], Formatter]


def formatter_factory_option(f: typing.Callable[..., typing.Any]) -> typing.Callable[..., typing.Any]:
    def validate(ctx: click.Context, param: object, value: str) -> FormatterFactory:
        _ = ctx, param
        try:
            return _FORMATTERS[value.upper()]
        except LookupError:
            raise click.BadParameter(f"Invalid format name: {value!r}") from None

    choices = list(_FORMATTERS.keys())
    default = choices[0]
    doc = f"""
The format of data printed into stdout.
This option is only relevant for commands that generate structured outputs, like pub or call; other commands ignore it.

The final representation of the output data is constructed from an intermediate "builtin-based" representation,
which is a simplified form that is stripped of the detailed DSDL type information, like JSON.
For more info please read the PyUAVCAN documentation on builtin-based representations.

YAML separates objects with `---`.

JSON and TSV (tab separated values) keep exactly one object per line.

TSV is intended for use with third-party software
such as computer algebra systems or spreadsheet processors.

TSVH is just TSV with the header included.
"""
    f = click.option(
        "--format",
        "-F",
        "formatter_factory",
        envvar="YAKUT_FORMAT",
        type=click.Choice(choices, case_sensitive=False),
        callback=validate,
        default=default,
        show_default=True,
        help=doc,
    )(f)
    return f


def _make_yaml_formatter() -> Formatter:
    from yakut.yaml import Dumper

    dumper = Dumper(explicit_start=True)
    return dumper.dumps


def _make_json_formatter() -> Formatter:
    # We prefer simplejson over the standard json because the native json lacks important capabilities:
    #  - simplejson preserves dict ordering, which is very important for UX.
    #  - simplejson supports Decimal.
    import simplejson as json  # type: ignore

    return lambda data: typing.cast(str, json.dumps(data, ensure_ascii=False, separators=(",", ":")))


def flatten(
        d: typing.Union[typing.Dict[typing.Any, typing.Any], typing.Collection[typing.Any]],
        parent_key: str = "",
        sep: str = ".",
) -> typing.Dict[str, typing.Any]:
    if isinstance(d, Mapping):
        items: typing.List[typing.Tuple[str, typing.Any]] = []
        for k, v in d.items():
            new_key = str(parent_key) + sep + str(k) if parent_key else str(k)
            if isinstance(v, Mapping) or (isinstance(v, Collection) and not isinstance(v, str)):
                for_extension = flatten(v, new_key, sep=sep)
                if for_extension is not None:
                    items.extend(for_extension.items())
                else:
                    print(v)
            else:
                items.append((new_key, v))
        return dict(items)
    elif isinstance(d, Collection) and not isinstance(d, str):
        items = []
        for i, v in enumerate(d):
            new_key = str(parent_key) + sep + str(f"[{i}]") if parent_key else str(f"[{i}]")
            if isinstance(v, Mapping) or (isinstance(v, Collection) and not isinstance(v, str)):
                for_extension = flatten(v, new_key, sep=sep)
                if for_extension is not None:
                    items.extend(for_extension.items())
                else:
                    print(v)
            else:
                items.append((new_key, v))
        return dict(items)
    else:
        return {}


is_first_time = True


def tsv_format_function(data: typing.Dict[typing.Any, typing.Any]) -> str:
    return "\t".join([str(v) for k, v in flatten(data).items()])


def tsv_format_function_with_header(data: typing.Dict[typing.Any, typing.Any]) -> str:
    global is_first_time
    if is_first_time:
        is_first_time = False
        return (
                "\t".join([str(k) for k, v in flatten(data).items()])
                + "\n"
                + "\t".join([str(v) for k, v in flatten(data).items()])
        )
    else:
        return "\t".join([str(v) for k, v in flatten(data).items()])


def _make_tsv_formatter() -> Formatter:
    return tsv_format_function


def _make_tsvh_formatter() -> Formatter:
    return tsv_format_function_with_header


_FORMATTERS = {
    "YAML": _make_yaml_formatter,
    "JSON": _make_json_formatter,
    "TSV": _make_tsv_formatter,
    "TSVH": _make_tsvh_formatter,
}


def _unittest_formatter() -> None:
    obj = {
        2345: {
            "abc": {
                "def": [123, 456],
            },
            "ghi": 789,
        }
    }
    assert (
            _FORMATTERS["YAML"]()(obj)
            == """---
2345:
  abc:
    def: [123, 456]
  ghi: 789
"""
    )
    assert _FORMATTERS["JSON"]()(obj) == '{"2345":{"abc":{"def":[123,456]},"ghi":789}}'
