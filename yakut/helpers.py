# Copyright (c) 2020 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

import enum
import typing
import click


class EnumParam(click.Choice):
    """
    A parameter that allows the user to select one of the enum options.
    The selection is case-insensitive and abbreviations are supported out of the box:
    F, foo, and FOO_BAR are all considered equivalent as long as there are no ambiguities.
    """

    def __init__(self, e: enum.EnumMeta) -> None:
        self._enum = e
        super().__init__(list(e.__members__), case_sensitive=False)

    def convert(
        self,
        value: typing.Union[str, enum.Enum],
        param: typing.Optional[click.Parameter],
        ctx: typing.Optional[click.Context],
    ) -> typing.Any:
        if isinstance(value, enum.Enum):  # This is to support default enum options.
            value = value.name
        assert isinstance(value, str)
        candidates: typing.List[enum.Enum] = [  # type: ignore
            x for x in self._enum if x.name.upper().startswith(value.upper())
        ]
        if len(candidates) == 0:
            raise click.BadParameter(f"Value {value!r} is not a valid choice for {list(self._enum.__members__)}")
        if len(candidates) > 1:
            raise click.BadParameter(f"Value {value!r} is ambiguous; possible matches: {[x.name for x in candidates]}")
        return candidates[0]
