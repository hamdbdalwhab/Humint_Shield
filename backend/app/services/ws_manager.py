"""Real-time WebSocket connection manager and telemetry broadcaster."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session_factory
from app.logging_config import get_logger
from app.models import EmailCampaign, EmailTracking, HumanAsset, QRScan
from app.services.device_detector import detect_device_model
from app.services.geoip_service import lookup_ip_geolocation

logger = get_logger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class CampaignWebSocketManager:
    """Manages active WebSockets per campaign and dispatches live telemetry."""

    def __init__(self) -> None:
        # campaign_id (str) -> set[WebSocket]
        self._rooms: dict[str, set[WebSocket]] = {}

    async def connect(self, campaign_id: str, websocket: WebSocket) -> None:
        """Accept and register a new client connection in a campaign room."""
        await websocket.accept()
        key = str(campaign_id).lower()
        if key not in self._rooms:
            self._rooms[key] = set()
        self._rooms[key].add(websocket)
        logger.info("ws_client_connected", campaign_id=key, total_clients=len(self._rooms[key]))

    def disconnect(self, campaign_id: str, websocket: WebSocket) -> None:
        """Remove a closed connection."""
        key = str(campaign_id).lower()
        if key in self._rooms:
            self._rooms[key].discard(websocket)
            if not self._rooms[key]:
                del self._rooms[key]
        logger.info("ws_client_disconnected", campaign_id=key)

    async def broadcast(self, campaign_id: str, message: dict[str, Any]) -> None:
        """Broadcast a JSON payload to every listener connected to this campaign."""
        key = str(campaign_id).lower()
        room = self._rooms.get(key)
        if not room:
            return

        dead_sockets: list[WebSocket] = []
        for ws in list(room):
            try:
                await ws.send_json(message)
            except Exception:
                dead_sockets.append(ws)

        for dead in dead_sockets:
            room.discard(dead)

    async def handle_telemetry_event(
        self,
        campaign_id: str,
        data: dict[str, Any],
        client_ip: str | None,
        user_agent: str | None,
    ) -> dict[str, Any] | None:
        """Process an incoming telemetry event from the landing page.

        Updates database models, enriches with deep device detection and GeoIP,
        and broadcasts real-time card updates to all admin dashboards.
        """
        event_name = data.get("event") or "page_viewed"
        tracking_uuid_str = data.get("tracking_uuid") or data.get("tid")
        fingerprint = data.get("fingerprint") or data.get("fingerprint_data") or {}
        gps_data = data.get("gps") or data.get("geolocation") or {}
        now = _now()
        time_str = now.strftime("%H:%M:%S")

        session_factory = get_session_factory()
        async with session_factory() as db:
            try:
                cid = uuid.UUID(str(campaign_id))
            except (ValueError, TypeError):
                return None

            campaign = await db.get(EmailCampaign, cid)
            if campaign is None:
                return None

            # Resolve device model and GeoIP
            model_name = detect_device_model(user_agent, fingerprint_data=fingerprint)
            geo = await lookup_ip_geolocation(client_ip, client_gps=gps_data)

            scan_row: QRScan | None = None
            tracking_row: EmailTracking | None = None

            if tracking_uuid_str:
                try:
                    t_uid = uuid.UUID(str(tracking_uuid_str))
                    tracking_row = (
                        await db.execute(
                            select(EmailTracking).where(EmailTracking.tracking_uuid == t_uid)
                        )
                    ).scalars().first()
                    if tracking_row:
                        scan_row = (
                            await db.execute(
                                select(QRScan).where(QRScan.tracking_id == tracking_row.id)
                            )
                        ).scalars().first()
                except (ValueError, TypeError):
                    pass

            if scan_row is None:
                # Find the latest scan row for this campaign and IP
                scan_row = (
                    await db.execute(
                        select(QRScan)
                        .where(QRScan.campaign_id == cid)
                        .order_by(QRScan.occurred_at.desc())
                        .limit(1)
                    )
                ).scalars().first()

            if scan_row is None:
                scan_row = QRScan(
                    organization_id=campaign.organization_id,
                    campaign_id=cid,
                    tracking_id=tracking_row.id if tracking_row else None,
                    ip_address=client_ip,
                    user_agent=user_agent,
                    occurred_at=now,
                    event_type="qr_scanned",
                )
                db.add(scan_row)

            # Update device and location metadata
            scan_row.device_model = model_name
            scan_row.country = geo.country
            scan_row.city = geo.city
            scan_row.isp = geo.isp
            scan_row.latitude = geo.latitude
            scan_row.longitude = geo.longitude
            scan_row.ip_address = client_ip or scan_row.ip_address
            scan_row.user_agent = user_agent or scan_row.user_agent
            if fingerprint:
                merged_fp = dict(scan_row.fingerprint_data or {})
                merged_fp.update(fingerprint)
                scan_row.fingerprint_data = merged_fp

            # Update timeline events
            events = list(scan_row.real_time_events or [])
            if not events:
                # Always add qr_scanned as initial event if missing
                events.append({
                    "event": "qr_scanned",
                    "label": "مسح رمز الاستجابة السريعة (QR)",
                    "timestamp": now.isoformat(),
                    "time_str": time_str,
                })

            if event_name == "page_viewed":
                if not any(e.get("event") == "page_viewed" for e in events):
                    events.append({
                        "event": "page_viewed",
                        "label": "فتح صفحة الهبوط واستخراج بصمة الجهاز",
                        "timestamp": now.isoformat(),
                        "time_str": time_str,
                    })
            elif event_name == "field_focused":
                field = data.get("field") or "form_input"
                field_label = "البريد الإلكتروني" if field == "email" else ("كلمة المرور" if field == "password" else field)
                events.append({
                    "event": "field_focused",
                    "field": field,
                    "label": f"بدء التفاعل مع حقل ({field_label})",
                    "timestamp": now.isoformat(),
                    "time_str": time_str,
                })
            elif event_name == "form_submitted":
                scan_row.event_type = "qr_credential_submitted"
                events.append({
                    "event": "form_submitted",
                    "label": "إرسال البيانات المدخلة واعتماد الهوية",
                    "timestamp": now.isoformat(),
                    "time_str": time_str,
                })

            scan_row.real_time_events = events

            # Compute duration on page
            time_on_page = 0
            if len(events) >= 2:
                try:
                    t0 = datetime.fromisoformat(events[0]["timestamp"])
                    t_last = datetime.fromisoformat(events[-1]["timestamp"])
                    time_on_page = max(0, int((t_last - t0).total_seconds()))
                except Exception:
                    pass

            await db.commit()
            await db.refresh(scan_row)

            # Resolve matched employee name if assigned
            emp_name = None
            if scan_row.employee_id:
                emp = await db.get(HumanAsset, scan_row.employee_id)
                emp_name = emp.full_name if emp else None

            # Prepare broadcast payload
            card_payload = {
                "type": "scan_update",
                "scan_id": str(scan_row.id),
                "campaign_id": str(campaign.id),
                "tracking_id": str(scan_row.tracking_id) if scan_row.tracking_id else None,
                "tracking_uuid": str(tracking_row.tracking_uuid) if tracking_row else None,
                "event_type": scan_row.event_type,
                "occurred_at": scan_row.occurred_at.isoformat(),
                "ip_address": scan_row.ip_address,
                "user_agent": scan_row.user_agent,
                "device_model": scan_row.device_model or "Unknown Device",
                "country": scan_row.country,
                "city": scan_row.city,
                "isp": scan_row.isp,
                "location_display": geo.display_location,
                "latitude": scan_row.latitude,
                "longitude": scan_row.longitude,
                "employee_id": str(scan_row.employee_id) if scan_row.employee_id else None,
                "employee_name": emp_name,
                "username_entered": scan_row.username,
                "email_entered": scan_row.email,
                "password_submitted": scan_row.password_submitted,
                "identity_resolution": scan_row.identity_resolution,
                "fingerprint": scan_row.fingerprint_data or {},
                "fingerprint_hash": (scan_row.fingerprint_data or {}).get("fingerprint_hash"),
                "device_hash": (scan_row.fingerprint_data or {}).get("device_hash"),
                "real_time_events": scan_row.real_time_events or [],
                "time_on_page_seconds": time_on_page,
            }

            await self.broadcast(str(campaign.id), card_payload)
            return card_payload


ws_manager = CampaignWebSocketManager()
