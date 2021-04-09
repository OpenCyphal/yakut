# Copyright (c) 2021 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

from __future__ import annotations
from typing import Iterable, Tuple, Callable, Dict, Optional, List
from . import Controller, Sample, ControllerError, ControllerNotFoundError
import threading
import yakut
import sdl2  # type: ignore


class JoystickController(Controller):
    """
    Interface for standard HID joystick.
    """

    def __init__(self, index: int) -> None:
        self._handle = sdl2.joystick.SDL_JoystickOpen(index)
        if not self._handle:
            raise ControllerNotFoundError(f"Cannot open joystick {index}")
        self._id = sdl2.joystick.SDL_JoystickInstanceID(self._handle)
        self._description = sdl2.joystick.SDL_JoystickNameForIndex(index).decode()
        self._update_hook = lambda: None

        n_axes = sdl2.joystick.SDL_JoystickNumAxes(self._handle)
        n_hats = sdl2.joystick.SDL_JoystickNumHats(self._handle)
        n_buttons = sdl2.joystick.SDL_JoystickNumButtons(self._handle)

        self._axes: List[float] = [
            JoystickController._scale_axis(sdl2.joystick.SDL_JoystickGetAxis(self._handle, i)) for i in range(n_axes)
        ]
        self._hats: List[Tuple[int, int]] = [
            JoystickController._split_hat(sdl2.joystick.SDL_JoystickGetHat(self._handle, i)) for i in range(n_hats)
        ]
        self._buttons: List[bool] = [sdl2.joystick.SDL_JoystickGetButton(self._handle, i) for i in range(n_buttons)]
        self._counters: List[int] = [0 for _ in self._buttons]

        _registry[self._id] = self._callback

        _logger.info(
            "%s: Joystick %r initial state: axes=%s hats=%s buttons=%s",
            self,
            index,
            self._axes,
            self._hats,
            self._buttons,
        )

    @property
    def description(self) -> str:
        return self._description

    def sample(self) -> Sample:
        with _lock:
            if _exception:
                raise ControllerError("Worker thread failed") from _exception

            axes_and_hats = self._axes.copy()
            for x, y in self._hats:
                axes_and_hats.append(float(x))
                axes_and_hats.append(float(y))

            return Sample(
                axis={k: v for k, v in enumerate(axes_and_hats)},
                button={k: v for k, v in enumerate(self._buttons)},
                toggle={k: v % 2 != 0 for k, v in enumerate(self._counters)},
            )

    def set_update_hook(self, hook: Callable[[], None]) -> None:
        self._update_hook = hook

    def close(self) -> None:
        with _lock:
            _registry.pop(self._id, None)
            sdl2.joystick.SDL_JoystickClose(self._handle)

    def _callback(self, event: sdl2.SDL_Event) -> None:
        if event.type == sdl2.SDL_JOYAXISMOTION:
            self._axes[event.jaxis.axis] = JoystickController._scale_axis(event.jaxis.value)

        elif event.type in (sdl2.SDL_JOYBUTTONDOWN, sdl2.SDL_JOYBUTTONUP):
            if event.jbutton.state == sdl2.SDL_PRESSED:
                self._buttons[event.jbutton.button] = True
                self._counters[event.jbutton.button] += 1
            else:
                self._buttons[event.jbutton.button] = False

        elif event.type == sdl2.SDL_JOYHATMOTION:
            self._hats[event.jhat.hat] = JoystickController._split_hat(event.jhat.value)

        else:
            _logger.debug("%s: Event dropped: %r", self, event)

        self._update_hook()

    @staticmethod
    def _scale_axis(raw: int) -> float:
        if raw >= 0:
            return raw / 32767.0
        return raw / 32768.0

    @staticmethod
    def _split_hat(value: int) -> Tuple[int, int]:
        return (
            (bool(value & sdl2.SDL_HAT_RIGHT) - bool(value & sdl2.SDL_HAT_LEFT)),
            (bool(value & sdl2.SDL_HAT_UP) - bool(value & sdl2.SDL_HAT_DOWN)),
        )

    @staticmethod
    def list_controllers() -> Iterable[Tuple[str, Callable[[], Controller]]]:
        def construct(index: int) -> Controller:
            with _lock:
                return JoystickController(index)

        with _init_done:
            _init_done.wait()

        with _lock:
            num_joys = sdl2.joystick.SDL_NumJoysticks()
            for idx in range(num_joys):
                name = sdl2.joystick.SDL_JoystickNameForIndex(idx).decode()
                _logger.debug("Detected joystick %d of %d: %r", idx + 1, num_joys, name)
                yield name, lambda: construct(idx)


_exception: Optional[Exception] = None
_lock = threading.RLock()
_init_done = threading.Condition()
_registry: Dict[sdl2.SDL_JoystickID : Callable[[sdl2.SDL_Event], None]] = {}


def _dispatch_joy(joystick: sdl2.SDL_JoystickID, event: sdl2.SDL_Event) -> None:
    with _lock:
        try:
            _registry[joystick](event)
        except KeyError:
            _logger.debug("No handler for joystick %r; dropping event %r", joystick, event)


def _run_sdl2() -> None:
    # Shall we require SDL2 somewhere else in this app, this logic will have to be extracted into a shared component.
    global _exception
    try:
        import ctypes

        # Initialization and event processing should be done in the same thread.
        err = sdl2.SDL_Init(sdl2.SDL_INIT_JOYSTICK)
        if err != 0:
            raise ControllerError(f"Could not initialize SDL2: {sdl2.SDL_GetError()!r}")

        err = sdl2.SDL_JoystickEventState(sdl2.SDL_ENABLE)
        if err != 0:  # This is recommended in the docs but is not critical.
            _logger.info("Could not set up joystick event handling policy: %r", sdl2.SDL_GetError())

        sdl2.SDL_SetHint(sdl2.SDL_HINT_JOYSTICK_ALLOW_BACKGROUND_EVENTS, b"1")

        _logger.debug("SDL2 initialized successfully, entering the event loop")
        with _init_done:
            _init_done.notify()

        event = sdl2.SDL_Event()
        while True:
            if sdl2.SDL_WaitEvent(ctypes.byref(event)) != 1:
                raise ControllerError(f"Could not poll event: {sdl2.SDL_GetError()!r}")

            if event.type == sdl2.SDL_JOYAXISMOTION:
                _dispatch_joy(event.jaxis.which, event)
            elif event.type == sdl2.SDL_JOYBALLMOTION:
                _dispatch_joy(event.jball.which, event)
            elif event.type in (sdl2.SDL_JOYBUTTONDOWN, sdl2.SDL_JOYBUTTONUP):
                _dispatch_joy(event.jbutton.which, event)
            elif event.type == sdl2.SDL_JOYHATMOTION:
                _dispatch_joy(event.jhat.which, event)
            else:
                _logger.debug("Event dropped: %r", event)

    except Exception as ex:
        _exception = ex
        _logger.exception("SDL2 worker thread failed: %s", ex)


_logger = yakut.get_logger(__name__)

threading.Thread(target=_run_sdl2, name="sdl2_worker", daemon=True).start()
