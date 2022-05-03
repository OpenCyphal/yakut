# Copyright (c) 2021 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

from __future__ import annotations
import math
from typing import Tuple, List, Sequence, Callable, Any, Dict
import dataclasses
import logging
import textwrap
from functools import lru_cache
import click
import pycyphal
import yakut
from yakut.enum_param import EnumParam
from yakut.yaml import EvaluableLoader
from yakut.subject_specifier_processor import process_subject_specifier, SubjectResolver
from ._executor import Executor, Publication

_MIN_SEND_TIMEOUT = 0.1
"""
With a slow garbage-collected language like Python, having a smaller timeout does not make practical sense.
This may be made configurable later.
"""


@dataclasses.dataclass(frozen=True)
class ExpressionContextModule:
    """
    Defines a Python module that is imported and available for use within YAML-embedded user expressions.
    """

    module_name: str
    docs_uri: str
    alias: str = ""
    wildcard: bool = False

    def __str__(self) -> str:
        if self.wildcard:
            body = f"from {self.module_name} import *"
        elif self.alias:
            body = f"import {self.module_name} as {self.alias}"
        else:
            body = f"import {self.module_name}"
        return body.ljust(25) + f"# {self.docs_uri}"

    @staticmethod
    def load(what: Sequence[ExpressionContextModule]) -> Dict[str, Any]:
        import inspect

        out: Dict[str, Any] = {}
        for ecm in what:
            _logger.debug("Importing: %r", ecm)
            mod = __import__(ecm.module_name)
            out[ecm.module_name] = mod
            if ecm.alias:
                out[ecm.alias] = mod
            if ecm.wildcard:
                out.update({name: member for name, member in inspect.getmembers(mod) if not name.startswith("_")})

        _logger.debug("Expression context contains %d items (listed on the next line):\n%s", len(out), list(out))
        return out


_EXPRESSION_CONTEXT_MODULES = [
    ExpressionContextModule("random", "https://docs.python.org/library/random.html", wildcard=True),
    ExpressionContextModule("time", "https://docs.python.org/library/time.html", wildcard=True),
    ExpressionContextModule("math", "https://docs.python.org/library/math.html", wildcard=True),
    ExpressionContextModule("os", "https://docs.python.org/library/os.html"),
    ExpressionContextModule("pycyphal", "https://pycyphal.readthedocs.io"),
    ExpressionContextModule("numpy", "https://numpy.org", alias="np"),
    ExpressionContextModule("scipy.constants", "https://docs.scipy.org/doc/scipy/reference/constants.html"),
    ExpressionContextModule("scipy.interpolate", "https://docs.scipy.org/doc/scipy/reference/interpolate.html"),
    ExpressionContextModule("scipy.linalg", "https://docs.scipy.org/doc/scipy/reference/linalg.html"),
    ExpressionContextModule("scipy.spatial", "https://docs.scipy.org/doc/scipy/reference/spatial.html"),
]

_EXAMPLES = """
Example: publish constant messages (no embedded expressions, just regular YAML):

\b
    yakut pub uavcan.diagnostic.record '{text: "Hello world!", severity: {value: 4}}' -N3 -T0.1 -P hi
    yakut pub 33:uavcan.si.unit.angle.scalar 2.31 uavcan.diagnostic.Record 'text: "2.31 radian"'

Example: publish sinewave with frequency 1 Hz, amplitude 10 meters:

\b
    yakut pub -T 0.01 1234:uavcan.si.unit.length.scalar '!$ "sin(t * pi * 2) * 10"'

Example: as above, but control the frequency of the sinewave and its amplitude using sliders 10 and 11
of the first connected controller (use `yakut joystick` to find connected controllers and their axis mappings):

\b
    yakut pub -T 0.01 1234:uavcan.si.unit.length.Scalar '{meter: !$ "sin(t * pi * 2 * A(1,10)) * 10 * A(1,11)"}'

Example: publish 3D angular velocity setpoint, thrust setpoint, and the arming switch state:

\b
    yakut pub -T 0.1 \\
        5:uavcan.si.unit.angular_velocity.Vector3 '!$ "[A(1,0)*10, A(1,1)*10, (A(1,2)-A(1,5))*5]"' \\
        6:uavcan.si.unit.power.Scalar '!$ A(2,10)*1e3' \\
        7:uavcan.primitive.scalar.Bit '!$ T(1,5)'

Example: simulate timestamped measurement of voltage affected by white noise with standard deviation 0.25 V:

\b
    yakut pub -T 0.1 6:uavcan.si.sample.voltage.scalar \\
        '{timestamp: !$ time()*1e6, volt: !$ "A(2,10)*100+normalvariate(0,0.25)"}'
""".strip()

_HELP = f"""
Publish messages on the specified subjects.
Unless the local transport is configured in anonymous node,
the local node will also publish on standard subjects like Heartbeat and provide some standard RPC-services
like GetInfo.

The command accepts a list of space-separated pairs like:

\b
    SUBJECT_SPECIFIER  YAML_FIELDS

The first element -- SUBJECT_SPECIFIER -- defines the subject-ID and/or the data type name;
refer to the subscription command for details.

The second element -- YAML_FIELDS -- specifies the values of the message fields in YAML format
(or JSON, which is a subset of YAML).
Missing fields will be left at their default values.
For more info about the format see DSDL API docs at https://pycyphal.readthedocs.io.

The number of such pairs can be arbitrary; all defined messages will be published synchronously.
If no such pairs are specified, only the heartbeat will be published, unless the local node is anonymous.

The YAML document may embed arbitrary Python expressions that are re-evaluated immediately before publication.
Such expressions are annotated with the YAML tag `!$` (exclamation followed by dollar).
The result of such expression is substituted into the original YAML structure;
as such, the result can be of arbitrary type as long as the final YAML structure can be applied to the specified
DSDL instance.

The YAML-embedded expressions have access to the following variables:

{Executor.SYM_INDEX}: int --- index of the current publication cycle, zero initially.

{Executor.SYM_TIME}: float --- time elapsed since first message (t=n*period).

{Executor.SYM_DTYPE}: type --- message class.

{Executor.SYM_CTRL_AXIS}: (controller,axis:int)->float ---
read the normalized value of `axis` from `controller` (e.g., joystick or MIDI fader).
To see the list of available controllers and determine their channel mapping, refer to `yakut joystick`.

{Executor.SYM_CTRL_BUTTON}: (controller,button:int)->bool ---
read the state of `button` from `controller` (true while held down).

{Executor.SYM_CTRL_TOGGLE}: (controller,toggle:int)->bool ---
read the state of `toggle` from `controller`.

The following Python modules are imported and usable within embedded expressions;
refer to their API docs for usage info:

\b
{textwrap.indent(chr(0x0A).join(map(str, _EXPRESSION_CONTEXT_MODULES)), " " * 4)}

{_EXAMPLES}
"""


def _validate_message_spec(
    ctx: click.Context,
    param: click.Parameter,
    value: Tuple[str, ...],
) -> List[Tuple[str, str]]:
    if len(value) % 2 != 0:
        raise click.BadParameter(
            f"Message specifier shall have an even number of paired arguments (found {len(value)} arguments)",
            ctx=ctx,
            param=param,
        )
    return [(s, f) for s, f in (value[i : i + 2] for i in range(0, len(value), 2))]  # pylint: disable=R1721


@yakut.subcommand(help=_HELP, aliases=["pub", "p"])
@click.argument(
    "message",
    type=str,
    callback=_validate_message_spec,
    metavar="SUBJECT FIELDS [SUBJECT FIELDS]...",
    nargs=-1,
)
@click.option(
    "--period",
    "-T",
    type=float,
    default=1.0,
    show_default=True,
    metavar="SECONDS",
    help=f"""
Message publication period.
All messages are published synchronously, so the period setting applies to all specified subjects.
The send timeout equals the period as long as it is not less than {_MIN_SEND_TIMEOUT} seconds.
""",
)
@click.option(
    "--count",
    "-N",
    type=int,
    default=2**64 - 1,
    metavar="CARDINAL",
    help=f"Number of publication cycles before exiting normally. Unlimited by default.",
)
@click.option(
    "--priority",
    "-P",
    default=pycyphal.presentation.DEFAULT_PRIORITY,
    type=EnumParam(pycyphal.transport.Priority),
    help=f"Priority of published message transfers. [default: {pycyphal.presentation.DEFAULT_PRIORITY.name}]",
)
@yakut.pass_purser
@yakut.asynchronous(interrupted_ok=True)
async def publish(
    purser: yakut.Purser,
    message: Sequence[Tuple[str, str]],
    period: float,
    count: int,
    priority: pycyphal.transport.Priority,
) -> None:
    _logger.debug("period=%s, count=%s, priority=%s, message=%s", period, count, priority, message)
    assert all((isinstance(a, str) and isinstance(b, str)) for a, b in message)
    assert isinstance(period, float) and isinstance(count, int) and isinstance(priority, pycyphal.transport.Priority)
    if period < 1e-9 or not math.isfinite(period):
        raise click.BadParameter("Period shall be a positive real number of seconds")
    if count <= 0:
        _logger.warning("Nothing to do because count=%s", count)
        return
    try:
        from pycyphal.application import Node
    except ImportError as ex:
        from yakut.cmd.compile import make_usage_suggestion

        raise click.ClickException(make_usage_suggestion(ex.name))

    finalizers: list[Callable[[], None]] = []
    try:
        # Parse the field specs we were given to validate syntax.
        # Do this early before other resources are initialized.
        yaml_loader = EvaluableLoader(ExpressionContextModule.load(_EXPRESSION_CONTEXT_MODULES))
        evaluators: list[Callable[..., Any]] = []
        for _, field_spec in message:
            try:
                evaluators.append(yaml_loader.load_unevaluated(field_spec))
            except ValueError as ex:
                raise click.BadParameter(f"Invalid field spec {field_spec!r}: {ex}") from None

        # Node construction should be delayed as much as possible to avoid unnecessary interference
        # with the bus and hardware. This is why we use the factory here instead of constructing the node eagerly.
        @lru_cache(None)
        def get_node() -> Node:
            node = purser.get_node("publish", allow_anonymous=True)
            finalizers.append(node.close)
            return node

        @lru_cache(None)
        def get_subject_resolver() -> SubjectResolver:
            node = get_node()
            if node.id is None:
                raise click.ClickException(
                    f"Cannot use automatic discovery because the local node is anonymous, "
                    f"so it cannot access the introspection services on remote nodes. "
                    f"You need to either fully specify the subjects explicitly or assign a local node-ID."
                )
            sr = SubjectResolver(node)
            finalizers.append(sr.close)
            return sr

        # Resolve subject-IDs and dtypes. This may or may not require the local node.
        subject_id_dtype_pairs: list[tuple[int, Any]] = [
            await process_subject_specifier(subject_spec, get_subject_resolver) for subject_spec, _ in message
        ]

        # We delayed node construction as much as possible. It may already be constructed if subject resolver was used.
        send_timeout = max(_MIN_SEND_TIMEOUT, period)
        node = get_node()
        publications = [
            Publication(
                subject_id=sbj_id,
                dtype=dty,
                evaluator=evl,
                node=node,
                priority=priority,
                send_timeout=send_timeout,
            )
            for (sbj_id, dty), evl in zip(subject_id_dtype_pairs, evaluators)
        ]
        executor = Executor(loader=yaml_loader, publications=publications)
        finalizers.append(executor.close)

        # Everything is ready, the node can be started now. It will be stopped during finalization.
        node.start()
        _logger.info(
            "Publishing %d subjects with period %.3fs, send timeout %.3fs, count %d, priority %s",
            len(message),
            period,
            send_timeout,
            count,
            priority.name,
        )
        try:
            await executor.run(count=count, period=period)
        finally:
            _log_final_report(node.presentation)
    finally:
        pycyphal.util.broadcast(finalizers[::-1])()


def _log_final_report(presentation: pycyphal.presentation.Presentation) -> None:
    if _logger.isEnabledFor(logging.INFO):
        _logger.info("%s", presentation.transport.sample_statistics())
        for s in presentation.transport.output_sessions:
            ds = s.specifier.data_specifier
            if isinstance(ds, pycyphal.transport.MessageDataSpecifier):
                _logger.info("Subject %d: %s", ds.subject_id, s.sample_statistics())


_logger = yakut.get_logger(__name__)
