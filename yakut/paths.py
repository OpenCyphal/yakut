# Copyright (c) 2019 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

import pathlib
import click
import yakut


VERSION_AGNOSTIC_DATA_DIR = pathlib.Path(click.get_app_dir("yakut"))
VERSION_SPECIFIC_DATA_DIR = VERSION_AGNOSTIC_DATA_DIR / ("v" + ".".join(map(str, yakut.__version_info__[:2])))

OUTPUT_TRANSFER_ID_MAP_DIR = VERSION_SPECIFIC_DATA_DIR / "output-transfer-id-maps"

OUTPUT_TRANSFER_ID_MAP_MAX_AGE = 60.0  # [second]
"""This is not a path but a related parameter so it's kept here. Files older that this are not used."""

DEFAULT_PUBLIC_REGULATED_DATA_TYPES_ARCHIVE_URI = (
    "https://github.com/UAVCAN/public_regulated_data_types/archive/master.zip"
)
