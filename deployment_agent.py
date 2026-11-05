"""HUMINT Shield - USB Local Deployment Agent.

Enterprise Local Companion for USB Security Awareness & Incident Response Simulations.
Runs a secure local WebSocket server on ws://127.0.0.1:8089 to interface between
the React Admin Dashboard and physical storage media.

Usage:
    python deployment_agent.py
    (or build standalone .exe using PyInstaller: pyinstaller --onefile deployment_agent.py)
"""
import asyncio
import base64
import ctypes
import json
import logging
import os
import shutil
import string
import sys
from datetime import datetime

try:
    import websockets
except ImportError:
    print("ERROR: websockets package is required. Install via: pip install websockets")
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("USBDeploymentAgent")

AGENT_PORT = 8089
AGENT_HOST = "127.0.0.1"


def get_connected_drives() -> list[dict]:
    """Scan and list connected storage drives using Windows API."""
    drives = []
    if os.name != "nt":
        # Fallback for non-Windows dev environments
        return [{"drive": "/media/usb", "label": "Dev Virtual USB", "is_removable": True, "type_name": "Removable USB", "free_gb": 16.0, "total_gb": 16.0}]

    bitmask = ctypes.windll.kernel32.GetLogicalDrives()
    for letter in string.ascii_uppercase:
        if bitmask & 1:
            drive_path = f"{letter}:\\"
            drive_type = ctypes.windll.kernel32.GetDriveTypeW(drive_path)
            # 2: DRIVE_REMOVABLE, 3: DRIVE_FIXED, 4: DRIVE_REMOTE, 5: DRIVE_CDROM
            is_removable = (drive_type == 2)
            type_name = "Removable USB" if is_removable else ("Local Fixed Drive" if drive_type == 3 else "Network / Optical")

            vol_buf = ctypes.create_unicode_buffer(1024)
            fs_buf = ctypes.create_unicode_buffer(1024)
            try:
                ctypes.windll.kernel32.GetVolumeInformationW(
                    drive_path,
                    vol_buf,
                    ctypes.sizeof(vol_buf),
                    None,
                    None,
                    None,
                    fs_buf,
                    ctypes.sizeof(fs_buf),
                )
                volume_label = vol_buf.value or "Disk"
                fs_type = fs_buf.value or "FAT32/NTFS"
            except Exception:
                volume_label = "Disk"
                fs_type = "Unknown"

            free_gb, total_gb = 0.0, 0.0
            try:
                usage = shutil.disk_usage(drive_path)
                free_gb = round(usage.free / (1024**3), 2)
                total_gb = round(usage.total / (1024**3), 2)
            except Exception:
                pass

            drives.append({
                "drive": drive_path,
                "label": volume_label,
                "fs_type": fs_type,
                "is_removable": is_removable,
                "type_name": type_name,
                "free_gb": free_gb,
                "total_gb": total_gb,
            })
        bitmask >>= 1
    return drives


async def handle_client(websocket):
    client_ip = websocket.remote_address[0] if websocket.remote_address else "local"
    logger.info(f"Dashboard connected from {client_ip}")

    # Send initial status
    await websocket.send(json.dumps({
        "type": "agent_connected",
        "agent": "HUMINT Shield USB Deployment Agent",
        "version": "1.0.0",
        "timestamp": datetime.now().isoformat(),
    }))

    try:
        async for raw_message in websocket:
            try:
                msg = json.loads(raw_message)
            except json.JSONDecodeError:
                await websocket.send(json.dumps({"type": "error", "message": "Invalid JSON payload"}))
                continue

            action = msg.get("action")
            logger.info(f"Received action: {action}")

            if action == "ping":
                await websocket.send(json.dumps({"type": "pong", "time": datetime.now().isoformat()}))

            elif action == "list_drives":
                drives = get_connected_drives()
                await websocket.send(json.dumps({
                    "type": "drives_list",
                    "drives": drives,
                    "count": len(drives),
                }))

            elif action == "deploy_test_assets":
                target_drive = msg.get("drive")
                assets = msg.get("assets", [])

                if not target_drive:
                    await websocket.send(json.dumps({"type": "error", "message": "Missing target drive letter"}))
                    continue

                if not os.path.exists(target_drive):
                    await websocket.send(json.dumps({"type": "error", "message": f"Target drive {target_drive} does not exist"}))
                    continue

                total_files = len(assets)
                logger.info(f"Deploying {total_files} safe simulation assets to {target_drive}...")

                written_files = []
                for i, asset in enumerate(assets):
                    fname = asset.get("filename", "notice.txt")
                    # Prevent directory traversal
                    clean_fname = os.path.basename(fname)
                    b64_content = asset.get("content_base64", "")

                    dest_path = os.path.join(target_drive, clean_fname)

                    # Update progress
                    percent = int(((i + 1) / (total_files + 1)) * 100)
                    await websocket.send(json.dumps({
                        "type": "progress",
                        "percent": percent,
                        "step": f"Writing {clean_fname}...",
                        "current_file": clean_fname,
                    }))
                    await asyncio.sleep(0.15)  # Smooth UI update

                    try:
                        file_bytes = base64.b64decode(b64_content)
                        with open(dest_path, "wb") as f:
                            f.write(file_bytes)
                        written_files.append(clean_fname)
                        logger.info(f"  + Wrote {dest_path} ({len(file_bytes)} bytes)")
                    except Exception as exc:
                        logger.error(f"Failed to write {clean_fname}: {exc}")
                        await websocket.send(json.dumps({
                            "type": "error",
                            "message": f"Failed to write file {clean_fname}: {str(exc)}",
                        }))
                        break
                else:
                    # Final 100% complete
                    await websocket.send(json.dumps({
                        "type": "deployed_success",
                        "drive": target_drive,
                        "files": written_files,
                        "count": len(written_files),
                        "timestamp": datetime.now().isoformat(),
                        "message": f"Successfully deployed {len(written_files)} awareness files to {target_drive}",
                    }))
                    logger.info(f"Deployment to {target_drive} completed successfully!")

            else:
                await websocket.send(json.dumps({"type": "unknown_action", "action": action}))

    except websockets.exceptions.ConnectionClosed:
        logger.info("Dashboard disconnected")
    except Exception as exc:
        logger.error(f"Error handling client: {exc}")


async def main():
    logger.info(f"Starting USB Deployment Agent on ws://{AGENT_HOST}:{AGENT_PORT}...")
    async with websockets.serve(handle_client, AGENT_HOST, AGENT_PORT):
        logger.info("Agent is live and listening for connections from HUMINT Shield Dashboard.")
        await asyncio.Future()  # run forever


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Agent stopped by user.")
