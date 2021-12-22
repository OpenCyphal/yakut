# Copyright (c) 2021 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

from __future__ import annotations
import math
from typing import Tuple, List, Sequence, Callable, Any, Dict
import dataclasses
import logging
import textwrap
import click
import pyuavcan
import yakut
from yakut.helpers import EnumParam
from yakut.yaml import EvaluableLoader
from yakut.util import construct_port_id_and_type
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
    ExpressionContextModule("pyuavcan", "https://pyuavcan.readthedocs.io"),
    ExpressionContextModule("numpy", "https://numpy.org", alias="np"),
    ExpressionContextModule("scipy.constants", "https://docs.scipy.org/doc/scipy/reference/constants.html"),
    ExpressionContextModule("scipy.interpolate", "https://docs.scipy.org/doc/scipy/reference/interpolate.html"),
    ExpressionContextModule("scipy.linalg", "https://docs.scipy.org/doc/scipy/reference/linalg.html"),
    ExpressionContextModule("scipy.spatial", "https://docs.scipy.org/doc/scipy/reference/spatial.html"),
]

_EXAMPLES = """
Example: publish constant messages (no embedded expressions, just regular YAML):

\b
    yakut pub uavcan.diagnostic.Record.1.1 '{text: "Hello world!", severity: {value: 4}}' -N3 -T0.1 -P hi
    yakut pub 33:uavcan/si/unit/angle/Scalar_1_0 'radian: 2.31' uavcan.diagnostic.Record.1.1 'text: "2.31 rad"'

Example: publish sinewave with frequency 1 Hz, amplitude 10 meters:

\b
    yakut pub -T 0.01 1234:uavcan.si.unit.length.Scalar.1.0 '{meter: !$ "sin(t * pi * 2) * 10"}'

Example: as above, but control the frequency of the sinewave and its amplitude using sliders 10 and 11
of the first connected controller (use `yakut joystick` to find connected controllers and their axis mappings):

\b
    yakut pub -T 0.01 1234:uavcan.si.unit.length.Scalar.1.0 '{meter: !$ "sin(t * pi * 2 * A(1,10)) * 10 * A(1,11)"}'

Example: publish 3D angular velocity setpoint, thrust setpoint, and the arming switch state;
use positional initialization instead of YAML dicts:

\b
    yakut pub -T 0.1 \\
        5:uavcan.si.unit.angular_velocity.Vector3.1.0 '!$ "[A(1,0)*10, A(1,1)*10, (A(1,2)-A(1,5))*5]"' \\
        6:uavcan.si.unit.power.Scalar.1.0 '!$ A(2,10)*1e3' \\
        7:uavcan.primitive.scalar.Bit.1.0 '!$ T(1,5)'

Example: simulate timestamped measurement of voltage affected by white noise with standard deviation 0.25 V:

\b
    yakut pub -T 0.1 6:uavcan.si.sample.voltage.Scalar.1.0 \\
        '{timestamp: !$ time()*1e6, volt: !$ "A(2,10)*100+normalvariate(0,0.25)"}'
""".strip()

_HELP = f"""
Publish messages on the specified subjects.
Unless the local transport is configured in anonymous node,
the local node will also publish on standard subjects like Heartbeat and provide some standard RPC-services
like GetInfo.

The command accepts a list of space-separated pairs like:

\b
    [SUBJECT_ID:]TYPE_NAME.MAJOR.MINOR  YAML_FIELDS

The first element is a name like `uavcan.node.Heartbeat.1.0` prepended by the subject-ID.
The subject-ID may be omitted if a fixed one is defined for the data type.

The second element specifies the values of the message fields in YAML format (or JSON, which is a subset of YAML).
Missing fields will be left at their default values.
For more info about the format see DSDL API docs at https://pyuavcan.readthedocs.io.

The number of such pairs can be arbitrary; all defined messages will be published synchronously.
If no such pairs are specified, only the heartbeat will be published, unless the local node is anonymous.

The YAML document may embed arbitrary Python expressions that are re-evaluated immediately before publication.
Such expressions are annotated with the YAML tag `!$` (exclamation followed by dollar).
The result of such expression is substituted into the original YAML structure;
as such, the result can be of arbitrary type as long as the final YAML structure can be applied to the specified
DSDL instance.

The YAML-embedded expressions have access to the following variables (type is specified after the colon):

{Executor.SYM_INDEX}: int --- index of the current publication cycle, zero initially.

{Executor.SYM_TIME}: float --- time elapsed since first message (t=n*period).

{Executor.SYM_DTYPE}: Type[pyuavcan.dsdl.CompositeType] --- message class.

{Executor.SYM_CTRL_AXIS}: (controller,axis:int)->float ---
read the normalized value of `axis` from `controller` (e.g., joystick or MIDI fader).
To see the list of available controllers and determine their channel mapping, refer to `yakut joystick --help`.

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


@yakut.subcommand(help=_HELP)
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
    default=2 ** 64 - 1,
    metavar="CARDINAL",
    help=f"Number of publication cycles before exiting normally. Unlimited by default.",
)
@click.option(
    "--priority",
    "-P",
    default=pyuavcan.presentation.DEFAULT_PRIORITY,
    type=EnumParam(pyuavcan.transport.Priority),
    help=f"Priority of published message transfers. [default: {pyuavcan.presentation.DEFAULT_PRIORITY.name}]",
)
@yakut.pass_purser
@yakut.asynchronous
async def publish(
    purser: yakut.Purser,
    message: Sequence[Tuple[str, str]],
    period: float,
    count: int,
    priority: pyuavcan.transport.Priority,
) -> None:
    _logger.debug("period=%s, count=%s, priority=%s, message=%s", period, count, priority, message)
    assert all((isinstance(a, str) and isinstance(b, str)) for a, b in message)
    assert isinstance(period, float) and isinstance(count, int) and isinstance(priority, pyuavcan.transport.Priority)
    if period < 1e-9 or not math.isfinite(period):
        raise click.BadParameter("Period shall be a positive real number of seconds")
    if count <= 0:
        _logger.info("Nothing to do because count=%s", count)
        return

    send_timeout = max(_MIN_SEND_TIMEOUT, period)
    loader = EvaluableLoader(ExpressionContextModule.load(_EXPRESSION_CONTEXT_MODULES))

    def make_publication_factory(
        subject_spec: str, field_spec: str
    ) -> Callable[[pyuavcan.presentation.Presentation], Publication]:
        subject_id, dtype = construct_port_id_and_type(subject_spec)
        # Catch errors as early as possible.
        if issubclass(dtype, pyuavcan.dsdl.ServiceObject):
            raise click.BadParameter(f"Subject spec {subject_spec!r} refers to a service type")
        # noinspection PyTypeChecker
        if subject_id is None and pyuavcan.dsdl.get_fixed_port_id(dtype) is None:
            raise click.UsageError(
                f"Subject-ID is not provided and {pyuavcan.dsdl.get_model(dtype)} does not have a fixed one"
            )
        try:
            evaluator = loader.load_unevaluated(field_spec)
        except ValueError as ex:
            raise click.BadParameter(f"Invalid field spec {field_spec!r}: {ex}") from None
        _logger.debug("Publication spec appears valid: %r", subject_spec)
        return lambda presentation: Publication(
            subject_id=subject_id,
            dtype=dtype,
            evaluator=evaluator,
            presentation=presentation,
            priority=priority,
            send_timeout=send_timeout,
        )

    # This is to perform as much processing as possible before constructing the node.
    # Catching errors early allows us to avoid disturbing the network and peripherals unnecessarily.
    publication_factories = [make_publication_factory(*m) for m in message]

    node = purser.get_node("publish", allow_anonymous=True)
    executor = Executor(
        node=node,
        loader=loader,
        publications=(f(node.presentation) for f in publication_factories),
    )
    try:  # Even if the publication set is empty, we still have to publish the heartbeat.
        _logger.info(
            "Publishing %d subjects with period %.3fs, send timeout %.3fs, count %d, priority %s",
            len(publication_factories),
            period,
            send_timeout,
            count,
            priority.name,
        )
        await executor.run(count=count, period=period)
    finally:
        executor.close()
        if _logger.isEnabledFor(logging.INFO):
            _logger.info("%s", node.presentation.transport.sample_statistics())
            for s in node.presentation.transport.output_sessions:
                ds = s.specifier.data_specifier
                if isinstance(ds, pyuavcan.transport.MessageDataSpecifier):
                    _logger.info("Subject %d: %s", ds.subject_id, s.sample_statistics())


_logger = yakut.get_logger(__name__)
