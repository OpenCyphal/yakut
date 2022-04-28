# Copyright (c) 2022 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

from __future__ import annotations
import sys
import dataclasses
from typing import TYPE_CHECKING, TextIO, Optional, Callable, TypeVar
import click
import pycyphal
import yakut
from yakut.progress import ProgressReporter
from yakut.param.formatter import FormatterHints
from yakut.yaml import Loader
from yakut.util import compose
from ._directive import Directive
from ._caller import do_calls

if TYPE_CHECKING:
    import pycyphal.application
    from uavcan.register import Access_1

T = TypeVar("T")

_logger = yakut.get_logger(__name__)


@dataclasses.dataclass
class Result:
    responses_per_node: dict[int, list[Optional["Access_1.Response"]]] = dataclasses.field(default_factory=dict)
    errors: list[str] = dataclasses.field(default_factory=list)


Filter = Callable[["Access_1.Response"], Optional["Access_1.Response"]]


def _make_mutability_filter(mutable: bool) -> Filter:
    def fun(resp: "Access_1.Response") -> Optional["Access_1.Response"]:
        return resp if mutable == resp.mutable else None

    return fun


def _make_persistence_filter(persistent: bool) -> Filter:
    def fun(resp: "Access_1.Response") -> Optional["Access_1.Response"]:
        return resp if persistent == resp.persistent else None

    return fun


def _eye(x: T) -> T:
    return x


@yakut.subcommand(aliases=["rbat", "rb"])
@click.argument(
    "register_file",
    type=click.File("r"),
    default=sys.stdin,
)
@click.option(
    "--timeout",
    "-T",
    type=float,
    default=pycyphal.presentation.DEFAULT_SERVICE_REQUEST_TIMEOUT,
    show_default=True,
    metavar="SECONDS",
    help="Service response timeout.",
)
@click.option("--only-mutable", "+M", "mutability_filter", flag_value=_make_mutability_filter(True))
@click.option("--only-immutable", "-M", "mutability_filter", flag_value=_make_mutability_filter(False))
@click.option("--only-persistent", "+P", "persistence_filter", flag_value=_make_persistence_filter(True))
@click.option("--only-volatile", "-P", "persistence_filter", flag_value=_make_persistence_filter(False))
@yakut.pass_purser
@yakut.asynchronous()
async def register_batch(
    purser: yakut.Purser,
    register_file: TextIO,
    timeout: float,
    mutability_filter: Filter,
    persistence_filter: Filter,
) -> int:
    """
    Read/write multiple registers at multiple nodes (useful for network configuration management).

    Accepts a YAML/JSON file containing register names and/or values per node; the default is to read from stdin.
    Acceptable formats are generated either by register-list (in which case registers will be only read)
    or by this command (in which case the specified values will be written).

    Save registers from multiple nodes into a file (using verbose form for clarity here):

    \b
        yakut register-list 42,45-50 |                          \\
        yakut register-dump --only-mutable --only-persistent    \\
        > network_config.json

    To get human-friendly output either add --format=yaml to the last command, or pipe the output through "jq".

    Save registers from one node into a file not keyed by node-ID (using shorthand commands here for brevity):

    \b
        y rl 42 | y rdump +MP | jq '.[]' > single_node_config.json
    """
    flt: Filter = compose(mutability_filter or _eye, persistence_filter or _eye)
    with register_file:
        directive = Directive.load(Loader().load(register_file))
    formatter = purser.make_formatter(FormatterHints(single_document=True))
    with purser.get_node("register_batch", allow_anonymous=False) as node:
        with ProgressReporter() as prog:
            result = await do_calls(node, prog, directive=directive, timeout=timeout)
    success = False
    # TODO report errors
    # FIXME
    sys.stdout.write(formatter(result.responses_per_node))
    sys.stdout.flush()
    return 0 if success else 1
