# Copyright (c) 2021 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

from __future__ import annotations
import abc
import sys
from typing import Iterable, Tuple, Callable
import dataclasses
import pyuavcan.util
import yakut

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
    def name(self) -> str:
        """
        Human-readable name of this controller. Examples:

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
    def set_update_hook(self, hook: Callable[[], None]) -> None:
        """
        The update hook is invoked shortly after the controller state is updated, possibly from a different thread.
        If a hook is already installed, the behavior is undefined.
        Invoking :meth:`sample` from the hook may or may not be supported.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def close(self) -> None:
        """
        Dispose the instance and the underlying resources. This method is idempotent.
        """
        raise NotImplementedError

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.name!r})"

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

    axis: Mapping[int, float]
    """
    Analogue axes whose values are normalized into [0, +1] for unipolar channels and [-1, +1] for bipolar channels.
    """

    button: Mapping[int, bool]
    """
    Each push button channel is True while the button is held down by the user, False otherwise.
    """

    toggle: Mapping[int, bool]
    """
    Toggle switch channels alternate their state between True and False at each user interaction.
    """


def list_controllers() -> Iterable[Tuple[str, Callable[[], Controller]]]:
    """
    Use this function for listing available devices and constructing new instances of :class:`Controller`.
    The :class:`null.NullController` is always available and listed first (i.e., at index 0, as the name suggests).

    :return: Iterable of tuples of (unique name, factory), one per available device.
    """
    from .null import NullController

    def handle_import_error(module_name: str, culprit: Exception) -> None:
        _logger.warning(
            "Could not import controller module %r; controllers of this kind may not be usable. Error: %s",
            module_name,
            str(culprit) or repr(culprit),
        )

    pyuavcan.util.import_submodules(sys.modules[__name__], handle_import_error)
    base = Controller
    # Order controller kinds by class name, but ensure that NullController always comes first.
    for ty in sorted(
        pyuavcan.util.iter_descendants(base),
        key=lambda x: (x is not NullController, x.__name__),
    ):
        try:
            options = list(ty.list_controllers())
        except Exception as ex:  # pylint: disable=broad-except
            _logger.warning("Could not list controllers of kind %r: %s", ty, ex)
            options = []
        for name, factory in options:
            _logger.debug("Detected controller from %s: %r", ty.__name__, name)
            yield name, factory


_logger = yakut.get_logger(__name__)
