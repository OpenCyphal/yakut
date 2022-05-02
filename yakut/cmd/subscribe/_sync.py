# Copyright (c) 2022 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>


from __future__ import annotations
from typing import Any, Callable, Awaitable, Iterable, Tuple, Optional
import pycyphal


SynchronizerOutput = Callable[
    [
        Tuple[
            Tuple[
                Optional[Tuple[Any, pycyphal.transport.TransferFrom]],
                pycyphal.presentation.Subscriber[Any],
            ],
            ...,
        ]
    ],
    None,
]

Synchronizer = Callable[
    [SynchronizerOutput],
    Awaitable[None],
]

SynchronizerFactory = Callable[
    [Iterable[pycyphal.presentation.Subscriber[Any]]],
    Synchronizer,
]
