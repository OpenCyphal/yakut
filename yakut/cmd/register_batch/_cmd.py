# Copyright (c) 2022 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

from __future__ import annotations
import logging
import sys
from typing import TYPE_CHECKING, TextIO, Union, Callable, Any
import click
import pycyphal
import yakut
from yakut.ui import ProgressReporter, show_error, show_warning
from yakut.param.formatter import FormatterHints
from yakut.yaml import Loader
from yakut.int_set_parser import parse_int_set, INT_SET_USER_DOC
from yakut.register import explode_value, get_access_response_metadata
from yakut.util import EXIT_CODE_UNSUCCESSFUL
from ._directive import Directive, SCHEMA_USER_DOC
from ._caller import do_calls, TypeCoercionFailure, Timeout, Skipped, Tag

if TYPE_CHECKING:
    import pycyphal.application
    from uavcan.register import Access_1

_logger = yakut.get_logger(__name__)


Predicate = Callable[["Access_1.Response"], bool]


_PREDICATES = {
    "m": lambda r: r if r.mutable else None,
    "i": lambda r: r if not r.mutable else None,
    "p": lambda r: r if r.persistent else None,
    "v": lambda r: r if not r.persistent else None,
    "mp": lambda r: r if r.mutable and r.persistent else None,
    "mv": lambda r: r if r.mutable and not r.persistent else None,
    "ip": lambda r: r if not r.mutable and r.persistent else None,
    "iv": lambda r: r if not r.mutable and not r.persistent else None,
}


_HELP = f"""
Read/write multiple registers at multiple nodes (useful for network configuration management).

Accepts a YAML/JSON file containing register names and/or values per node; the default is to read from stdin.
Acceptable formats are generated either by register-list (in which case registers will be only read)
or by this command (in which case the specified values will be written).

The registers will be processed strictly sequentially in the order they are specified
(this matters if register access has side effects).

Save configuration parameters into a file (using verbose form for clarity here):

\b
    yakut register-list 125     | yakut register-batch 125 --only=mp > pure_config.json
    yakut register-list 125,    | yakut register-batch     --only=mp > node_125_config.json
    yakut register-list 120-128 | yakut register-batch     --only=mp > network_config.json

To get human-friendly output either add --format=yaml to the last command, or pipe the output through "jq".

You can also remove the node-ID keys using jq '.[]' (this may be useful if you already have an existing file):

\b
    cat node_125_config.json | jq '.[]'

Apply the same parameters to nodes 10,11,12,13,14:

\b
    cat pure_config.json | y rb 10-15

You can also convert a pure config file that is not keyed by node-ID by adding the IDs using jq
(this is obviously not intended for interactive use):

\b
    cat pure_config.json | \\
    jq '. as $in | [range(10;15) | {{key: .|tostring, value: $in}}] | from_entries' | \\
    y rb

...same but applied to one node 125:

\b
    cat pure_config.json | jq '{{"125": .}}' | y rb

Filter output registers by name preserving the node-ID keys; in this case those matching "uavcan*id":

\b
    y rl 125, | y rb | jq 'map_values(with_entries(select(.key | test("uavcan.+id"))))'

Read diagnostic registers from two similar nodes
(protip: save the register names into a file instead of calling register-list each time):

\b
    y rl 124 | y rb 124,125 -oiv

{INT_SET_USER_DOC}
"""


@yakut.subcommand(aliases=["rbat", "rb"], help=_HELP)
@click.argument(
    "node_ids",
    required=False,
    type=lambda x: parse_int_set(x) if x is not None else None,
)
@click.option(
    "--file",
    "-f",
    type=click.File("r"),
    default=sys.stdin,
    help=f"""
Defaults to stdin. Supports YAML/JSON.

{SCHEMA_USER_DOC}
""",
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
@click.option(
    "--optional-register",
    "-r",
    is_flag=True,
    help="""
If modification is requested (i.e., if a value is given),
nodes that report that they don't have such register are silently ignored instead of reporting an error.
Best-effort output will always be produced regardless of this option; that is, it only affects the exit code.
""",
)
@click.option(
    "--detailed",
    "-d",
    count=True,
    help="Display the values as-is, with DSDL type information, do not simplify. Specify twice to include metadata.",
)
@click.option(
    "--only",
    "-o",
    type=click.Choice(list(_PREDICATES.keys()), case_sensitive=False),
    help="""
Filter the output to include only mutable/immutable, persistent/volatile registers.
All registers are always written regardless, this option only affects the final output.
""",
)
@yakut.pass_purser
@yakut.asynchronous()
async def register_batch(
    purser: yakut.Purser,
    node_ids: set[int] | int | None,
    file: TextIO,
    timeout: float,
    optional_register: bool,
    detailed: int,
    only: str | None,
) -> int:
    predicate: Predicate = _PREDICATES[only] if only else lambda _: True
    formatter = purser.make_formatter(FormatterHints(single_document=True))
    representer = _make_representer(detail=detailed)
    with file:
        directive = Directive.load(
            Loader().load(file),
            node_ids=node_ids if not isinstance(node_ids, int) else {node_ids},
        )
    _logger.debug("Loaded directive: %r", directive)
    with purser.get_node("register_batch", allow_anonymous=False) as node:
        with ProgressReporter() as prog:
            result = await do_calls(node, prog, directive=directive, timeout=timeout)
        if _logger.isEnabledFor(logging.INFO):
            _logger.info("%s", node.presentation.transport.sample_statistics())

    from uavcan.register import Access_1

    success = True

    def error(msg: str) -> None:
        nonlocal success
        success = False
        show_error(msg)

    for node_id, per_node in result.responses_per_node.items():
        failed_count = 0
        for reg_name, response in per_node.items():
            if isinstance(response, Access_1.Response) and not response.value.empty:
                continue
            failed_count += 1
            prefix = f"{node_id}:{reg_name!r}: "
            if isinstance(response, Access_1.Response) and response.value.empty:
                if optional_register:
                    show_warning(prefix + "No such register, ignored as requested")
                else:
                    error(prefix + "No such register")
            elif isinstance(response, TypeCoercionFailure):
                error(prefix + f"Original value unchanged because coercion failed: {response.msg}")
            elif isinstance(response, Timeout):
                error(prefix + "Timed out and gave up on this node")
            elif isinstance(response, Skipped):
                assert not success
            else:
                assert False, response
        _logger.info("Node %r: total %r, failed %r", node_id, len(per_node), failed_count)
        if failed_count > 0:
            show_warning(f"{node_id}: {failed_count} failed of {len(per_node)} total. Output incomplete.")

    final: Any = {
        node_id: {
            reg_name: representer(response)
            for reg_name, response in per_node.items()
            if isinstance(response, Access_1.Response) and predicate(response)
        }
        for node_id, per_node in result.responses_per_node.items()
    }
    if isinstance(node_ids, int):
        final = final[node_ids]
    sys.stdout.write(formatter(final))
    sys.stdout.flush()
    return 0 if success else EXIT_CODE_UNSUCCESSFUL


def _make_representer(detail: int) -> Callable[[Union[Tag, "Access_1.Response"]], Any]:
    from uavcan.register import Access_1

    def represent(response: Union[Tag, Access_1.Response]) -> Any:
        return (
            explode_value(
                response.value,
                simplify=detail < 1,
                metadata=get_access_response_metadata(response) if detail > 1 else None,
            )
            if isinstance(response, Access_1.Response)
            else None
        )

    return represent
