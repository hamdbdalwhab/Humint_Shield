"""Provider webhook routers.

* ``whatsapp`` — WA-AKG read receipts, replies and session state.  SMS delivery
  is owned by the TextBee gateway, which reports batches through its own API
  rather than signed callbacks.
"""
from __future__ import annotations

from app.api.v1.webhooks.whatsapp import router as whatsapp_router

__all__ = ["whatsapp_router"]
