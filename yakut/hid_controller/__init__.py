# Copyright (c) 2021 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

from __future__ import annotations
import abc
import sys
from typing import Iterable, Tuple, Callable
import dataclasses
import pyuavcan.util

if sys.version_info >= (3, 9):
    from collections.abc import Mapping
else:  # pragma: no cover
    from typing import Mapping  # pylint: disable=ungrouped-imports


class ControllerError(RuntimeError):
    """
    Base class for controller-related errors.
    """


class ControllerNotFoundError(ControllerError):
    """
    Controller could not be opened or sampled because it is no longer connected or never was.
    """


class Controller(abc.ABC):
    """
    Models a human interface controller like a joystick or a MIDI controller.
    The access is normally non-exclusive, meaning that multiple processes can access the same device concurrently,
    unless this is not supported by the hardware or the platform.
    """

    @property
    @abc.abstractmethod
    def description(self) -> str:
        """
        Human-readable description of this controller. Examples:

        - ``FAD.9:FAD.9 MIDI 1 24:0``
        - ``Xbox 360 Controller``

        This property does not raise exceptions.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def sample(self) -> Sample:
        """
        Sample the current state of the controls and return it.

        :raises: :class:`ControllerError`
        """
        raise NotImplementedError

    @abc.abstractmethod
    def close(self) -> None:
        """
        Dispose the instance and the underlying resources. This method is idempotent.
        """
        raise NotImplementedError

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.description!r})"

    @staticmethod
    def list_controllers() -> Iterable[Tuple[str, Callable[[], Controller]]]:
        """
        List devices that are usable with this specific class.
        Normally you should use the freestanding function :func:`list_controllers`.
        """
        raise NotImplementedError


@dataclasses.dataclass(frozen=True)
class Sample:
    """
    An atomic sample of the current controller's state.
    """

    analog_axes: Mapping[int, float]
    """
    Analogue axes whose values are normalized into [0, +1] for unipolar channels and [-1, +1] for bipolar channels.
    """

    push_buttons: Mapping[int, bool]
    """
    Each push button channel is True while the button is held down by the user, False otherwise.
    """

    toggle_switches: Mapping[int, bool]
    """
    Toggle switch channels alternate their state between True and False at each user interaction.
    """


def list_controllers() -> Iterable[Tuple[str, Callable[[], Controller]]]:
    """
    Use this function for listing available devices and constructing new instances of :class:`Controller`.

    :return: Iterable of tuples of (unique name, factory), one per available device.
    """
    pyuavcan.util.import_submodules(sys.modules[__name__])
    base = Controller
    for ty in pyuavcan.util.iter_descendants(base):
        prefix = ty.__name__[: -len(base.__name__)].lower()
        for name, factory in ty.list_controllers():
            yield f"{prefix}/{name}", factory
