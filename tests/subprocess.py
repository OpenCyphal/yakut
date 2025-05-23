# Copyright (c) 2019 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

from __future__ import annotations
import os
import sys
import shutil
import typing
import logging
from tempfile import NamedTemporaryFile
import subprocess
from pathlib import Path
from subprocess import CalledProcessError as CalledProcessError


_logger = logging.getLogger(__name__)


def execute(
    *args: str,
    timeout: typing.Optional[float] = None,
    environment_variables: typing.Optional[typing.Dict[str, str]] = None,
    log: bool = True,
    ensure_success: bool = True,
) -> typing.Tuple[int, str, str]:
    r"""
    This is a wrapper over :func:`subprocess.check_output`.

    :param args: The args to run.
    :param timeout: Give up waiting if the command could not be completed in this much time and raise TimeoutExpired.
        No limit by default.
    :param environment_variables: appends or overrides environment variables for the process.
    :param log: Log stdout/stderr upon completion.
    :param ensure_success: Raise CalledProcessError if the return code is non-zero.
    :return: (stdout, stderr) of the command.

    >>> execute('ping', '127.0.0.1', timeout=0.1)
    Traceback (most recent call last):
    ...
    subprocess.TimeoutExpired: ...
    """
    cmd = _make_process_args(*args)
    _logger.info("Executing process with timeout=%s: %s", timeout if timeout is not None else "inf", cmd)
    env = _get_env()
    _logger.debug("Environment: %s", env)
    if environment_variables:
        env.update(environment_variables)
    # Can't use PIPE because it is too small on Windows, causing the process to block on stdout/stderr writes.
    # Instead we redirect stdout/stderr to temporary files whose size is unlimited, and read them later.
    with NamedTemporaryFile(suffix=".out", buffering=0) as stdout_file:
        with NamedTemporaryFile(suffix=".err", buffering=0) as stderr_file:
            # Can't use shell=True with timeout; see https://stackoverflow.com/questions/36952245
            out = subprocess.run(  # pylint: disable=subprocess-run-check
                cmd,
                timeout=timeout,
                encoding="utf8",
                env=env,
                stdout=stdout_file,
                stderr=stderr_file,
            )
            stdout = _read_stream(stdout_file)
            stderr = _read_stream(stderr_file)
    if log:
        _logger.debug("%s stdout:\n%s", cmd, stdout)
        _logger.debug("%s stderr:\n%s", cmd, stderr)
    if out.returncode != 0 and ensure_success:
        raise CalledProcessError(out.returncode, cmd, stdout, stderr)
    assert isinstance(stdout, str) and isinstance(stderr, str)
    return out.returncode, stdout, stderr


def execute_cli(
    *args: str,
    timeout: typing.Optional[float] = None,
    environment_variables: typing.Optional[typing.Dict[str, str]] = None,
    log: bool = True,
    ensure_success: bool = True,
) -> typing.Tuple[int, str, str]:
    """
    A wrapper over :func:`execute` that runs the CLI tool with the specified arguments.
    """
    return execute(
        "python",
        "-m",
        "yakut",
        *args,
        timeout=timeout,
        environment_variables=environment_variables,
        log=log,
        ensure_success=ensure_success,
    )


class Subprocess:
    r"""
    A wrapper over :class:`subprocess.Popen`.
    This wrapper allows collection of stdout upon completion.
    At first I tried using a background reader thread that was blocked on ``stdout.readlines()``,
    but that solution ended up being dysfunctional because it is fundamentally incompatible with internal
    stdio buffering in the monitored process which we have absolutely no control over from our local process.
    Sure, there exist options to suppress buffering, such as the ``-u`` flag in Python or the PYTHONUNBUFFERED env var,
    but they would make the test environment unnecessarily fragile,
    so I opted to use a simpler approach where we just run the process until it kicks the bucket
    and then loot the output from its dead body.

    >>> p = Subprocess('ping', '127.0.0.1')
    >>> p.alive
    True
    >>> p.wait(0.1)
    Traceback (most recent call last):
    ...
    subprocess.TimeoutExpired: ...
    >>> p.kill()
    >>> p.wait(2.0)[0] != 0
    True
    >>> p.alive
    False
    """

    def __init__(self, *args: str, environment_variables: typing.Optional[typing.Dict[str, str]] = None):
        cmd = _make_process_args(*args)
        _logger.debug("Starting subprocess: %s", cmd)

        if sys.platform.startswith("win"):  # pragma: no cover
            # If the current process group is used, CTRL_C_EVENT will kill the parent and everyone in the group!
            creationflags: int = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            creationflags = 0

        env = _get_env(environment_variables)
        # Can't use PIPE because it is too small on Windows, causing the process to block on stdout/stderr writes.
        # Instead we redirect stdout/stderr to temporary files whose size is unlimited, and read them later.
        self._stdout = NamedTemporaryFile(suffix=".out", buffering=0)  # pylint: disable=consider-using-with
        self._stderr = NamedTemporaryFile(suffix=".err", buffering=0)  # pylint: disable=consider-using-with
        # Buffering must be DISABLED, otherwise we can't read data on Windows after the process is interrupted.
        # For some reason stdout is not flushed at exit there.
        self._inferior = subprocess.Popen(  # pylint: disable=consider-using-with
            cmd,
            stdout=self._stdout,
            stderr=self._stderr,
            encoding="utf8",
            env=env,
            creationflags=creationflags,
            bufsize=0,
        )
        _logger.info("PID %d started: %s\n%s", self.pid, cmd, env)

    @staticmethod
    def cli(*args: str, environment_variables: typing.Optional[typing.Dict[str, str]] = None) -> Subprocess:
        """
        A convenience factory for running the CLI tool.
        """
        return Subprocess("python", "-m", "yakut", *args, environment_variables=environment_variables)

    def wait(
        self, timeout: float, interrupt: typing.Optional[bool] = False, log: bool = True
    ) -> typing.Tuple[int, str, str]:
        if interrupt and self._inferior.poll() is None:
            self.interrupt()
        # stdout/stderr values returned by communicate() are not usable here because we don't use PIPE.
        # Frankly I think the subprocess module API is not very well designed.
        self._inferior.communicate(timeout=timeout)
        stdout = _read_stream(self._stdout)
        stderr = _read_stream(self._stderr)
        exit_code = int(self._inferior.returncode)
        if log:
            _logger.debug("PID %d exit code: %d", self.pid, exit_code)
            _logger.debug("PID %d stdout:\n%s", self.pid, stdout)
            _logger.debug("PID %d stderr:\n%s", self.pid, stderr)
        return exit_code, stdout, stderr

    def kill(self) -> None:
        self._inferior.kill()

    def interrupt(self) -> None:
        import signal

        try:
            self._inferior.send_signal(signal.SIGINT)
        except ValueError:  # pragma: no cover
            # On Windows, SIGINT is not supported, and CTRL_C_EVENT does nothing.
            self._inferior.send_signal(getattr(signal, "CTRL_BREAK_EVENT"))

    @property
    def pid(self) -> int:
        return int(self._inferior.pid)

    @property
    def alive(self) -> bool:
        return self._inferior.poll() is None

    def __del__(self) -> None:
        try:
            inf = self._inferior
        except AttributeError:
            pass  # Ignore semi-constructed objects.
        else:
            if inf.poll() is None:
                inf.kill()


def _read_stream(io: typing.Any) -> str:
    io.flush()
    io.seek(0)
    out = io.read().decode("utf8")
    assert isinstance(out, str)
    return out


_ENV_COPY_KEYS = {
    "PATH",
    "SYSTEMROOT",
    "HOMEDRIVE",
    "HOMEPATH",
    "USERPROFILE",
    "WINDIR",
    "TEMP",
    "TMP",
    "LOCALAPPDATA",
    "APPDATA",
    "PROGRAMFILES",
    "PROGRAMFILES(X86)",
    "PROGRAMW6432",
    "PROGRAMDATA",
    "ALLUSERSPROFILE",
    "PUBLIC",
    # Specific to us:
    "CYPHAL_PATH",
    "PYCYPHAL_PATH",
}


def _get_env(environment_variables: typing.Optional[typing.Dict[str, str]] = None) -> typing.Dict[str, str]:
    from tests import DEPS_DIR

    venv_path = Path(sys.executable).parent
    env = {k: v for k, v in os.environ.items() if k in _ENV_COPY_KEYS}
    # Buffering must be DISABLED, otherwise we can't read data on Windows after the process is interrupted.
    # For some reason stdout is not flushed at exit there.
    env.update(
        {
            "PYTHONUNBUFFERED": "1",
            "PYTHONPATH": str(DEPS_DIR),  # This is to load sitecustomize.py, which enables coverage.
            "PATH": os.pathsep.join([str(venv_path), env["PATH"]]),  # Make scripts from venv invokable.
        }
    )
    env.update(environment_variables or {})
    return env


def _make_process_args(executable: str, *args: str) -> typing.Sequence[str]:
    # On Windows, the path lookup is not performed so we have to find the executable manually.
    # On GNU/Linux it doesn't matter so we do it anyway for consistency.
    resolved = shutil.which(executable)
    if not resolved:  # pragma: no cover
        raise RuntimeError(f"Cannot locate executable: {executable}")
    executable = resolved
    return list(map(str, [executable] + list(args)))
