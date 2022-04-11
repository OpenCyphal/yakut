# Copyright (c) 2021 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

from __future__ import annotations
import dataclasses
from typing import Dict, Sequence, Any, List
from yakut.yaml import Loader
from ._env import encode, flatten_registers, NAME_SEP, EnvironmentVariableError


NOT_ENV = "="
"""
Equals sign is the only character that cannot occur in an environment variable name in most OS.
"""


class SchemaError(ValueError):
    pass


@dataclasses.dataclass(frozen=True)
class Composition:
    env: Dict[str, bytes]
    ext: Sequence[External]

    predicate: Sequence[Statement]
    main: Sequence[Statement]
    fin: Sequence[Statement]

    @property
    def kill_timeout(self) -> float:
        try:
            # This is very tentative and is not yet specified. May be changed.
            return float(self.env.get("(kill_timeout)"))  # type: ignore
        except (ValueError, TypeError):
            return 20.0


@dataclasses.dataclass(frozen=True)
class Statement:
    pass


@dataclasses.dataclass(frozen=True)
class ShellStatement(Statement):
    cmd: str


@dataclasses.dataclass(frozen=True)
class CompositionStatement(Statement):
    comp: Composition


@dataclasses.dataclass(frozen=True)
class JoinStatement(Statement):
    pass


@dataclasses.dataclass(frozen=True)
class External:
    file: str


def load_ast(text: str) -> Any:
    try:
        return Loader().load(text)
    except Exception as ex:
        raise SchemaError(f"Syntax error: {ex}") from ex


def load_composition(ast: Any, env: Dict[str, bytes]) -> Composition:
    """
    Environment inheritance order (last entry takes precedence):

    - Parent process environment (i.e., the environment the orchestrator is invoked from).
    - Outer composition environment (e.g., root members of the orchestration file).
    - Local environment variables.
    """
    if not isinstance(ast, dict):
        raise SchemaError(f"The composition shall be a dict, not {type(ast).__name__}")
    ast = ast.copy()  # Prevent mutation of the outer object.
    env = env.copy()  # Prevent mutation of the outer object.
    try:
        for name, value in flatten_registers(
            {k: v for k, v in ast.items() if isinstance(k, str) and NOT_ENV not in k}
        ).items():
            if NAME_SEP in name:  # Cyphal register.
                name = name.upper().replace(NAME_SEP, "_" * 2)
            if value is not None:
                env[name] = encode(value)
            else:
                env.pop(name, None)  # None is used to unset variables.
    except EnvironmentVariableError as ex:
        raise SchemaError(f"Environment variable error: {ex}") from EnvironmentVariableError

    out = Composition(
        env=env.copy(),
        ext=load_external(ast.pop("external=", [])),
        predicate=load_script(ast.pop("?=", []), env.copy()),
        main=load_script(ast.pop("$=", []), env.copy()),
        fin=load_script(ast.pop(".=", []), env.copy()),
    )
    unattended = [k for k in ast if NOT_ENV in k]
    if unattended:
        raise SchemaError(f"Unknown directives: {unattended}")
    return out


def load_script(ast: Any, env: Dict[str, bytes]) -> Sequence[Statement]:
    if isinstance(ast, list):
        return [load_statement(x, env) for x in ast]
    return [load_statement(ast, env)]


def load_statement(ast: Any, env: Dict[str, bytes]) -> Statement:
    if isinstance(ast, str):
        return ShellStatement(ast)
    if isinstance(ast, dict):
        return CompositionStatement(load_composition(ast, env))
    if ast is None:
        return JoinStatement()
    raise SchemaError("Statement shall be either: string (command to run), dict (nested schema), null (join)")


def load_external(ast: Any) -> List[External]:
    def item(inner: Any) -> External:
        if isinstance(inner, str):
            return External(inner)
        raise SchemaError(f"Call arguments shall be strings, not {type(ast).__name__}")

    if isinstance(ast, list):
        return [item(x) for x in ast]
    return [item(ast)]
