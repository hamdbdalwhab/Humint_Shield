"""Local removable-drive detection and safe USB deployment."""
from __future__ import annotations

import os

import pytest

from app.services import usb_drive_service as svc


def test_safe_file_name_blocks_path_traversal() -> None:
    assert "/" not in svc.safe_file_name("../evil.html", fallback="x.html")
    assert "\\" not in svc.safe_file_name("..\evil.html", fallback="x.html")
    assert svc.safe_file_name("   ", fallback="fallback.html") == "fallback.html"
    assert svc.safe_file_name('bad"name.html', fallback="x.html") == "bad'name.html"


def test_normalise_drive_accepts_letter_forms() -> None:
    assert svc._normalise_drive("h") == "H:\\"
    assert svc._normalise_drive("H:" ) == "H:\\"
    assert svc._normalise_drive("H:\\") == "H:\\"


def test_normalise_drive_rejects_garbage() -> None:
    with pytest.raises(svc.USBDriveError):
        svc._normalise_drive("")
    with pytest.raises(svc.USBDriveError):
        svc._normalise_drive("1:")


def test_resolve_drive_refuses_unknown_and_system(monkeypatch) -> None:
    fake = [
        svc.DriveInfo("C:", "Win", "NTFS", False, True, "fixed", 1.0, 2.0, True),
        svc.DriveInfo("H:", "USB", "FAT32", True, False, "removable", 3.0, 8.0, True),
    ]
    monkeypatch.setattr(svc, "list_drives", lambda: fake)

    assert svc.resolve_drive("H:").drive == "H:"
    with pytest.raises(svc.USBDriveError):
        svc.resolve_drive("C:")  # system drive
    with pytest.raises(svc.USBDriveError):
        svc.resolve_drive("Z:")  # not connected


def test_resolve_drive_refuses_fixed_disk(monkeypatch) -> None:
    monkeypatch.setattr(
        svc,
        "list_drives",
        lambda: [svc.DriveInfo("E:", "BK", "NTFS", False, False, "fixed", 5.0, 9.0, True)],
    )
    with pytest.raises(svc.USBDriveError) as excinfo:
        svc.resolve_drive("E:")
    assert "not a removable" in str(excinfo.value)


@pytest.mark.skipif(os.name != "nt", reason="Windows drive enumeration")
def test_list_drives_marks_the_boot_volume() -> None:
    drives = svc.list_drives()
    assert drives, "at least the system drive must be visible"
    assert any(drive.is_system for drive in drives)


def test_drives_payload_shape() -> None:
    payload = svc.drives_payload()
    assert set(payload) == {"host", "platform", "drives"}
    assert isinstance(payload["drives"], list)
