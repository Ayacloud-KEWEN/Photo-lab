"""Import from iPhone: list connected phones, count what is new, start the import task."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from lumen.core.errors import ConflictError, NotFoundError
from lumen.library import phone_import
from lumen.media.phone import PhoneDevice, PhoneError
from lumen.schemas.phones import Phone, PhoneImport, PhoneList, PhoneSummary
from lumen.schemas.settings import AppSettingsUpdate
from lumen.services.settings import get_settings, update_settings
from lumen.tasks import queue


def default_folder() -> Path:
    photos = Path("D:/照片")
    if sys.platform == "win32" and photos.is_dir():
        return photos / "iPhone"
    return Path.home() / "Pictures" / "iPhone"


def import_folder(conn: sqlite3.Connection) -> Path:
    chosen = get_settings(conn).phone_import_folder
    return Path(chosen) if chosen else default_folder()


def _devices() -> list[PhoneDevice]:
    try:
        return phone_import.SOURCE.devices()
    except PhoneError:
        return []


def list_phones(conn: sqlite3.Connection) -> PhoneList:
    settings = get_settings(conn)
    available = True
    try:
        devices = phone_import.SOURCE.devices()
    except PhoneError:
        devices, available = [], False
    return PhoneList(
        items=[Phone(id=d.id, name=d.name, status=d.status) for d in devices],
        folder=str(import_folder(conn)),
        include_edited=settings.phone_import_edited,
        available=available,
    )


def _device(device_id: str) -> PhoneDevice:
    for device in _devices():
        if device.id == device_id:
            return device
    raise NotFoundError("The phone is not connected", details={"id": device_id})


def summary(conn: sqlite3.Connection, device_id: str) -> PhoneSummary:
    """Count what an import would copy (lists the whole phone: can take a while)."""
    device = _device(device_id)
    include_edited = get_settings(conn).phone_import_edited
    try:
        with phone_import.SOURCE.open(device_id) as session:
            files = list(session.files())
    except PhoneError as exc:
        raise ConflictError(str(exc), details={"id": device_id}) from exc
    todo = phone_import.plan(conn, device.serial, files, include_edited=include_edited)
    counted = [f for f in files if include_edited or not phone_import.is_edited(f)]
    return PhoneSummary(
        total=len(counted),
        new_count=len(todo.copy),
        new_bytes=sum(f.size for f in todo.copy),
        already=todo.done + len(todo.in_library),
    )


def start_import(conn: sqlite3.Connection, device_id: str, body: PhoneImport) -> int:
    device = _device(device_id)
    if device.status != "ready":
        raise ConflictError(
            "Unlock the phone and allow this computer to read it", details={"id": device_id}
        )
    if body.folder is not None or body.include_edited is not None:
        update_settings(
            conn,
            AppSettingsUpdate(
                phone_import_folder=body.folder, phone_import_edited=body.include_edited
            ),
        )
    return queue.enqueue(
        conn,
        phone_import.PHONE_IMPORT_TASK,
        payload={
            "device_id": device.id,
            "serial": device.serial,
            "dest": str(import_folder(conn)),
            "include_edited": get_settings(conn).phone_import_edited,
        },
    )
