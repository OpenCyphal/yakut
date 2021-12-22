# Copyright (c) 2021 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

# pylint: disable=too-many-boolean-expressions,too-many-instance-attributes

from __future__ import annotations
import re
from typing import Optional, TYPE_CHECKING, Any
import dataclasses
import pyuavcan
import yakut

if TYPE_CHECKING:
    import pyuavcan.application  # pylint: disable=ungrouped-imports


_logger = yakut.get_logger(__name__.split("._", maxsplit=1)[0])


@dataclasses.dataclass(frozen=True)
class AppDescriptor:
    r"""
    Application package file name format::

        NAME-HW_MAJ.HW_MIN-SW_MAJ.SW_MIN.SW_VCS.SW_CRC.app*
                   \_____/                     \_____/
            \____________/              \____________/
          either major or both          either CRC or both
        can be omitted if multiple      CRC and VCS can be
       hardware versions supported      omitted if irrelevant

    The values are sourced from uavcan.node.GetInfo, and they are as follows:

    NAME -- The name of the node; e.g., "com.zubax.telega".

    HW_MAJ, HW_MIN --
    Hardware version numbers.
    The minor number or both of them can be omitted iff the package is compatible with multiple hardware revisions.

    SW_MAJ, SW_MIN -- Software version numbers.

    SW_VCS, SW_CRC --
    The version control system (VCS) revision ID (e.g., git commit hash) and the CRC of the software package.
    Both are hexadecimal numbers and both are optional: either the CRC alone or both VCS-hash and CRC can be omitted
    (CRC cannot be populated without the VCS-hash).

    The fields are terminated by a literal string ".app",
    which can be followed by arbitrary additional metadata (like a file extension).

    Examples: com.zubax.telega-1.2-0.3.68620b82.28df0c432c2718cd.app.bin, com.zubax.telega-0.3.app

    The implementation applies trivial heuristics to decide if a given application
    needs to be updated to another version.
    Generally, an update is considered necessary if the available hardware version numbers match and
    CRC is different (if defined) or the update is of a newer version.
    """

    FILE_NAME_PATTERN = re.compile(
        r"(?i)([\w.]+)(?:-(\d+)(?:\.(\d+))?)?-(\d+)\.(\d+)(?:\.([0-9a-f]+)(?:\.([0-9a-f]+))?)?\.app.*"
    )

    name: str
    hw_maj: Optional[int]
    hw_min: Optional[int]
    sw_maj: int
    sw_min: int
    sw_vcs: Optional[int]
    sw_crc: Optional[int]

    def is_equivalent(self, other: AppDescriptor) -> bool:
        """
        :return: True if updating "self" to "other" is pointless because they are likely to be functionally equivalent.
            A property that is not defined for at least one operand is considered to match.
            For instance, if CRC is not defined, it is considered to match.
        """

        def compatible(a: Optional[int], b: Optional[int]) -> bool:
            if a is None or b is None:
                return True
            return a == b

        self._log("Checking if %s is equivalent...", other)
        if self.name != other.name:
            self._log("No, it is a completely different application.")
            return False
        if not compatible(self.hw_maj, other.hw_maj) or not compatible(self.hw_min, other.hw_min):
            self._log("No, the hardware version does not match.")
            return False
        if self.sw_maj != other.sw_maj or self.sw_min != other.sw_min:
            self._log("No, the software version does not match.")
            return False
        if not compatible(self.sw_vcs, other.sw_vcs) or not compatible(self.sw_crc, other.sw_crc):
            self._log("No, VCS/CRC do not match.")
            return False
        self._log("Yes, this app is equivalent to %s, an update is likely to be meaningless.", other)
        return True

    def should_update_to(self, other: AppDescriptor) -> bool:
        self._log("Checking if this app should be updated to %s...", other)
        if self.name != other.name:
            self._log("No, this is a completely different application.")
            return False
        if (self.hw_maj is not None and other.hw_maj is not None and self.hw_maj != other.hw_maj) or (
            self.hw_min is not None and other.hw_min is not None and self.hw_min != other.hw_min
        ):
            self._log("No, the hardware version does not match, an update might brick the node.")
            return False

        self._log("The applications appear to be compatible -- an update would not break the node. Looking further...")
        if self.sw_crc is not None and other.sw_crc is not None and self.sw_crc != other.sw_crc:
            self._log("The CRC is different! An update is therefore required regardless of the other parameters.")
            return True

        self._log("CRC is identical or not defined, checking the version information...")
        if (self.sw_maj > other.sw_maj) or ((self.sw_maj == other.sw_maj) and (self.sw_min > other.sw_min)):
            self._log("No, the other application is older.")
            return False

        vcs_different = self.sw_vcs is not None and other.sw_vcs is not None and self.sw_vcs != other.sw_vcs
        if (self.sw_maj != other.sw_maj) or (self.sw_min != other.sw_min) or vcs_different:
            self._log("Yes, %s is of a different version and is not older than the current one.", other)
            return True

        self._log("No, this application does not need to be updated to %s", other)
        return False

    def make_glob_expression(self) -> str:
        """
        Construct a glob expression for pre-matching.
        This is helpful when you need to filter out relevant files from a large directory.
        """
        return f"{self.name}-*.app*"

    @staticmethod
    def from_file_name(file_name: str) -> Optional[AppDescriptor]:
        match = AppDescriptor.FILE_NAME_PATTERN.match(file_name)
        if not match:
            return None
        name, hw_maj, hw_min, sw_maj, sw_min, sw_vcs, sw_crc = match.groups()

        def mint10(s: str) -> Optional[int]:
            return int(s, 10) if s is not None else None

        def mint16(s: str) -> Optional[int]:
            return int(s, 16) if s is not None else None

        return AppDescriptor(
            name.lower(),
            mint10(hw_maj),
            mint10(hw_min),
            int(sw_maj),
            int(sw_min),
            mint16(sw_vcs),
            mint16(sw_crc),
        )

    @staticmethod
    def from_node_info(info: pyuavcan.application.NodeInfo) -> AppDescriptor:
        has_hw = info.hardware_version.major > 0 or info.hardware_version.minor > 0
        return AppDescriptor(
            info.name.tobytes().decode(errors="ignore").strip().lower(),
            info.hardware_version.major if has_hw else None,
            info.hardware_version.minor if has_hw else None,
            info.software_version.major,
            info.software_version.minor,
            info.software_vcs_revision_id or None,
            info.software_image_crc.sum() or None,
        )

    def _log(self, text: str, *args: Any) -> None:
        text = f"{self}: {text}"
        _logger.info(text, *args)

    def __str__(self) -> str:
        out = f"{self.name}"
        if self.hw_maj is not None:
            out += f"-{self.hw_maj}" + f".{self.hw_min}" * (self.hw_min is not None)
        out += f"-{self.sw_maj}.{self.sw_min}"
        if self.sw_vcs is not None:
            out += f".{self.sw_vcs:016x}" + (f".{self.sw_crc:016x}" if self.sw_crc is not None else "")
        return out + ".app"


def _unittest_app_descriptor_from_node_info() -> None:
    from tests.dsdl import ensure_compiled_dsdl

    ensure_compiled_dsdl()

    from pyuavcan.application import NodeInfo
    from uavcan.node import Version_1_0 as Version

    ad = AppDescriptor.from_node_info(
        NodeInfo(
            hardware_version=Version(16, 17),
            software_version=Version(26, 27),
            software_vcs_revision_id=0x123456,
            name="org.uavcan.NODE",
            software_image_crc=[0xDEADBEEF],
        )
    )
    assert ad.name == "org.uavcan.node"
    assert ad.hw_maj == 16
    assert ad.hw_min == 17
    assert ad.sw_maj == 26
    assert ad.sw_min == 27
    assert ad.sw_vcs == 0x123456
    assert ad.sw_crc == 0xDEADBEEF

    ad = AppDescriptor.from_node_info(
        NodeInfo(
            software_version=Version(26, 27),
            name="org.uavcan.NODE",
        )
    )
    assert ad.name == "org.uavcan.node"
    assert ad.hw_maj is None
    assert ad.hw_min is None
    assert ad.sw_maj == 26
    assert ad.sw_min == 27
    assert ad.sw_vcs is None
    assert ad.sw_crc is None


def _unittest_app_descriptor_from_file_name() -> None:
    assert "org.uavcan.node-16.17-26.27.0000000000123456.00000000deadbeef.app" == str(
        AppDescriptor.from_file_name("org.uavcan.NODE-16.17-26.27.123456.DEADBEEF.application.bin")
    )
    assert "org.uavcan.node-16-26.27.0000000000123456.00000000deadbeef.app" == str(
        AppDescriptor.from_file_name("org.uavcan.NODE-16-26.27.123456.DEADBEEF.application.bin")
    )
    assert "org.uavcan.node-26.27.0000000000123456.00000000deadbeef.app" == str(
        AppDescriptor.from_file_name("org.uavcan.NODE-26.27.123456.DEADBEEF.application.bin")
    )
    assert "org.uavcan.node-26.27.0000000000123456.app" == str(
        AppDescriptor.from_file_name("org.uavcan.NODE-26.27.123456.application.bin")
    )
    assert "org.uavcan.node-26.27.app" == str(AppDescriptor.from_file_name("org.uavcan.NODE-26.27.app"))
    assert "org.uavcan.node-16.17-26.27.app" == str(AppDescriptor.from_file_name("org.uavcan.NODE-16.17-26.27.app"))

    assert None is AppDescriptor.from_file_name("org.uavcan.node-z-26.27.app")
    assert None is AppDescriptor.from_file_name("org.uavcan.NODE-16.17-26.27.123456.DEADBEEF.bin")


def _unittest_app_descriptor_equivalency() -> None:
    def ffn(s: str) -> AppDescriptor:
        x = AppDescriptor.from_file_name(s)
        assert x
        return x

    # Missing parameters on either side are matched as equivalent.
    assert ffn("z-1.2-3.4.a.b.app").is_equivalent(ffn("z-1.2-3.4.a.b.app"))
    assert ffn("z-1.2-3.4.a.app").is_equivalent(ffn("z-1.2-3.4.a.b.app"))
    assert ffn("z-1.2-3.4.app").is_equivalent(ffn("z-1.2-3.4.a.b.app"))
    assert ffn("z-1-3.4.app").is_equivalent(ffn("z-1.2-3.4.a.b.app"))
    assert ffn("z-3.4.app").is_equivalent(ffn("z-1.2-3.4.a.b.app"))
    assert ffn("z-1.2-3.4.a.b.app").is_equivalent(ffn("z-1.2-3.4.a.app"))
    assert ffn("z-1.2-3.4.a.b.app").is_equivalent(ffn("z-1.2-3.4.app"))
    assert ffn("z-1.2-3.4.a.b.app").is_equivalent(ffn("z-1-3.4.a.b.app"))
    assert ffn("z-1.2-3.4.a.b.app").is_equivalent(ffn("z-3.4.a.b.app"))

    assert not ffn("z-1.2-3.4.a.b.app").is_equivalent(ffn("x-1.2-3.4.a.b.app"))  # Name
    assert not ffn("z-1.2-3.4.a.b.app").is_equivalent(ffn("z-2.2-3.4.a.b.app"))  # Hw major
    assert not ffn("z-1.2-3.4.a.b.app").is_equivalent(ffn("z-1.3-3.4.a.b.app"))  # Hw minor
    assert not ffn("z-1.2-3.4.a.b.app").is_equivalent(ffn("z-1.2-4.4.a.b.app"))  # Sw major
    assert not ffn("z-1.2-3.4.a.b.app").is_equivalent(ffn("z-1.2-3.3.a.b.app"))  # Sw minor
    assert not ffn("z-1.2-3.4.a.b.app").is_equivalent(ffn("z-1.2-3.4.c.b.app"))  # VCS
    assert not ffn("z-1.2-3.4.a.b.app").is_equivalent(ffn("z-1.2-3.4.a.c.app"))  # CRC


def _unittest_app_descriptor_update() -> None:
    def ffn(s: str) -> AppDescriptor:
        x = AppDescriptor.from_file_name(s)
        assert x
        return x

    assert not ffn("z-1.2-3.4.a.b.app").should_update_to(ffn("z-1.2-3.4.a.b.app"))  # Base, same

    assert ffn("z-1.2-3.4.a.b.app").should_update_to(ffn("z-1.2-4.4.a.b.app"))  # Sw major
    assert ffn("z-1.2-3.4.a.b.app").should_update_to(ffn("z-1.2-3.5.a.b.app"))  # Sw minor

    assert not ffn("z-1.2-3.4.a.b.app").should_update_to(ffn("z-1.2-3.3.a.b.app"))  # rhs is older
    assert ffn("z-1.2-3.4.a.b.app").should_update_to(ffn("z-1.2-3.3.a.c.app"))  # CRC is different, version ignored
    assert ffn("z-1.2-3.4.a.b.app").should_update_to(ffn("z-1.2-3.3.a.c.app"))  # CRC is different, version ignored
    assert ffn("z-1.2-3.4.a.b.app").should_update_to(ffn("z-3.3.a.c.app"))  # CRC is different, version ignored

    assert ffn("z-1.2-3.4.a.b.app").should_update_to(ffn("z-1.2-3.4.c.b.app"))  # VCS hash differs
    assert ffn("z-1.2-3.4.a.b.app").should_update_to(ffn("z-1.2-3.4.c.app"))  # Same without CRC
    assert ffn("z-1.2-3.4.a.app").should_update_to(ffn("z-1.2-3.4.c.b.app"))  # Same without CRC

    assert not ffn("z-1.2-3.4.a.b.app").should_update_to(ffn("x-1.2-3.3.a.c.app"))  # Wrong name
    assert not ffn("z-1.2-3.4.a.b.app").should_update_to(ffn("x-1.3-3.3.a.c.app"))  # Wrong hardware
    assert not ffn("z-1.2-3.4.a.b.app").should_update_to(ffn("x-2.2-3.3.a.c.app"))  # Wrong hardware

    assert not ffn("z-1.2-3.4.a.b.app").should_update_to(ffn("z-1.2-3.4.a.b.app"))
    assert not ffn("z-1.2-3.4.a.b.app").should_update_to(ffn("z-1.2-2.4.a.b.app"))  # Sw major
    assert not ffn("z-1.2-3.4.a.b.app").should_update_to(ffn("z-1.2-3.3.a.b.app"))  # Sw minor
