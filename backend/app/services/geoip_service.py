"""GeoIP & ISP lookup service with YemenNet / Sanaa precision and GPS override.

Provides accurate country, city, ISP and coordinates.  Maintains an in-memory
cache to eliminate redundant external HTTP queries.
"""
from __future__ import annotations

import ipaddress
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.logging_config import get_logger

logger = get_logger(__name__)

_CACHE: dict[str, tuple[float, GeoLocation]] = {}
_CACHE_TTL_SECONDS = 3600 * 6  # 6 hours cache


@dataclass
class GeoLocation:
    country: str | None = None
    city: str | None = None
    isp: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    is_gps: bool = False

    @property
    def display_location(self) -> str:
        parts: list[str] = []
        if self.city:
            parts.append(self.city)
        if self.country and self.country != self.city:
            parts.append(self.country)
        loc = ", ".join(parts) or "Unknown Location"
        if self.isp:
            loc += f" (ISP: {self.isp})"
        if self.is_gps:
            loc += " 📍 GPS"
        return loc


def is_private_or_loopback(ip: str) -> bool:
    """Return True if the IP is private, link-local, or loopback."""
    if not ip or ip in ("unknown", "127.0.0.1", "localhost", "::1"):
        return True
    try:
        obj = ipaddress.ip_address(ip)
        return obj.is_private or obj.is_loopback or obj.is_link_local
    except ValueError:
        return True


async def lookup_ip_geolocation(
    ip_address: str | None,
    client_gps: dict[str, Any] | None = None,
) -> GeoLocation:
    """Resolve geographic location and ISP for an IP address.

    Args:
        ip_address: Client public IP string.
        client_gps: Optional GPS coordinates dictionary (e.g. {"latitude": 15.35, "longitude": 44.20}).

    Returns:
        A populated GeoLocation instance.
    """
    clean_ip = (ip_address or "").strip()

    # Check GPS override first
    gps_lat: float | None = None
    gps_lon: float | None = None
    has_gps = False
    if client_gps and isinstance(client_gps, dict):
        try:
            if client_gps.get("latitude") is not None and client_gps.get("longitude") is not None:
                gps_lat = float(client_gps["latitude"])
                gps_lon = float(client_gps["longitude"])
                has_gps = True
        except (ValueError, TypeError):
            pass

    # Private or local development IP
    if is_private_or_loopback(clean_ip):
        res = GeoLocation(
            country="Yemen",
            city="Sanaa",
            isp="YemenNet (Local Dev)",
            latitude=gps_lat if has_gps else 15.3694,
            longitude=gps_lon if has_gps else 44.1910,
            is_gps=has_gps,
        )
        return res

    # Check cache
    now = time.time()
    if clean_ip in _CACHE:
        cached_time, cached_geo = _CACHE[clean_ip]
        if now - cached_time < _CACHE_TTL_SECONDS:
            if has_gps:
                return GeoLocation(
                    country=cached_geo.country,
                    city=cached_geo.city,
                    isp=cached_geo.isp,
                    latitude=gps_lat,
                    longitude=gps_lon,
                    is_gps=True,
                )
            return cached_geo

    # Query external GeoIP service (ip-api.com)
    geo = GeoLocation()
    try:
        url = f"http://ip-api.com/json/{clean_ip}?fields=status,message,country,city,regionName,isp,org,as,lat,lon"
        async with httpx.AsyncClient(timeout=2.5) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "success":
                    country = data.get("country") or "Unknown"
                    city = data.get("city") or data.get("regionName") or "Unknown"
                    isp = data.get("isp") or data.get("org") or data.get("as") or "Unknown"
                    lat = data.get("lat")
                    lon = data.get("lon")

                    # YemenNet / Sanaa Precision Normalization:
                    # Generic GeoIP databases frequently mislocate YemenNet (AS30873) IP ranges
                    # as Aden because of the submarine cable landing, despite the routing gateway
                    # and core NOC residing in Sana'a.
                    isp_lower = isp.lower()
                    if (
                        country == "Yemen"
                        or "yemennet" in isp_lower
                        or "telecom" in isp_lower
                        or "as30873" in isp_lower
                        or "teleyemen" in isp_lower
                    ):
                        country = "Yemen"
                        # If city is Aden or missing on a YemenNet block, normalize to Sanaa
                        if city in ("Aden", "Unknown", None) or "yemennet" in isp_lower:
                            city = "Sanaa"
                        if "yemen" in isp_lower or "ptc" in isp_lower:
                            isp = "YemenNet"

                    geo = GeoLocation(
                        country=country,
                        city=city,
                        isp=isp,
                        latitude=gps_lat if has_gps else lat,
                        longitude=gps_lon if has_gps else lon,
                        is_gps=has_gps,
                    )
                    _CACHE[clean_ip] = (now, geo)
                    return geo
    except Exception as exc:
        logger.warning("geoip_lookup_failed", ip=clean_ip, error=str(exc))

    # Fallback when lookup times out or fails
    fallback = GeoLocation(
        country="Yemen",
        city="Sanaa",
        isp="YemenNet",
        latitude=gps_lat if has_gps else 15.3694,
        longitude=gps_lon if has_gps else 44.1910,
        is_gps=has_gps,
    )
    _CACHE[clean_ip] = (now, fallback)
    return fallback
