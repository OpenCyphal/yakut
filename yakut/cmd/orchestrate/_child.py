# Copyright (c) 2021 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

from __future__ import annotations
import os
import sys
import time
import signal
from subprocess import Popen, DEVNULL
from typing import Dict, Optional, Callable, List, Tuple, BinaryIO, Any
import yakut

# Disable unused ignore warning for this file only because there appears to be no other way to make MyPy
# accept this file both on Windows and GNU/Linux.
# mypy: warn_unused_ignores=False

_logger = yakut.get_logger(__name__)


if sys.platform.startswith("win"):  # pragma: no cover
    SIGNAL_INTERRUPT = signal.CTRL_BREAK_EVENT
    SIGNAL_TERMINATE = signal.SIGTERM
    SIGNAL_KILL = signal.SIGTERM
else:
    SIGNAL_INTERRUPT = signal.SIGINT
    SIGNAL_TERMINATE = signal.SIGTERM
    SIGNAL_KILL = signal.SIGKILL


class Child:
    """
    Starts a child shell process and provides convenient non-blocking controls:

    - :meth:`poll` for querying the status.
    - :meth:`stop` for stopping with automatic escalation of the signal strength.
    - The constructor accepts file objects where the child process output is sent to.

    When running on Windows, it may be desirable to use PowerShell as the system shell.
    For that, export the COMSPEC environment variable.
    """

    def __init__(self, cmd: str, env: Dict[str, bytes], *, stdout: BinaryIO, stderr: BinaryIO) -> None:
        """
        :param cmd: Shell command to execute. Execution starts immediately.
        :param env: Additional environment variables.
        :param stdout: Stdout from the child process is redirected there.
        :param stderr: Ditto, but for stderr.
        """
        self._return: Optional[int] = None
        self._signaling_schedule: List[Tuple[float, Callable[[], None]]] = []
        e: Any
        if os.supports_bytes_environ:
            e = os.environb.copy()  # type: ignore
            e.update({k.encode(): v for k, v in env.items()})
        else:  # pragma: no cover
            e = os.environ.copy()
            e.update({k: v.decode() for k, v in env.items()})
        self._proc = Popen(  # pylint: disable=consider-using-with
            cmd,
            env=e,
            shell=True,
            stdout=stdout,
            stderr=stderr,
            stdin=DEVNULL,
            bufsize=1,
        )

    @property
    def pid(self) -> int:
        """
        The process-ID of the child. This value retains validity even after the child is terminated.
        """
        return self._proc.pid

    def poll(self, timeout: float) -> Optional[int]:
        """
        :param timeout: Block for this many seconds, at most.
        :return: None if still running, exit code if finished (idempotent).
        """
        if self._return is None:
            if self._signaling_schedule:
                deadline, handler = self._signaling_schedule[0]
                if time.monotonic() >= deadline:
                    self._signaling_schedule.pop(0)
                    handler()

            ret = self._proc.poll()
            if ret is None:
                time.sleep(timeout)
                ret = self._proc.poll()
            if ret is not None:
                self._return = ret

        return self._return

    def stop(self, escalate_after: float, give_up_after: float) -> None:
        """
        Send a SIGINT/CTRL_BREAK_EVENT to the process and schedule to check if it's dead later.

        :param escalate_after: If the process is still alive this many seconds after the initial termination signal,
            send a SIGTERM.

        :param give_up_after: Ditto, but instead of SIGTERM send SIGKILL (on Windows reuse SIGTERM instead)
            and disown the child immediately without waiting around. This is logged as error.
        """
        if self._return is not None or self._proc.poll() is not None:
            return
        give_up_after = max(give_up_after, escalate_after)
        _logger.debug(
            "%s: Stopping using signal %r. Escalation timeout: %.1f, give-up timeout: %.1f",
            self,
            SIGNAL_INTERRUPT,
            escalate_after,
            give_up_after,
        )
        signal_tree(self.pid, SIGNAL_INTERRUPT)

        def terminate() -> None:
            _logger.warning("%s: The child is still alive. Escalating to %r", self, SIGNAL_TERMINATE)
            signal_tree(self.pid, SIGNAL_TERMINATE)

        def kill() -> None:
            _logger.error(
                "%s: The child is still alive. Escalating to %r and detaching. No further attempts will be made!",
                self,
                SIGNAL_KILL,
            )
            self.kill()

        now = time.monotonic()
        self._signaling_schedule = [
            (now + escalate_after, terminate),
            (now + give_up_after, kill),
        ]

    def kill(self) -> None:
        """
        This is intended for abnormal termination of the owner of this instance.
        Simply kills the child with all its children and ceases all related activities.
        """
        if self._return is None:
            self._return = -SIGNAL_KILL
        signal_tree(self.pid, SIGNAL_KILL)

    def __str__(self) -> str:
        return f"Child {self.pid:08d}"


def signal_tree(pid: int, sig: int) -> None:
    """
    Send the signal to the specified process and all its children. The parent is signaled first.
    The list of children is collected once before the parent is signaled.

    This is needed for properly terminating process hierarchies, particularly those launched by shells,
    because merely killing the parent does not necessarily terminate its children.
    If there is no such process, does nothing.
    """
    import psutil  # type: ignore

    try:
        parent = psutil.Process(pid)
    except psutil.NoSuchProcess:
        _logger.debug("No process with PID=%r", pid)
    else:
        children = parent.children()
        _logger.debug("Sending signal %r to process %r with direct children %r", sig, pid, [x.pid for x in children])
        parent.send_signal(sig)
        for c in children:
            signal_tree(c.pid, sig)


def _unittest_child(caplog: object) -> None:
    import pytest
    import logging
    from pathlib import Path

    assert isinstance(caplog, pytest.LogCaptureFixture)

    io_out = Path("stdout")
    io_err = Path("stderr")

    if not sys.platform.startswith("win"):
        py = (
            "import time, signal as s; "
            + "s.signal(s.SIGINT, lambda *_: None); "
            + "s.signal(s.SIGTERM, lambda *_: None); "
            + "time.sleep(10)"
        )

        with caplog.at_level(logging.CRITICAL):
            c = Child(f'python -c "{py}"', {}, stdout=io_out.open("wb"), stderr=io_err.open("wb"))
            assert c.poll(0.1) is None
            c.stop(1.0, 2.0)
            assert c.poll(1.0) is None
            for _ in range(50):
                res = c.poll(0.1)
            assert res is not None
            assert res < 0  # Killed
            c.stop(1.0, 2.0)  # No effect because already dead.
        assert not io_out.read_text()
        assert not io_err.read_text()

        c = Child(f"sleep 10", {}, stdout=io_out.open("wb"), stderr=io_err.open("wb"))
        assert c.poll(0.1) is None
        c.kill()
        res = c.poll(1.0)
        assert res is not None
        assert res < 0  # Killed
        assert not io_out.read_text()
        assert not io_err.read_text()

        c = Child(
            """python -c "import sys; print('ABC', file=sys.stderr); print('DEF'); print('GHI', end='')" """,
            {},
            stdout=io_out.open("wb"),
            stderr=io_err.open("wb"),
        )
        assert 0 == c.poll(1.0)
        time.sleep(2.0)
        assert io_out.read_text().splitlines() == ["DEF", "GHI"]
        assert io_err.read_text().splitlines() == ["ABC"]

    else:  # pragma: no cover
        c = Child(f"echo Hello", {}, stdout=io_out.open("wb"), stderr=io_err.open("wb"))
        assert 0 == c.poll(5.0)
        c.stop(2.0, 4.0)
        c.kill()
        assert io_out.read_text().splitlines() == ["Hello"]
        assert not io_err.read_text()

    io_out.unlink(missing_ok=True)
    io_err.unlink(missing_ok=True)
