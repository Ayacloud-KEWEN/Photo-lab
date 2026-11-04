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


def incurs_seek_penalty(path: Path) -> bool | None:
    """True for a spinning disk (seeks are slow), False for an SSD, None when unknown."""
    if sys.platform != "win32":
        return None
    try:
        return _windows_seek_penalty(path)
    except OSError:
        return None


def _windows_seek_penalty(path: Path) -> bool | None:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.restype = wintypes.HANDLE
    mount_point = ctypes.create_unicode_buffer(1024)
    if not kernel32.GetVolumePathNameW(str(path), mount_point, len(mount_point)):
        return None
    drive = mount_point.value.rstrip("\\")
    if len(drive) != 2 or drive[1] != ":":
        return None  # network share or mounted folder

    class Query(ctypes.Structure):
        _fields_ = (
            ("property_id", wintypes.DWORD),
            ("query_type", wintypes.DWORD),
            ("extra", ctypes.c_ubyte * 1),
        )

    class SeekPenalty(ctypes.Structure):
        _fields_ = (
            ("version", wintypes.DWORD),
            ("size", wintypes.DWORD),
            ("incurs_seek_penalty", wintypes.BOOLEAN),
        )

    share_read_write = 0x1 | 0x2
    open_existing = 3
    handle = kernel32.CreateFileW(
        "\\\\.\\" + drive, 0, share_read_write, None, open_existing, 0, None
    )
    if handle in (None, wintypes.HANDLE(-1).value):
        return None
    try:
        query = Query(property_id=7, query_type=0)  # StorageDeviceSeekPenaltyProperty
        result = SeekPenalty()
        returned = wintypes.DWORD()
        ok = kernel32.DeviceIoControl(
            wintypes.HANDLE(handle),
            0x2D1400,  # IOCTL_STORAGE_QUERY_PROPERTY
            ctypes.byref(query),
            ctypes.sizeof(query),
            ctypes.byref(result),
            ctypes.sizeof(result),
            ctypes.byref(returned),
            None,
        )
        return bool(result.incurs_seek_penalty) if ok else None
    finally:
        kernel32.CloseHandle(wintypes.HANDLE(handle))
