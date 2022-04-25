# Copyright (c) 2022 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>


from __future__ import annotations
from typing import Any, Iterable, TypeVar
import logging
from pycyphal.presentation import Subscriber
from pycyphal.presentation.subscription_synchronizer.monotonic_clustering import MonotonicClusteringSynchronizer
from ._sync import SynchronizerOutput, Synchronizer

T = TypeVar("T")


def make_sync_monoclust(
    subscribers: Iterable[Subscriber[Any]],
    *,
    f_key: MonotonicClusteringSynchronizer.KeyFunction,
    tolerance_minmax: tuple[float, float],
) -> Synchronizer:
    tolerance_minmax = float(tolerance_minmax[0]), float(tolerance_minmax[1])
    sync = MonotonicClusteringSynchronizer(subscribers, f_key=f_key, tolerance=max(tolerance_minmax))
    prev_key: Any = None

    async def fun(output: SynchronizerOutput) -> None:
        nonlocal prev_key
        # noinspection PyTypeChecker
        async for synchronized_group in sync:
            key = sum(f_key(x[0]) for x in synchronized_group) / len(synchronized_group)
            output(synchronized_group)
            if prev_key is not None:
                sync.tolerance = _clamp(
                    tolerance_minmax,
                    (sync.tolerance + _tolerance_from_key_delta(prev_key, key)) * 0.5,
                )
            _logger.info("Tolerance autotune: %r", sync.tolerance)
            prev_key = key

    return fun


def _tolerance_from_key_delta(old: T, new: T) -> T:
    return (new - old) * 0.5  # type: ignore


def _clamp(lo_hi: tuple[T, T], val: T) -> T:
    lo, hi = lo_hi
    return min(max(lo, val), hi)  # type: ignore


_logger = logging.getLogger(__name__)
