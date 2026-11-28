"""HUMINT Shield - USB Local Deployment Agent (Enterprise Edition).

Enterprise Local Companion for USB Security Awareness & Incident Response Simulations.
Runs a secure local WebSocket server on ws://127.0.0.1:8089 to interface between
the React Admin Dashboard and physical storage media.

Features:
- Real-time drive insertion/removal hardware monitoring and live push notifications.
- Intelligent USB drive detection (handles both removable-bit and fixed-bit flash drives).
- Protection against accidental writes to the host system OS disk (C:\\).
- Safe, authorized incident response awareness asset deployment.
"""
from __future__ import annotations

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
from typing import Set

# Configure Windows UTF-8 stdout if possible
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Ensure websockets and psutil are installed
try:
    import websockets
except ImportError:
    print("\n[!] FATAL: 'websockets' package is not installed.")
    print("    Please run: pip install websockets psutil\n")
    sys.exit(1)

try:
    import psutil
except ImportError:
    psutil = None

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("USBDeploymentAgent")

AGENT_PORT = 8089
AGENT_HOST = "127.0.0.1"

# Track connected dashboards
connected_clients: Set = set()
_last_drives_cache: list[dict] = []


def print_banner() -> None:
    banner = f"""
===============================================================================
  _   _ _   _ __  __ ___ _   _ _____   ____  _     _ _____ _     ____  
 | | | | | | |  \/  |_ _| \ | |_   _| / ___|| |__ (_) ____| |   |  _ \ 
 | |_| | | | | |\/| || ||  \| | | |   \___ \| '_ \| |  _| | |   | | | |
 |  _  | |_| | |  | || || |\  | | |    ___) | | | | | |___| |___| |_| |
 |_| |_|\___/|_|  |_|___|_| \_| |_|   |____/|_| |_|_|_____|_____|____/ 

  USB LOCAL COMPANION AGENT - ENTERPRISE PHYSICAL ASSESSMENT SUITE
===============================================================================
  [+] WebSocket URL : ws://{AGENT_HOST}:{AGENT_PORT}
  [+] Status        : ONLINE & MONITORING HARDWARE PORTS
  [+] Auto-Detect   : Active (Instant push notification when USB is plugged in)
  [+] Host Defense  : System Drive Protection Active (C:\\ Lockout)
-------------------------------------------------------------------------------
  [*] Keep this window OPEN while running USB awareness campaigns.
===============================================================================
"""
    print(banner, flush=True)


def get_system_drive_letter() -> str:
    """Return the system drive root, e.g. 'C'."""
    sys_drive = os.environ.get("SystemDrive", "C:")
    return sys_drive.replace(":", "").replace("\\", "").upper()


def get_connected_drives() -> list[dict]:
    """Scan and list connected storage drives with intelligent USB classification."""
    drives = []
    sys_letter = get_system_drive_letter()

    if os.name != "nt":
        # Fallback for non-Windows dev environments
        return [{
            "drive": "/media/usb",
            "label": "Dev Virtual USB",
            "is_removable": True,
            "is_system": False,
            "type_name": "Removable USB Flash Drive",
            "free_gb": 16.0,
            "total_gb": 16.0,
        }]

    try:
        bitmask = ctypes.windll.kernel32.GetLogicalDrives()
    except Exception as exc:
        logger.error(f"Error querying logical drives: {exc}")
        return []

    # Optional psutil partition map for extra hints
    psutil_map = {}
    if psutil is not None:
        try:
            for part in psutil.disk_partitions(all=True):
                norm_mount = part.mountpoint.rstrip("\\").upper()
                psutil_map[norm_mount] = part
        except Exception:
            pass

    for letter in string.ascii_uppercase:
        if bitmask & 1:
            drive_path = f"{letter}:\\"
            is_sys = (letter == sys_letter)
            try:
                drive_type = ctypes.windll.kernel32.GetDriveTypeW(drive_path)
                # 2: DRIVE_REMOVABLE, 3: DRIVE_FIXED, 4: DRIVE_REMOTE, 5: DRIVE_CDROM

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
                    volume_label = vol_buf.value or ("USB Drive" if drive_type == 2 else "Local Disk")
                    fs_type = fs_buf.value or "FAT32/NTFS"
                except Exception:
                    volume_label = "USB Drive" if drive_type == 2 else "Local Disk"
                    fs_type = "Unknown"

                free_gb, total_gb = 0.0, 0.0
                try:
                    usage = shutil.disk_usage(drive_path)
                    free_gb = round(usage.free / (1024**3), 2)
                    total_gb = round(usage.total / (1024**3), 2)
                except Exception:
                    pass

                # Classification logic:
                # 1. Windows kernel says removable (drive_type == 2)
                # 2. Or non-system drive with removable flag from psutil
                # 3. Or non-system drive formatted as FAT32 / exFAT
                # 4. Or non-system drive with capacity <= 128 GB (typical USB flash drive)
                is_removable = (drive_type == 2)
                if not is_removable and not is_sys:
                    if fs_type.upper() in ("FAT", "FAT32", "EXFAT"):
                        is_removable = True
                    elif 0 < total_gb <= 128.0 and drive_type == 3:
                        is_removable = True

                if is_sys:
                    type_name = "Host OS System Drive (Protected)"
                elif is_removable:
                    type_name = "Removable USB Flash Drive"
                elif drive_type == 3:
                    type_name = "Secondary Fixed Storage"
                elif drive_type == 4:
                    type_name = "Network Share"
                elif drive_type == 5:
                    type_name = "Optical CD/DVD Drive"
                else:
                    type_name = "External Storage"

                drives.append({
                    "drive": drive_path,
                    "label": volume_label,
                    "fs_type": fs_type,
                    "is_removable": is_removable,
                    "is_system": is_sys,
                    "type_name": type_name,
                    "free_gb": free_gb,
                    "total_gb": total_gb,
                })
            except Exception as e:
                logger.debug(f"Skipping drive {drive_path}: {e}")
        bitmask >>= 1

    # Sort so removable USBs appear at the top, and system drive at the bottom
    drives.sort(key=lambda d: (not d["is_removable"], d["is_system"], d["drive"]))
    return drives


async def broadcast_drives_update(event_name: str = "drive_change") -> None:
    """Notify all connected React dashboard instances of drive changes."""
    if not connected_clients:
        return
    drives = get_connected_drives()
    payload = json.dumps({
        "type": "drives_list",
        "drives": drives,
        "count": len(drives),
        "event": event_name,
        "timestamp": datetime.now().isoformat(),
    })
    coros = [client.send(payload) for client in list(connected_clients)]
    if coros:
        await asyncio.gather(*coros, return_exceptions=True)


async def hardware_monitor_loop():
    """Background task polling Windows drive changes every 1.5 seconds."""
    global _last_drives_cache
    _last_drives_cache = get_connected_drives()

    while True:
        try:
            await asyncio.sleep(1.5)
            current = get_connected_drives()
            prev_keys = {d["drive"]: (d["label"], d["total_gb"]) for d in _last_drives_cache}
            curr_keys = {d["drive"]: (d["label"], d["total_gb"]) for d in current}

            if prev_keys != curr_keys:
                added = set(curr_keys.keys()) - set(prev_keys.keys())
                removed = set(prev_keys.keys()) - set(curr_keys.keys())
                if added:
                    logger.info(f"[+] USB / Drive INSERTED: {list(added)}")
                if removed:
                    logger.info(f"[-] USB / Drive REMOVED: {list(removed)}")
                _last_drives_cache = current
                await broadcast_drives_update("drive_change")
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.debug(f"Monitor error: {exc}")


async def handle_client(websocket):
    client_ip = websocket.remote_address[0] if websocket.remote_address else "local"
    logger.info(f"[+] Admin Dashboard connected from {client_ip}")
    connected_clients.add(websocket)

    # Send initial handshake with current drives immediately
    drives = get_connected_drives()
    await websocket.send(json.dumps({
        "type": "agent_connected",
        "agent": "HUMINT Shield USB Deployment Agent",
        "version": "2.0.0-Enterprise",
        "timestamp": datetime.now().isoformat(),
        "drives": drives,
    }))

    try:
        async for raw_message in websocket:
            try:
                msg = json.loads(raw_message)
            except json.JSONDecodeError:
                await websocket.send(json.dumps({"type": "error", "message": "Invalid JSON payload"}))
                continue

            action = msg.get("action")
            logger.info(f"[*] Request received: {action}")

            if action == "ping":
                await websocket.send(json.dumps({"type": "pong", "time": datetime.now().isoformat()}))

            elif action == "list_drives":
                current_drives = get_connected_drives()
                removable_count = sum(1 for d in current_drives if d.get("is_removable"))
                logger.info(f"[i] Scanned {len(current_drives)} drives ({removable_count} removable USB)")
                await websocket.send(json.dumps({
                    "type": "drives_list",
                    "drives": current_drives,
                    "count": len(current_drives),
                }))

            elif action == "deploy_test_assets":
                target_drive = msg.get("drive")
                assets = msg.get("assets", [])

                if not target_drive:
                    await websocket.send(json.dumps({"type": "error", "message": "Missing target drive letter"}))
                    continue

                # Host defense: block writing to system OS drive
                sys_letter = get_system_drive_letter()
                target_letter = target_drive.replace(":", "").replace("\\", "").upper()
                if target_letter == sys_letter:
                    logger.warning(f"[BLOCKED] Prevented attempt to deploy payload to Host System Drive ({target_drive})!")
                    await websocket.send(json.dumps({
                        "type": "error",
                        "message": f"حماية النظام مفعلة: لا يمكن نشر ملفات المحاكاة على قرص النظام الرئيسي ({target_drive}). يرجى اختيار فلاشة USB خارجية.",
                    }))
                    continue

                if not os.path.exists(target_drive):
                    await websocket.send(json.dumps({"type": "error", "message": f"Target drive '{target_drive}' not detected"}))
                    continue

                total_files = len(assets)
                logger.info(f"[*] Deploying {total_files} safe simulation assets to {target_drive}...")

                written_files = []
                for i, asset in enumerate(assets):
                    fname = asset.get("filename", "notice.txt")
                    clean_fname = os.path.basename(fname)
                    b64_content = asset.get("content_base64", "")
                    dest_path = os.path.join(target_drive, clean_fname)

                    # Update progress
                    percent = int(((i + 1) / (total_files + 1)) * 100)
                    await websocket.send(json.dumps({
                        "type": "progress",
                        "percent": percent,
                        "step": f"كتابة {clean_fname}...",
                        "current_file": clean_fname,
                    }))
                    await asyncio.sleep(0.12)  # Smooth UI update

                    try:
                        file_bytes = base64.b64decode(b64_content)
                        with open(dest_path, "wb") as f:
                            f.write(file_bytes)
                        written_files.append(clean_fname)
                        logger.info(f"  + [OK] Wrote {clean_fname} ({len(file_bytes)} bytes)")
                    except Exception as exc:
                        logger.error(f"  - [FAIL] Failed to write {clean_fname}: {exc}")
                        await websocket.send(json.dumps({
                            "type": "error",
                            "message": f"فشل كتابة الملف {clean_fname}: {str(exc)}",
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
                        "message": f"تم تجهيز ونشر {len(written_files)} ملفات توعية بنجاح على الفلاشة {target_drive}",
                    }))
                    logger.info(f"[SUCCESS] Deployment to {target_drive} completed successfully ({len(written_files)} files)!")

            else:
                logger.warning(f"Unknown action: {action}")
                await websocket.send(json.dumps({"type": "unknown_action", "action": action}))

    except websockets.exceptions.ConnectionClosed:
        logger.info("[-] Admin Dashboard disconnected")
    except Exception as exc:
        logger.error(f"[-] Error handling client: {exc}")
    finally:
        connected_clients.discard(websocket)


async def main():
    print_banner()
    monitor_task = asyncio.create_task(hardware_monitor_loop())
    try:
        async with websockets.serve(handle_client, AGENT_HOST, AGENT_PORT):
            logger.info(f"Agent is running on ws://{AGENT_HOST}:{AGENT_PORT} - Ready for React Dashboard.")
            await asyncio.Future()  # run forever
    except OSError as exc:
        if "10048" in str(exc) or "already in use" in str(exc).lower():
            logger.error(f"[!] Port {AGENT_PORT} is already in use by another process.")
            print(f"\n[!] ERROR: ws://{AGENT_HOST}:{AGENT_PORT} is already running!")
            print("    Another instance of the agent may already be active.")
            print("    Please close the existing instance or terminate port 8089.\n")
        else:
            logger.error(f"Failed to start WebSocket server: {exc}")
        sys.exit(1)
    finally:
        monitor_task.cancel()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[*] USB Companion Agent stopped cleanly by user.")
