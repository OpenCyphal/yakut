# Copyright (c) 2021 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

from __future__ import annotations
import time
import itertools
from typing import List, Iterable
import threading
import click
import yakut
from yakut.controller import list_controllers, Controller


_logger = yakut.get_logger(__name__)


@yakut.subcommand(aliases="joy")
def joystick() -> None:
    """
    Show the state of all joysticks and MIDI controllers connected to this computer, htop-style.
    The values printed by this command can be used with the publisher command to alter published messages in real-time.
    This is convenient for controlling various processes or mechanisms in real time during simulation,
    hardware testing, manual operation, etc.

    There is an index associated with each controller that can be referred to along with a specific axis/button name
    from the publisher command (read its docs for more information and usage examples).
    There is also a virtual controller named "null" always available at index 0 with no axes/buttons;
    all of its channels always read out as zero/false.

    X-Box controllers may require a special initialization sequence under GNU/Linux:
    https://gist.github.com/pavel-kirienko/86b9d039151405451130a0fb3896887c
    """
    controllers = [factory() for _name, factory in list_controllers()]
    _logger.info("Using %d controllers: %s", len(controllers), controllers)
    try:
        _run(controllers)
    finally:
        for ctl in controllers:
            ctl.close()


def _run(controllers: List[Controller]) -> None:
    update = threading.Event()
    for ctl in controllers:
        ctl.set_update_hook(update.set)

    for update_count in itertools.count():
        time.sleep(0.05)
        update.wait(1.0)
        update.clear()

        lines = "\n".join(_render_all(controllers))
        click.clear()
        click.echo(lines)
        _logger.debug("%d updates", update_count)


def _render_all(controllers: List[Controller]) -> Iterable[str]:
    yield "Legend: A -- analog axis, B -- push button, T -- toggle switch"
    for idx, ctl in enumerate(controllers):
        yield ""
        yield click.style(f"{idx} ", fg="bright_cyan") + click.style(ctl.name, fg="bright_white", bg="blue")
        sample = ctl.sample()

        if sample.axis:
            yield " ".join(
                click.style(f"A({idx},{axis})=", fg="green") + click.style(f"{value:+.2f}", fg="bright_white")
                for axis, value in sorted(sample.axis.items())
            )
        else:
            yield click.style("No analog axes detected (try moving the controls)", fg="bright_red")

        if sample.button:
            yield " ".join(
                click.style(f"B({idx},{axis})=", fg="cyan") + click.style(f"{value:d}", fg="bright_white")
                for axis, value in sorted(sample.button.items())
            )
        else:
            yield click.style("No buttons detected (try pushing them)", fg="bright_red")

        if sample.toggle:
            yield " ".join(
                click.style(f"T({idx},{axis})=", fg="yellow") + click.style(f"{value:d}", fg="bright_white")
                for axis, value in sorted(sample.toggle.items())
            )
        else:
            yield click.style("No toggles detected (try switching them)", fg="bright_red")
