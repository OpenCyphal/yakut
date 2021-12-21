# Copyright (c) 2021 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>
# pylint: disable=consider-using-with

import asyncio
import pytest
from tests.subprocess import Subprocess


# noinspection SpellCheckingInspection
@pytest.mark.asyncio
async def _unittest_joystick() -> None:
    asyncio.get_running_loop().slow_callback_duration = 10.0

    # This command interacts directly with the hardware.
    # We can't test it end-to-end in a virtualized environment without being able to emulate the connected hardware.
    # For now, we just check if it runs at all, which is not very helpful but is better than nothing.
    # Eventually we should find a way to emulate connected joysticks and MIDI controllers.
    proc = Subprocess.cli("joy", stdout=open("stdout", "wb"), stderr=open("stderr", "wb"))
    assert proc.alive
    await asyncio.sleep(5)
    assert proc.alive, open("stderr", "r").read()
    proc.wait(10.0, interrupt=True)

    # The null controller shall always be available.
    with open("stdout", "r") as f:
        assert "null" in f.read()
