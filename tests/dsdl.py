# Copyright (c) 2019 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

import sys
import pathlib
import importlib
import pytest
from . import TEST_DIR, ROOT_DIR


CUSTOM_DATA_TYPES_DIR = TEST_DIR / "custom_data_types"

OUTPUT_DIR = ROOT_DIR / pathlib.Path(".dsdl_generated")
"""
The output directory needs to be added to YAKUT_PATH in order to use the compiled namespaces.
"""


@pytest.fixture(scope="session")  # type: ignore
def compiled_dsdl() -> None:
    """
    Ensures that the regulated DSDL namespaces are compiled and importable.
    To force recompilation, remove the output directory.
    """
    output_dir = str(OUTPUT_DIR)
    if output_dir not in sys.path:
        sys.path.insert(0, output_dir)
    try:
        import uavcan
        import sirius_cyber_corp
    except ImportError:
        from tests.subprocess import execute_cli
        from yakut.paths import DEFAULT_PUBLIC_REGULATED_DATA_TYPES_ARCHIVE_URI

        sirius_cyber_corp_dir = str(CUSTOM_DATA_TYPES_DIR / "sirius_cyber_corp")

        args = [
            "compile",
            DEFAULT_PUBLIC_REGULATED_DATA_TYPES_ARCHIVE_URI,
            "--lookup",
            sirius_cyber_corp_dir,
            "-O",
            output_dir,
        ]
        execute_cli(*args, timeout=90.0)

        args = ["compile", sirius_cyber_corp_dir, "--output", output_dir]
        execute_cli(*args, timeout=90.0)

        importlib.invalidate_caches()
