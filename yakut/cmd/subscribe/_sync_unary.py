# Copyright (c) 2022 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>


from __future__ import annotations
from typing import Any, Iterable
import pycyphal
from ._sync import SynchronizerOutput, Synchronizer


def make_sync_unary(subscribers: Iterable[pycyphal.presentation.Subscriber[Any]]) -> Synchronizer:
    subscribers = list(subscribers)
    if len(subscribers) != 1:
        raise ValueError(f"Unary synchronizer requires exactly one subscriber; got {subscribers}")
    (subscriber,) = subscribers

    async def fun(output: SynchronizerOutput) -> None:
        async for msg, meta in subscriber:
            assert isinstance(meta, pycyphal.transport.TransferFrom)
            output((((msg, meta), subscriber),))

    return fun
