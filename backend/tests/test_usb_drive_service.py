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


def _fake_removable(drive: str) -> svc.DriveInfo:
    return svc.DriveInfo(drive, "USB", "FAT32", True, False, "removable", 1.0, 2.0, True)


def test_deploy_refuses_a_full_drive_before_writing(monkeypatch) -> None:
    """A drive without room fails with a clear error, not a truncated copy."""
    from types import SimpleNamespace

    monkeypatch.setattr(svc, "resolve_drive", lambda drive: _fake_removable("H:\\"))
    monkeypatch.setattr(svc.shutil, "disk_usage", lambda _root: SimpleNamespace(free=10))

    with pytest.raises(svc.USBDriveError, match="Not enough free space"):
        svc.deploy_files("H:", [("awareness.html", b"x" * 1000)])


@pytest.mark.skipif(os.name != "nt", reason="writes to a Windows path")
def test_deploy_verifies_every_written_file(monkeypatch, tmp_path) -> None:
    """Each file is read back so a short write cannot be reported as success."""
    monkeypatch.setattr(
        svc, "resolve_drive", lambda drive: _fake_removable(str(tmp_path) + "\\")
    )
    result = svc.deploy_files("H:", [("awareness.html", b"hello world")])

    assert (tmp_path / "awareness.html").read_bytes() == b"hello world"
    assert result["files"] == [{"name": "awareness.html", "bytes": 11}]
    assert result["total_bytes"] == 11


@pytest.mark.skipif(os.name != "nt", reason="writes to a Windows path")
def test_deploy_detects_a_truncated_write(monkeypatch, tmp_path) -> None:
    """A partial write must raise instead of leaving a silent half-copy."""
    from pathlib import Path

    monkeypatch.setattr(
        svc, "resolve_drive", lambda drive: _fake_removable(str(tmp_path) + "\\")
    )
    real_write = Path.write_bytes
    monkeypatch.setattr(
        Path, "write_bytes", lambda self, data: real_write(self, bytes(data)[:2])
    )

    with pytest.raises(svc.USBDriveError, match="after writing"):
        svc.deploy_files("H:", [("awareness.html", b"hello world")])
