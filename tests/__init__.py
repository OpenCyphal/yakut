# Copyright (c) 2020 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>
# pylint: disable=wrong-import-position

from pathlib import Path
from typing import Callable, TypeVar, Any

# Please maintain these carefully if you're changing the project's directory structure.
TEST_DIR = Path(__file__).resolve().parent
ROOT_DIR = TEST_DIR.parent

DEPS_DIR = TEST_DIR / "deps"
assert DEPS_DIR.is_dir()


T = TypeVar("T")


def timeout(seconds: int) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    This is a decorator that makes the function raise :class:`TimeoutError` if it takes more than ``seconds``
    seconds to complete.

    >>> import time
    >>> @timeout(3)
    ... def runas(delay: float) -> None:
    ...     time.sleep(delay)
    >>> runas(1)
    >>> runas(10)
    Traceback (most recent call last):
      ...
    TimeoutError: ...
    """
    import signal
    from functools import wraps

    def decorator(fun: Callable[..., T]) -> Callable[..., T]:
        @wraps(fun)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            def signal_handler(_signum: int, _frame: Any) -> None:
                raise TimeoutError(f"Function {fun} took more than {seconds:.0f}s to complete")

            signal.signal(signal.SIGALRM, signal_handler)
            signal.alarm(seconds)
            try:
                return fun(*args, **kwargs)
            finally:
                signal.alarm(0)

        return wrapper

    return decorator
