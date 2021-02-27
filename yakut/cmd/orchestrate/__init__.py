# Copyright (c) 2021 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

from __future__ import annotations
import sys
import signal
import logging
from typing import Any
import click
import yakut

from ._schema import Composition as Composition
from ._schema import load_ast as load_ast
from ._schema import load_composition as load_composition

from ._executor import Context as Context
from ._executor import Stack as Stack
from ._executor import ErrorCode as ErrorCode
from ._executor import exec_file as exec_file
from ._executor import exec_composition as exec_composition


_logger = logging.getLogger(__name__)


def _indent(text: str) -> str:
    import textwrap

    return textwrap.indent(text, " " * 4)


# language=YAML
EXAMPLE_BASIC = """
$=:
- sleep 10
- echo $GREETING    # Concurrent execution!
-                   # Join statement, wait for "sleep" to finish.
- $=: echo $GREETING
  GREETING: bar     # Overrides the outer scope.
- ?=:               # This statement fails but error suppressed.
    $=: sleep 1
    .=: unknown-command-failure-ignored
-                   # Another join barrier.
- exit 88
.=: echo finalizer
GREETING: Hello world!
""".strip()
EXAMPLE_BASIC_STDOUT = """
Hello world!
bar
finalizer
""".strip()
EXAMPLE_BASIC_EXIT_CODE = 88


# language=YAML
EXAMPLE_EXTERNAL = """
external=:
- vars.orc.yaml   # Definition below
- echo.orc.yaml   # Definition below
.=: exit $EXIT_CODE
""".strip()
# language=YAML
EXAMPLE_EXTERNAL_VARS = """
# vars.orc.yaml
VARIABLE: This is my variable.
EXIT_CODE: 99
""".strip()
# language=YAML
EXAMPLE_EXTERNAL_ECHO = """
# echo.orc.yaml
$=: |
  python -c "from os import getenv; print(getenv('VARIABLE'))"
""".strip()
EXAMPLE_EXTERNAL_STDOUT = """
This is my variable.
""".strip()
EXAMPLE_EXTERNAL_EXIT_CODE = 99


# language=YAML
EXAMPLE_PUB_SUB = """
#!/usr/bin/env -S yakut orchestrate
# Compile DSDL and launch a pair of pub/sub.
$=:
- yakut compile $DSDL_SRC   # "DSDL_SRC" is to be set externally.
-                           # Wait for the compiler to finish.
- yakut --format json sub -M -N2 33:uavcan.si.unit.angle.Scalar.1.0
- yakut --format json sub -M -N1 uavcan.diagnostic.Record.1.1
- $=: >         # Inner composition with a single multi-line command.
    yakut pub -N5
    33:uavcan.si.unit.angle.Scalar.1.0 'radian: 4.0'
    uavcan.diagnostic.Record.1.1       'text: "four radians"'
  uavcan.node.id: 9  # The publisher is not anonymous unlike others.
.=:
- ?=: rm -r $YAKUT_COMPILE_OUTPUT       # Clean up at the exit.
uavcan.udp.iface: 127.42.0.1  # Configure the transport via registers.
YAKUT_COMPILE_OUTPUT: pub_sub_compiled_dsdl
YAKUT_PATH:           pub_sub_compiled_dsdl
""".strip()
# language=YAML
EXAMPLE_PUB_SUB_STDOUT = """
{"33":{"radian":4.0}}
{"8184":{"timestamp":{"microsecond":0},"severity":{"value":0},"text":"four radians"}}
{"33":{"radian":4.0}}
""".strip()


_HELP = f"""
Manage configuration of multiple UAVCAN nodes using YAML files.

Currently, this tool is not tested against Windows and is therefore not expected to function there correctly.

Here, "orchestration" means configuration management of a UAVCAN-based distributed computing system.
The participants of such a system may be either software processes executed on a computer (local or remote),
dedicated hardware units (e.g., a flight management unit or a sensor), or a mix thereof.

The user writes an orchestration file (orc-file for short) that defines the desired node parameters
and the shell commands that need to be executed to bring the system configuration into the desired state.
The configuration of remote nodes may be enforced via UAVCAN using proxy commands like
"yakut register", "yakut call", etc. (this is convenient for hardware nodes) or via conventional means like SSH
(useful for software nodes executed on a remote computer).

As prescribed by the UAVCAN standard, the node parameters are modeled as registers
(see standard RPC-service uavcan.register.Access).
Register values described in the orc-file are passed to the invoked processes via environment variables.
An environment variable name is constructed from register name by upper-casing it and replacing full stop characters
(".") with double low line characters ("__").

Binary-typed values (aka raw bytes) are passed as-is, strings are UTF8-encoded,
and numerical values are passed as decimals. Array elements are space-separated.
For example, register "m.motor.inductance_dq" of type "real32[2]" with value (0.12, 0.13)
is passed as an environment variable named "M__MOTOR__INDUCTANCE_DQ" assigned "0.12 0.13".

When defining a register value in the orc-file, the user may spell out its name in its entirety:

\b
    m.motor.inductance_dq: [0.12, 0.13]
    m.motor.flux_linkage:  1.34
    uavcan.node.id:        1201
    uavcan.pub.foo.id:     7777

For convenience and clarity, it is possible to group registers into dictionaries:

\b
    m.motor:
      inductance_dq: [0.12, 0.13]
      flux_linkage:   1.34
    uavcan:
      node.id: 1201
      pub.foo.id: 7777

It is also possible to define regular environment variables alongside the registers -- they will be passed
to the invoked processes as-is without modification.
Regular environment variables are distinguished from registers by the lack of "." in their names.

Null-valued keys can be used to erase registers and environment variables defined in an outer scope
(so that they are not propagated).

The behaviors defined by an orchestration file are specified using "compositions".
A composition is a YAML-dictionary of UAVCAN registers, environment variables, and "directives".
A directive is a dictionary key ending with an equals sign "=".
The syntax can be approximated as follows, using a PEG-like notation:

\b
    # register and envvar are described in free form above.
    composition = (register / envvar / directive)+
    directive   = predicate / main / finalizer / external
    predicate   = "?=" : script
    main        = "$=" : script
    finalizer   = ".=" : script
    external    = "external=": files
    script      = statement / (statement*)
    statement   = shell / join / composition
    shell       = string
    join        = null
    files       = string / (string*)

The script directives "?=" (predicate), "$=" (main), and ".=" (finalizer) define shell commands or nested compositions
that are to be executed.
If there is more than one command/composition specified, all of them are launched concurrently
until the executor encounters the first "join statement", whereat it will wait for the previously
launched script items to complete successfully before continuing.

A shell command that returns zero is considered successful, otherwise it is considered to have failed.
The exit code of a composition is that of its first statement to fail, or zero if all completed successfully
(but see below about predicates).
The execution order is as follows:

1. The predicate script "?=" is executed first.
If any of its statements fail, its execution is aborted, pending processes are interrupted,
and success (sic!) is reported (that is, zero).
The predicate script is intended to define commands that are allowed/expected to fail,
hence the result is always zero.

2. The main script "$=" is executed only if none of the statements of the predicate have failed.
The first statement to fail aborts the execution of all pending statements and its exit code becomes
the exit code of the current composition.

3. The finalizer script ".=" is always executed if the predicate was successful after the main script,
even if the main script has failed.
Its exit code is discarded unless the main script executed successfully.
Execution of the finalizer script is never interrupted to ensure that the configuration of the managed
system is always left in a known state.
It is therefore recommended to avoid placing any non-trivial statements in the finalizer script.

Example:

\b
{_indent(EXAMPLE_BASIC)}

The exit code of the above composition is {EXAMPLE_BASIC_EXIT_CODE} and the stdout is:

\b
{_indent(EXAMPLE_BASIC_STDOUT)}

The "external=" directive defines an external orc-file to be executed BEFORE the script directives of the current
composition.
The path is either absolute or relative; in the latter case, the file will be searched for
in the current working directory and then through the directories specified in YAKUT_PATH.
The composition defined in the external file (the callee) inherits/overrides the environment variables
from the caller.
Upon successful execution, the caller inherits all environment variables back from the callee.
If the callee fails or cannot be executed for other reasons, the execution of the caller is aborted
and its exit code is propagated.
Example of three orc-files:

\b
{_indent(EXAMPLE_EXTERNAL)}

\b
{_indent(EXAMPLE_EXTERNAL_VARS)}

\b
{_indent(EXAMPLE_EXTERNAL_ECHO)}

The above example exits with code {EXAMPLE_EXTERNAL_EXIT_CODE} printing this:

\b
{_indent(EXAMPLE_EXTERNAL_STDOUT)}

The orchestrator uses the following exit codes to report internal errors:
125 -- orc-file is malformed;
124 -- orc-file not found or cannot be read.

The orchestrator attempts to manage the entire process tree atomically.
If execution of a process fails, the orchestrator will bring down its siblings, execute the finalizer,
and then return the exit code of the first failed process.
The orchestrator treats SIGINT/SIGTERM/SIGHUP sent to itself as a command to cease execution and finalize
the composition immediately.
When terminating a launched process, the orchestrator starts with SIGINT and gradually escalates up to SIGKILL
if the process refuses to stop peacefully in a reasonable time.

Children's stdout/stderr are piped into those of the orchestrator host process with per-line buffering
(so that concurrent output does not mangle lines of text).
Despite the line buffering, the streams are operated in binary mode.

A slightly more practical example is shown below:

\b
{_indent(EXAMPLE_PUB_SUB)}

The stdout of the above composition is:

\b
{_indent(EXAMPLE_PUB_SUB_STDOUT)}
"""


@yakut.subcommand(help=_HELP)
@click.argument("file", type=str)
@yakut.pass_purser
def orchestrate(purser: yakut.Purser, file: str) -> None:
    sig_num = 0

    def on_signal(s: int, _: Any) -> None:
        nonlocal sig_num
        sig_num = s
        _logger.info("Orchestrator received signal %s %r, stopping...", s, signal.strsignal(s))

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)
    if not sys.platform.startswith("win"):
        signal.signal(signal.SIGHUP, on_signal)

    ctx = Context(lookup_paths=purser.paths)
    res = exec_file(ctx, file, {}, gate=lambda: sig_num == 0)

    sys.exit(res if res != 0 else -sig_num)
