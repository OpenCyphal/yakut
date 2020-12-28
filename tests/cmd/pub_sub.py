# Copyright (c) 2020 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

from __future__ import annotations
import typing
import pytest
import pathlib
from tests.subprocess import execute_u, Subprocess, CalledProcessError
from tests.dsdl import regulated_dsdl
from tests.transport import TRANSPORT_FACTORIES, TransportFactory


@pytest.mark.parametrize("transport_factory", TRANSPORT_FACTORIES)  # type: ignore
def _unittest_pub_sub(transport_factory: TransportFactory, regulated_dsdl: typing.Any) -> None:
    _ = regulated_dsdl
    print(transport_factory)
