"""Local removable-drive discovery and safe USB deployment.

The application runs on the operator's own machine, so it can enumerate the
drives that are physically attached to that machine and write an awareness
document straight to the chosen USB stick.  No separate companion agent is
required (the legacy ``ws://127.0.0.1:8089`` bridge remains supported).

Safety rules enforced here:

* only drives the operating system reports as **removable** are written to;
* the system/boot volume is always refused;
* the destination file name is sanitised and cannot contain a path separator,
  so a campaign name can never redirect a write outside the drive root;
* every write is explicit: the caller names the drive it wants.
"""
from __future__ import annotations

import os
import platform
import re
import shutil
import time
from dataclasses import asdict, dataclass
from pathlib import Path

#: ``GetDriveTypeW`` return value for removable media.
_DRIVE_REMOVABLE = 2
_DRIVE_FIXED = 3
_DRIVE_REMOTE = 4
_DRIVE_CDROM = 5
_DRIVE_RAMDISK = 6

_TYPE_NAMES = {
    _DRIVE_REMOVABLE: "removable",
    _DRIVE_FIXED: "fixed",
    _DRIVE_REMOTE: "network",
    _DRIVE_CDROM: "optical",
    _DRIVE_RAMDISK: "ramdisk",
}


class USBDriveError(ValueError):
    """Raised when a drive cannot be used for a physical drop."""


@dataclass(slots=True)
class DriveInfo:
    """One mounted volume visible to the application host."""

    drive: str
    label: str
    fs_type: str
    is_removable: bool
    is_system: bool
    type_name: str
    free_gb: float
    total_gb: float
    writable: bool


def _windows_drive_type(root: str) -> int:
    """Return the Win32 drive type for ``root`` (``0`` on failure)."""
    try:
        import ctypes

        return int(ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(root)))
    except Exception:  # pragma: no cover - non-Windows / restricted host
        return 0


def _system_roots() -> set[str]:
    """Return normalised roots of the volume Windows booted from."""
    roots: set[str] = set()
    for var in ("SystemDrive", "SystemRoot", "windir"):
        value = os.environ.get(var)
        if not value:
            continue
        match = re.match(r"^([A-Za-z]:)", value)
        if match:
            roots.add(match.group(1).upper() + "\\")
    if not roots:  # pragma: no cover - defensive
        roots.add(str(Path(os.path.abspath(os.sep))).upper())
    return roots


def list_drives() -> list[DriveInfo]:
    """Enumerate mounted volumes with their bus type and free space.

    Returns:
        One :class:`DriveInfo` per mounted volume, removable media first.
    """
    drives: list[DriveInfo] = []
    system_roots = _system_roots() if os.name == "nt" else set()

    if os.name == "nt":
        import string

        candidates = [f"{letter}:\\" for letter in string.ascii_uppercase]
    else:  # pragma: no cover - the product targets Windows operators
        candidates = []

    for root in candidates:
        drive_type = _windows_drive_type(root)
        if drive_type == 0:
            continue
        # Skip optical/network volumes: they are not USB drop targets.
        if drive_type not in (_DRIVE_REMOVABLE, _DRIVE_FIXED, _DRIVE_RAMDISK):
            continue
        try:
            usage = shutil.disk_usage(root)
        except OSError:
            continue
        label = ""
        fs_type = ""
        try:
            import ctypes

            volume_name = ctypes.create_unicode_buffer(261)
            fs_name = ctypes.create_unicode_buffer(261)
            ctypes.windll.kernel32.GetVolumeInformationW(
                ctypes.c_wchar_p(root),
                volume_name,
                261,
                None,
                None,
                None,
                fs_name,
                261,
            )
            label = volume_name.value
            fs_type = fs_name.value
        except Exception:  # pragma: no cover - label is cosmetic
            pass
        drives.append(
            DriveInfo(
                drive=root[:2].upper(),
                label=label,
                fs_type=fs_type,
                is_removable=drive_type == _DRIVE_REMOVABLE,
                is_system=root.upper() in system_roots,
                type_name=_TYPE_NAMES.get(drive_type, "unknown"),
                free_gb=round(usage.free / (1024**3), 2),
                total_gb=round(usage.total / (1024**3), 2),
                writable=os.access(root, os.W_OK),
            )
        )

    drives.sort(key=lambda item: (not item.is_removable, item.drive))
    return drives


def platform_name() -> str:
    """Return a short host description for the operator UI."""
    return f"{platform.system()} {platform.release()}".strip()


def _normalise_drive(drive: str) -> str:
    """Validate a drive selection such as ``H``, ``H:`` or ``H:\\``."""
    if not isinstance(drive, str) or not drive.strip():
        raise USBDriveError("A drive letter is required")
    letter = drive.strip().upper()[:1]
    if not letter.isalpha():
        raise USBDriveError(f"Invalid drive selection: {drive!r}")
    return f"{letter}:\\"


def resolve_drive(drive: str) -> DriveInfo:
    """Return the drive metadata, refusing anything unsafe to write to.

    Raises:
        USBDriveError: Unknown, read-only or non-removable drive, or the
            system volume.
    """
    root = _normalise_drive(drive)
    for info in list_drives():
        if info.drive == root[:2].upper():
            if info.is_system:
                raise USBDriveError("Refusing to write to the system drive")
            if not info.is_removable:
                raise USBDriveError(
                    f"{info.drive} is a {info.type_name} disk, not a removable USB stick"
                )
            if not info.writable:
                raise USBDriveError(f"{info.drive} is not writable")
            return info
    raise USBDriveError(f"Drive {root[:2]} is not connected")


def safe_file_name(name: str, *, fallback: str) -> str:
    """Return a file name that cannot escape the drive root."""
    candidate = (name or "").replace("\\", "-").replace("/", "-").replace('"', "'")
    candidate = re.sub(r"[\x00-\x1f\x7f]", "", candidate).strip(" .")
    if not candidate:
        candidate = fallback
    if len(candidate) > 120:
        stem, dot, suffix = candidate.rpartition(".")
        candidate = (stem[:116] + dot + suffix) if dot else candidate[:120]
    return candidate


def deploy_files(drive: str, files: list[tuple[str, bytes]]) -> dict:
    """Write ``files`` into the root of a validated removable drive.

    Args:
        drive: Drive selection such as ``H:``.
        files: ``(file_name, content)`` pairs.

    Returns:
        ``{"drive", "label", "files": [...], "total_bytes"}``.

    Raises:
        USBDriveError: Invalid target drive or an empty file list.
    """
    info = resolve_drive(drive)
    if not files:
        raise USBDriveError("No files were supplied for the USB drive")
    root = Path(f"{info.drive}\\")
    required = sum(len(content) for _, content in files)
    # Refuse before writing anything: a half-copied lure is worse than a clear
    # error, because the operator would deploy an incomplete stick.
    try:
        free_bytes = shutil.disk_usage(root).free
    except OSError:  # pragma: no cover - the drive can vanish mid-request
        free_bytes = None
    if free_bytes is not None and required > free_bytes:
        raise USBDriveError(
            f"Not enough free space on {info.drive}: "
            f"{required} bytes needed, {free_bytes} available"
        )
    written: list[dict] = []
    total = 0
    for index, (name, content) in enumerate(files, start=1):
        file_name = safe_file_name(name, fallback=f"awareness-{index}.html")
        target = root / file_name
        if target.parent != root:  # pragma: no cover - safe_file_name prevents this
            raise USBDriveError(f"Refusing to write outside the drive root: {file_name}")
        # A file already on the stick can be briefly locked by antivirus, the
        # Windows indexer or a preview pane.  Retry first; if the lock persists,
        # write a new name instead of failing the whole deployment.
        for attempt in range(3):
            try:
                target.write_bytes(content)
                break
            except PermissionError:
                if attempt == 2:
                    stem, dot, suffix = file_name.rpartition(".")
                    alt = (
                        f"{stem} (USB){dot}{suffix}"
                        if dot
                        else f"{file_name} (USB)"
                    )
                    target = root / safe_file_name(alt, fallback=f"awareness-{index}.html")
                    try:
                        target.write_bytes(content)
                        file_name = target.name
                    except OSError as exc:
                        raise USBDriveError(
                            f"{file_name} is locked by another program "
                            f"(antivirus or file preview). Close it and retry. ({exc})"
                        ) from exc
                else:
                    time.sleep(0.6 * (attempt + 1))
        # Read the size back: a truncated write (full volume, failing flash
        # cell) must never be reported as a successful deployment.
        try:
            written_size = target.stat().st_size
        except OSError as exc:  # pragma: no cover - drive removed mid-request
            raise USBDriveError(
                f"Unable to verify {target.name} after writing: {exc}"
            ) from exc
        if written_size != len(content):
            raise USBDriveError(
                f"{target.name} is {written_size} of {len(content)} bytes after "
                "writing; the drive may be full or failing"
            )
        total += len(content)
        written.append({"name": target.name, "bytes": len(content)})
    return {
        "drive": info.drive,
        "label": info.label,
        "files": written,
        "total_bytes": total,
    }


def drives_payload() -> dict:
    """Return the operator-facing drive payload."""
    return {
        "host": platform_name(),
        "platform": platform.system().lower(),
        "drives": [asdict(info) for info in list_drives()],
    }


__all__ = [
    "DriveInfo",
    "USBDriveError",
    "deploy_files",
    "drives_payload",
    "list_drives",
    "platform_name",
    "resolve_drive",
    "safe_file_name",
]
