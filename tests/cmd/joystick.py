# Copyright (c) 2021 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>
# pylint: disable=consider-using-with

import asyncio
from tests.subprocess import Subprocess


# noinspection SpellCheckingInspection
async def _unittest_joystick() -> None:
    asyncio.get_running_loop().slow_callback_duration = 10.0

    # This command interacts directly with the hardware.
    # We can't test it end-to-end in a virtualized environment without being able to emulate the connected hardware.
    # For now, we just check if it runs at all, which is not very helpful but is better than nothing.
    # Eventually we should find a way to emulate connected joysticks and MIDI controllers.
    proc = Subprocess.cli("joy")
    assert proc.alive
    await asyncio.sleep(5)
    assert proc.alive
    _, stdout, _stderr = proc.wait(10.0, interrupt=True)
    assert "null" in stdout, "The null controller shall always be available."
