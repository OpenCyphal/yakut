# Copyright (c) 2019 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

import sys
import random
import asyncio
import contextlib
import click
import pyuavcan
import yakut


_logger = yakut.get_logger(__name__)


@yakut.subcommand()
@yakut.pass_purser
@yakut.asynchronous
async def accommodate(purser: yakut.Purser) -> None:
    """
    Automatically find a node-ID value that is not used by any other node that is currently online.

    This is a simpler alternative to plug-and-play node-ID allocation logic defined in Specification.
    Unlike the solution presented there, this alternative is less deterministic and less robust;
    it is fundamentally unsafe and it should not be used in production.
    Instead, it is intended for use in R&D and testing applications,
    either directly by humans or from automation scripts.

    The operating principle is extremely simple and can be viewed as a simplification of the
    node-ID claiming procedure defined in J1939:
    listen to Heartbeat messages for a short while,
    build the list of node-ID values that are currently in use,
    and then randomly pick a node-ID from the unused ones.
    The listening duration is determined heuristically at run time;
    for most use cases it is unlikely to exceed three seconds.
    """
    try:
        import uavcan.node
    except (ImportError, AttributeError):
        from yakut.cmd.compile import make_usage_suggestion

        raise click.UsageError(make_usage_suggestion("uavcan")) from None

    transport = purser.get_transport()
    node_id_set_cardinality = transport.protocol_parameters.max_nodes
    if node_id_set_cardinality > 2 ** 24:
        # Special case: for very large sets just pick a random number.
        # Very large sets are only possible with test transports such as loopback so it's acceptable.
        # If necessary, later we could develop a more robust solution.
        click.echo(random.randint(0, node_id_set_cardinality - 1))
        return

    candidates = set(range(node_id_set_cardinality))
    try:
        candidates.remove(transport.local_node_id)  # Allow non-anonymous transports for consistency.
    except LookupError:
        pass

    if node_id_set_cardinality > 1000:
        # Special case: some transports with large NID cardinality may have difficulties supporting a node-ID of zero
        # depending on the configuration of the underlying hardware and software.
        # This is not a problem of UAVCAN but of the platform itself.
        # For example, a UDP/IP transport over IPv4 with a node-ID of zero would map to an IP address with trailing
        # zeros which may be the address of the subnet, which is likely to cause all sorts of complications.
        _logger.debug("Removing the zero node-ID from the set of available values to avoid platform-specific issues")
        candidates.remove(0)

    pres = pyuavcan.presentation.Presentation(transport)
    with contextlib.closing(pres):
        deadline = asyncio.get_event_loop().time() + uavcan.node.Heartbeat_1_0.MAX_PUBLICATION_PERIOD * 2.0
        sub = pres.make_subscriber_with_fixed_subject_id(uavcan.node.Heartbeat_1_0)
        while asyncio.get_event_loop().time() <= deadline:
            result = await sub.receive(deadline)
            if result is None:
                break
            msg, transfer = result
            assert isinstance(transfer, pyuavcan.transport.TransferFrom)
            _logger.debug("Received %r via %r", msg, transfer)
            if transfer.source_node_id is None:
                _logger.warning(
                    "FYI, the network contains an anonymous node which is publishing Heartbeat. "
                    "Please contact the vendor and inform them that this behavior is non-compliant. "
                    "The offending heartbeat message is: %r, transfer: %r",
                    msg,
                    transfer,
                )
            else:
                try:
                    candidates.remove(int(transfer.source_node_id))
                except LookupError:
                    pass
                else:
                    # If at least one node is in the Initialization state, the network might be starting,
                    # so we need to listen longer to minimize the chance of collision.
                    multiplier = 3.0 if msg.mode.value == uavcan.node.Mode_1_0.INITIALIZATION else 1.0
                    advancement = uavcan.node.Heartbeat_1_0.MAX_PUBLICATION_PERIOD * multiplier
                    _logger.debug(
                        "Deadline advanced by %.1f s; %d candidates left of %d possible",
                        advancement,
                        len(candidates),
                        node_id_set_cardinality,
                    )
                    deadline = max(deadline, asyncio.get_event_loop().time() + advancement)

    if not candidates:
        click.secho(f"All {node_id_set_cardinality} of the available node-ID values are occupied.", err=True, fg="red")
        sys.exit(1)
    else:
        pick = random.choice(list(candidates))
        _logger.info(
            "The set of unoccupied node-ID values contains %d elements out of %d possible; the chosen value is %d",
            len(candidates),
            node_id_set_cardinality,
            pick,
        )
        click.echo(pick)
