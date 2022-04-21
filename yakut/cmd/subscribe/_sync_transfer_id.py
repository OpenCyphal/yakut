# Copyright (c) 2022 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>


from __future__ import annotations
from typing import Any, Iterable
from pycyphal.presentation import Subscriber
from pycyphal.presentation.subscription_synchronizer.transfer_id import TransferIDSynchronizer
from ._sync import SynchronizerOutput, Synchronizer


def make_sync_transfer_id(subscribers: Iterable[Subscriber[Any]]) -> Synchronizer:
    sync = TransferIDSynchronizer(subscribers)

    async def fun(output: SynchronizerOutput) -> None:
        # noinspection PyTypeChecker
        async for synchronized_group in sync:
            output(synchronized_group)

    return fun
