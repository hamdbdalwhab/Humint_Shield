"""Authenticated downloads for the defensive documentation.

The detailed playbook and the physical USB-drop guide live at the project root
so they can be reviewed, versioned and printed independently of the web build.
These endpoints expose them to the admin dashboard without making the files
public.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse

from app.deps import get_current_user

router = APIRouter(
    prefix="/security",
    tags=["security"],
    dependencies=[Depends(get_current_user)],
)

_PROJECT_ROOT = Path(__file__).resolve().parents[4]
_DOCUMENTS = {
    "playbook": ("DEFENSIVE_PLAYBOOK.md", "text/markdown; charset=utf-8"),
    "usb-guide": ("README_USB.md", "text/markdown; charset=utf-8"),
}


def _document_path(key: str) -> tuple[Path, str]:
    """Resolve a fixed, allow-listed document path."""
    entry = _DOCUMENTS.get(key)
    if entry is None:  # pragma: no cover - route allow-list
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    filename, media_type = entry
    path = _PROJECT_ROOT / filename
    if not path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{filename} is not available in this deployment",
        )
    return path, media_type


@router.get(
    "/playbook",
    summary="Download the defensive playbook (Markdown)",
    response_class=FileResponse,
)
async def download_playbook() -> FileResponse:
    """Return the complete detection, IR and hardening playbook."""
    path, media_type = _document_path("playbook")
    return FileResponse(
        path,
        media_type=media_type,
        filename="DEFENSIVE_PLAYBOOK.md",
    )


@router.get(
    "/usb-guide",
    summary="Download the safe USB-drop exercise guide (Markdown)",
    response_class=FileResponse,
)
async def download_usb_guide() -> FileResponse:
    """Return the operator guide for the physical USB-drop exercise."""
    path, media_type = _document_path("usb-guide")
    return FileResponse(
        path,
        media_type=media_type,
        filename="README_USB.md",
    )


__all__ = ["router"]
