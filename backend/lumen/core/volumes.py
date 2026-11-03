"""File system volume identification (used to recognise external drives later)."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class VolumeInfo:
    serial: str | None
    label: str | None


def get_volume_info(path: Path) -> VolumeInfo:
    if sys.platform != "win32":
        return VolumeInfo(serial=None, label=None)
    return _windows_volume_info(path)


def _windows_volume_info(path: Path) -> VolumeInfo:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    mount_point = ctypes.create_unicode_buffer(1024)
    if not kernel32.GetVolumePathNameW(str(path), mount_point, len(mount_point)):
        return VolumeInfo(serial=None, label=None)

    label = ctypes.create_unicode_buffer(261)
    serial = wintypes.DWORD()
    max_component = wintypes.DWORD()
    flags = wintypes.DWORD()
    fs_name = ctypes.create_unicode_buffer(261)
    ok = kernel32.GetVolumeInformationW(
        mount_point.value,
        label,
        len(label),
        ctypes.byref(serial),
        ctypes.byref(max_component),
        ctypes.byref(flags),
        fs_name,
        len(fs_name),
    )
    if not ok:
        return VolumeInfo(serial=None, label=None)
    return VolumeInfo(serial=f"{serial.value:08X}", label=label.value or None)
