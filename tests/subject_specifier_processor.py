# Copyright (c) 2022 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

from __future__ import annotations
import asyncio
from typing import Any
import pytest
import pycyphal
from pycyphal.transport.loopback import LoopbackTransport
from yakut.subject_specifier_processor import process_subject_specifier, SubjectResolver
from yakut.subject_specifier_processor import BadSpecifierError, NoFixedPortIDError, NetworkDiscoveryError
from yakut import dtype_loader


@pytest.mark.asyncio
async def _unittest_without_subject_resolver() -> None:
    asyncio.get_running_loop().slow_callback_duration = 5.0

    import uavcan.primitive
    import uavcan.node

    def get_subject_resolver() -> SubjectResolver:
        raise RuntimeError("Subject resolver shall not be used in this test")

    async def once(specifier: str) -> tuple[int, Any]:
        return await process_subject_specifier(specifier, get_subject_resolver)

    assert (123, uavcan.primitive.Empty_1) == await once("123:uavcan.primitive.Empty.1")

    fpid = pycyphal.dsdl.get_fixed_port_id(uavcan.node.Heartbeat_1)
    assert fpid is not None
    assert (fpid, uavcan.node.Heartbeat_1) == await once("uavcan.node.Heartbeat.1")

    with pytest.raises(BadSpecifierError):
        await once("99999999:uavcan.primitive.Empty.1")

    with pytest.raises(BadSpecifierError):
        await once("not_a_number:uavcan.primitive.Empty.1")

    with pytest.raises(dtype_loader.FormatError):
        await once("bad:format:error")

    with pytest.raises(dtype_loader.FormatError):
        await once("123:123.123.123")

    with pytest.raises(dtype_loader.NotFoundError):
        await once("123:uavcan.primitive.Empty.1.250")

    with pytest.raises(NoFixedPortIDError):
        await once("uavcan.primitive.Empty")


@pytest.mark.asyncio
async def _unittest_with_subject_resolver() -> None:
    asyncio.get_running_loop().slow_callback_duration = 5.0

    from pycyphal.application import make_node, NodeInfo, register
    import uavcan.primitive.scalar

    local_node = make_node(info=NodeInfo(), transport=LoopbackTransport(2222))
    subject_resolver = SubjectResolver(local_node)

    def advertise(kind: str, name: str, dtype_name: str, port_id: int) -> None:
        local_node.registry[f"uavcan.{kind}.{name}.id"] = register.ValueProxy(register.Natural16([port_id]))
        local_node.registry[f"uavcan.{kind}.{name}.type"] = register.ValueProxy(register.String(dtype_name))

    advertise("pub", "foo", "uavcan.primitive.scalar.Bit.1.200", 500)
    advertise("sub", "bar", "uavcan.primitive.scalar.Integer8.1.200", 600)  # minor version ignored
    advertise("pub", "bar", "uavcan.node.GetInfo.1.0", 600)  # service type ignored
    advertise("pub", "bad", "nonexistent.DataType.1.0", 600)  # nonexistent type ignored
    advertise("sub", "baz", "uavcan.primitive.scalar.Real16.1.200", 0xFFFF)

    local_node.start()

    async def once(specifier: str) -> tuple[int, Any]:
        return await process_subject_specifier(specifier, lambda: subject_resolver)

    assert (500, uavcan.primitive.scalar.Bit_1) == await once("500")
    assert (600, uavcan.primitive.scalar.Integer8_1) == await once("600")  # minor version ignored

    with pytest.raises(NetworkDiscoveryError):
        await once("700")  # nonexistent

    subject_resolver.close()
    local_node.close()
    await asyncio.sleep(1.0)
