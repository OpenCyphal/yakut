# Copyright (c) 2021 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

from __future__ import annotations
from typing import Dict, List, Set
from copy import copy
import dataclasses
import yakut
from yakut.controller import Controller, Sample, list_controllers, ControllerNotFoundError


class ControlReader:
    """
    This class can be trivially updated to emit notifications when a controller input is received
    (i.e., when the user interacts with the controller like moving a slider or pressing a button).
    """

    def __init__(self) -> None:
        self._sources: List[_Source] = []
        self._selectors: Dict[str, _Source] = {}

    @property
    def selectors(self) -> Set[str]:
        """
        Selectors of currently connected controllers.
        """
        return set(self._selectors)

    def connect(self, selector: str) -> bool:
        """
        Initialize the specified controller and start reading it.
        Do nothing and return True if it is already initialized.
        The same controller may be referred to either by name or by index; their equivalency is handled properly.

        :returns: True if ok, False if no such controller exists.
        """
        if selector in self._selectors:
            _logger.debug("%s: Controller that matches selector %r is already connected", self, selector)
            return True

        for index, (name, factory) in enumerate(list_controllers()):
            keys = {str(index), name}
            if selector in keys:
                _logger.info("%s: Connecting new controller matching selector %r", self, selector)
                try:
                    controller = factory()
                except ControllerNotFoundError:
                    _logger.debug("%s: The controller was disconnected during initialization", self)
                    return False
                source = _Source(controller, controller.sample())
                self._sources.append(source)

                keys.add(controller.name)
                for k in keys:
                    self._selectors[k] = source

                return True
        return False

    def capture_all(self) -> None:
        """
        Capture the state of all controllers nearly atomically.
        The updated state can be collected using :meth:`read` separately per controller.
        """
        for s in self._sources:
            s.last_sample = s.controller.sample()

    def read(self, selector: str) -> Sample:
        """
        :raises: :class:`LookupError` if the controller was not initialized previously using :meth:`connect`.
        """
        return copy(self._selectors[selector].last_sample)

    def close(self) -> None:
        _logger.debug("%s: Closing", self)
        for s in self._sources:
            s.controller.close()

    def __repr__(self) -> str:
        return f"{type(self).__name__}(selectors={list(self._selectors)})"


@dataclasses.dataclass()
class _Source:
    controller: Controller
    last_sample: Sample


_logger = yakut.get_logger(__name__)


def _unittest_null() -> None:
    cr = ControlReader()
    assert cr.selectors == set()
    cr.capture_all()  # No-op because no controllers connected.

    assert cr.connect("0")
    assert cr.selectors == {"0", "null", "null/null"}

    assert cr.connect("0")  # Do nothing
    assert cr.selectors == {"0", "null", "null/null"}

    assert cr.connect("null")  # Do nothing
    assert cr.selectors == {"0", "null", "null/null"}

    assert not cr.connect("999")  # Not found
    assert cr.selectors == {"0", "null", "null/null"}

    cr.capture_all()

    assert cr.read("0").axis == {}
    assert cr.read("0").button == {}
    assert cr.read("null").toggle == {}

    print(cr)
