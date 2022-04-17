# Copyright (c) 2022 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

import sys
from typing import Any
import pytest
import pycyphal
from yakut.dtype_loader import load_dtype, FormatError, NotFoundError
from .dsdl import OUTPUT_DIR


def _unittest_dtype_loader(compiled_dsdl: Any) -> None:
    _ = compiled_dsdl
    sys.path.append(str(OUTPUT_DIR))

    with pytest.raises(NotFoundError, match=r".*yakut compile.*unknown_root_namespace.*"):
        _ = load_dtype("unknown_root_namespace.Type.1.0")

    with pytest.raises(FormatError):
        _ = load_dtype("unknown_root_namespace.Type.1.0.0")

    ty = load_dtype("uavcan.node.Heartbeat.1.0")
    assert isinstance(ty, type)
    model = pycyphal.dsdl.get_model(ty)
    assert model.full_name == "uavcan.node.Heartbeat"
    assert model.version == (1, 0)

    ty = load_dtype("sirius_cyber_corp.Foo.1.0")
    assert isinstance(ty, type)
    model = pycyphal.dsdl.get_model(ty)
    assert model.full_name == "sirius_cyber_corp.Foo"
    assert model.version == (1, 0)

    with pytest.raises(NotFoundError):
        _ = load_dtype("sirius_cyber_corp.Foo.1.1")

    ty = load_dtype("sirius_cyber_corp.Foo.1.1", allow_minor_version_mismatch=True)  # Same but relaxed.
    assert isinstance(ty, type)
    model = pycyphal.dsdl.get_model(ty)
    assert model.full_name == "sirius_cyber_corp.Foo"
    assert model.version == (1, 9)

    ty = load_dtype("sirius_cyber_corp.Foo.1")
    assert isinstance(ty, type)
    model = pycyphal.dsdl.get_model(ty)
    assert model.full_name == "sirius_cyber_corp.Foo"
    assert model.version == (1, 9)

    ty = load_dtype("sirius_cyber_corp.Foo.2")
    assert isinstance(ty, type)
    model = pycyphal.dsdl.get_model(ty)
    assert model.full_name == "sirius_cyber_corp.Foo"
    assert model.version == (2, 2)

    ty = load_dtype("sirius_cyber_corp.Foo")
    assert isinstance(ty, type)
    model = pycyphal.dsdl.get_model(ty)
    assert model.full_name == "sirius_cyber_corp.Foo"
    assert model.version == (2, 2)
