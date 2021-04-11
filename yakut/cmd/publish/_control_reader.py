# Copyright (c) 2021 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

from __future__ import annotations
from typing import Dict
from copy import copy
import dataclasses
import yakut
from yakut import hid_controller


class ControlReader:
    """
    This class can be trivially updated to emit notifications when a controller input is received
    (i.e., when the user interacts with the controller like moving a slider or pressing a button).
    """

    def __init__(self) -> None:
        self._sources: Dict[str, _Source] = {}

    def connect(self, selector: str) -> bool:
        """
        Initialize the specified controller and start reading it.

        :returns: True if ok, False if no such controller exists.
        """
        available = list(hid_controller.list_controllers())
        # If the selector is a number, use it as an index; otherwise, match by name.
        try:
            name, factory = available[int(selector)]
        except IndexError:
            return False
        except ValueError:
            for name, factory in available:
                if name == selector:
                    break
            else:
                return False
        assert isinstance(name, str) and callable(factory)
        _logger.info("Initializing new HID controller %r matching selector %r", name, selector)
        try:
            controller = factory()
            sample = controller.sample()
            self._sources[selector] = _Source(controller, sample)
        except hid_controller.ControllerNotFoundError:
            return False
        return True

    def capture_all(self) -> None:
        """
        Capture the state of all controllers nearly atomically.
        The updated state can be collected using :meth:`read` separately per controller.
        """
        for s in self._sources.values():
            s.last_sample = s.controller.sample()

    def read(self, selector: str) -> hid_controller.Sample:
        """
        :raises: :class:`LookupError` if the controller was not initialized previously using :meth:`connect`.
        """
        return copy(self._sources[selector].last_sample)

    def close(self) -> None:
        _logger.debug("Closing sources: %r", self._sources)
        for s in self._sources.values():
            s.controller.close()


@dataclasses.dataclass()
class _Source:
    controller: hid_controller.Controller
    last_sample: hid_controller.Sample


_logger = yakut.get_logger(__name__)
