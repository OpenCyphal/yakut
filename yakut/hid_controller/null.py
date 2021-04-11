# Copyright (c) 2021 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

from __future__ import annotations
from typing import Iterable, Tuple, Callable
import yakut
from . import Controller, Sample


class NullController(Controller):
    """
    The null controller is useful if no real control inputs are needed.
    It always exists in exactly one instance and all its axes/buttons/etc. always read as zero/false.
    """

    DESCRIPTION = "null"

    def __init__(self) -> None:
        _logger.info("%s: Initialized", self)

    @property
    def description(self) -> str:
        return NullController.DESCRIPTION

    def sample(self) -> Sample:
        return Sample(axis={}, button={}, toggle={})

    def set_update_hook(self, hook: Callable[[], None]) -> None:
        _logger.debug("%s: Update hook ignored because the null controller is never updated: %r", self, hook)

    def close(self) -> None:
        _logger.debug("%s: Closed (this is a no-op)", self)

    @staticmethod
    def list_controllers() -> Iterable[Tuple[str, Callable[[], Controller]]]:
        yield NullController.DESCRIPTION, NullController


_logger = yakut.get_logger(__name__)
