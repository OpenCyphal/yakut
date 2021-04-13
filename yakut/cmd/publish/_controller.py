# Copyright (c) 2021 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

from __future__ import annotations
from typing import Set, Any, Callable, Optional
import yakut
from yakut.controller import Controller, list_controllers, ControllerNotFoundError
from yakut.controller import Sample as Sample


class ControllerReader:
    """
    This class can be trivially updated to emit notifications when a controller input is received
    (i.e., when the user interacts with the controller like moving a slider or pressing a button).
    """

    def __init__(self) -> None:
        """
        The list of available controllers is sampled ONCE during initialization and held forever because:

        - This is a slow operation that involves much IO.
        - Controllers may be connected/disconnected at runtime, rendering their indices obsolete.
        """
        self._sources = [ControlInputSource(name, factory) for name, factory in list_controllers()]

    @property
    def active(self) -> Set[str]:
        """
        Names of currently active controllers (i.e., those that are read from).
        """
        return set(x.name for x in self._sources if x.active)

    def sample_and_hold(self) -> None:
        """
        Capture the state of all controllers nearly atomically.
        The updated state can be collected using :meth:`read` separately per controller.
        """
        for s in self._sources:
            s.sample_and_hold()

    def read(self, selector: Any) -> Sample:
        """
        TODO: support abbreviated case-insensitive names for persistence;
        e.g., ``xbox`` to match the first X-Box 360 Controller.

        :raises: :class:`ControllerNotFoundError`
        """
        try:
            selector = int(selector)
        except (ValueError, TypeError):  # pragma: no cover
            raise ControllerNotFoundError(f"Non-index controller selectors not yet supported: {selector!r}") from None
        try:
            src = self._sources[selector]
        except LookupError:
            raise ControllerNotFoundError(f"No controller at index {selector}") from None
        out = src.read()
        assert isinstance(out, Sample)
        return out

    def close(self) -> None:
        for s in self._sources:
            s.close()

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self._sources})"


class ControlInputSource:
    def __init__(self, name: str, factory: Callable[[], Controller]) -> None:
        self.name = name
        self._factory = factory
        self._controller: Optional[Controller] = None
        self._last_sample: Optional[Sample] = None

    @property
    def active(self) -> bool:
        return self._controller is not None

    def sample_and_hold(self) -> None:
        if self._controller is not None:
            self._last_sample = self._controller.sample()

    def read(self) -> Sample:
        if self._controller is None:
            _logger.debug("%s: Connecting", self)
            self._controller = self._factory()
            self._last_sample = self._controller.sample()
        assert self._last_sample is not None
        return self._last_sample

    def close(self) -> None:
        if self._controller is not None:
            _logger.debug("%s: Closing", self)
            self._controller.close()

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.name!r})"


_logger = yakut.get_logger(__name__)


def _unittest_null() -> None:
    import pytest

    cr = ControllerReader()
    assert cr.active == set()
    cr.sample_and_hold()  # No-op because no controllers connected.

    assert cr.read("0")
    assert cr.active == {"null"}

    assert cr.read("0")  # Already connected
    assert cr.active == {"null"}

    with pytest.raises(ControllerNotFoundError):
        cr.read("999")
    assert cr.active == {"null"}

    cr.sample_and_hold()

    assert cr.read("0").axis == {}
    assert cr.read("0").button == {}
    assert cr.read("0").toggle == {}

    print(cr)
