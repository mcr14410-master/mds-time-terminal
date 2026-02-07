"""
Sync-Service - Kommunikation mit dem MDS Server.

Aufgaben:
1. Stempelungen aus Offline-Queue an Server senden
2. User-Liste vom Server synchronisieren
3. Server-Erreichbarkeit prüfen
4. User-Info vom Server abrufen (für Info-Screen)
"""

import asyncio
import logging
import httpx
from datetime import datetime, timezone
from service import config, db

logger = logging.getLogger(__name__)


class SyncService:
    def __init__(self):
        cfg = config.get("server")
        self.base_url = cfg["url"].rstrip("/")
        self.api_path = cfg["api_path"]
        self.timeout = cfg.get("timeout", 5)
        self.sync_interval = cfg.get("sync_interval", 30)
        self.user_sync_interval = cfg.get("user_sync_interval", 300)

        self.terminal_id = config.get("terminal", "id")
        self.api_key = config.get("terminal", "api_key")

        self._running = False
        self._server_online = False
        self._last_user_sync = 0

    @property
    def server_online(self) -> bool:
        return self._server_online

    @property
    def api_url(self) -> str:
        return f"{self.base_url}/api/terminal"

    @property
    def _headers(self) -> dict:
        return {"X-Terminal-Key": self.api_key or ""}

    # ============================================
    # Server Health Check
    # ============================================

    async def check_server(self) -> bool:
        """Prüft ob MDS Server erreichbar ist."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(f"{self.base_url}/api/health")
                self._server_online = resp.status_code == 200
        except Exception:
            self._server_online = False

        return self._server_online

    # ============================================
    # Stempelungen synchronisieren
    # ============================================

    async def sync_stamps(self) -> dict:
        """
        Sendet alle ungesyncten Stempelungen an den Server.
        
        Returns:
            {"synced": int, "failed": int, "pending": int}
        """
        unsynced = db.get_unsynced_stamps()
        if not unsynced:
            return {"synced": 0, "failed": 0, "pending": 0}

        synced = 0
        failed = 0

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for stamp in unsynced:
                try:
                    resp = await client.post(
                        f"{self.api_url}/stamp",
                        json={
                            "user_id": stamp["user_id"],
                            "entry_type": stamp["entry_type"],
                            "timestamp": stamp["timestamp"],
                        },
                        headers=self._headers,
                    )

                    if resp.status_code in (200, 201):
                        data = resp.json()
                        server_id = data.get("id")
                        db.mark_stamp_synced(stamp["id"], server_id)
                        synced += 1
                    else:
                        error_msg = resp.text[:200]
                        db.mark_stamp_failed(stamp["id"], f"HTTP {resp.status_code}: {error_msg}")
                        failed += 1
                        logger.warning(f"Sync fehlgeschlagen für Stamp {stamp['id']}: {resp.status_code}")

                except Exception as e:
                    db.mark_stamp_failed(stamp["id"], str(e)[:200])
                    failed += 1
                    logger.warning(f"Sync-Fehler für Stamp {stamp['id']}: {e}")

        pending = db.get_pending_count()

        if synced > 0:
            db.log_sync_event("stamps_synced", f"{synced} Stempelungen synchronisiert")
            logger.info(f"Stamps synchronisiert: {synced} OK, {failed} Fehler, {pending} ausstehend")

        return {"synced": synced, "failed": failed, "pending": pending}

    # ============================================
    # User-Liste synchronisieren
    # ============================================

    async def sync_users(self) -> bool:
        """
        Lädt User-Liste vom MDS Server und aktualisiert lokalen Cache.
        Holt nur User mit time_tracking_enabled.
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(
                    f"{self.api_url}/users",
                    headers=self._headers,
                )

                if resp.status_code != 200:
                    logger.warning(f"User-Sync fehlgeschlagen: HTTP {resp.status_code}")
                    return False

                users = resp.json()

                # Nur relevante Felder extrahieren
                user_list = []
                for u in users:
                    user_list.append({
                        "id": u["id"],
                        "first_name": u.get("first_name", ""),
                        "last_name": u.get("last_name", ""),
                        "rfid_chip_id": u.get("rfid_chip_id"),
                        "pin_code": u.get("pin_code"),
                        "time_tracking_enabled": u.get("time_tracking_enabled", False),
                        "time_model_name": u.get("time_model_name"),
                    })

                db.sync_users(user_list)
                self._last_user_sync = asyncio.get_event_loop().time()
                db.log_sync_event("users_synced", f"{len(user_list)} User synchronisiert")
                return True

        except Exception as e:
            logger.warning(f"User-Sync Fehler: {e}")
            db.log_sync_event("users_sync_failed", str(e), success=False)
            return False

    # ============================================
    # User-Info vom Server (für Info-Screen)
    # ============================================

    async def get_user_info(self, user_id: int) -> dict | None:
        """
        Holt detaillierte User-Info vom Server (Zeitkonto, Urlaub etc.).
        """
        if not self._server_online:
            return None

        try:
            resp = await self._client.get(
                f"{self._base_url}/api/terminal/user-info/{user_id}",
                headers=self._headers,
            )
            if resp.status_code == 200:
                return resp.json()
            return None
        except Exception as e:
            logger.warning(f"get_user_info fehlgeschlagen: {e}")
            return None

    # ============================================
    # Background Sync Loop
    # ============================================

    async def start_sync_loop(self):
        """Hintergrund-Sync: Stempelungen + User-Liste regelmäßig synchronisieren."""
        self._running = True
        logger.info(f"Sync-Loop gestartet (Stamps: {self.sync_interval}s, Users: {self.user_sync_interval}s)")

        # Initiale User-Sync
        await self.check_server()
        if self._server_online:
            await self.sync_users()

        while self._running:
            try:
                # Server-Status prüfen
                was_online = self._server_online
                await self.check_server()

                if self._server_online and not was_online:
                    logger.info("Server wieder erreichbar - starte Sync")
                    db.log_sync_event("server_online", "Server wieder erreichbar")
                elif not self._server_online and was_online:
                    logger.warning("Server nicht erreichbar")
                    db.log_sync_event("server_offline", "Server nicht erreichbar", success=False)

                if self._server_online:
                    # Stempelungen synchronisieren
                    await self.sync_stamps()

                    # User-Liste periodisch aktualisieren
                    now = asyncio.get_event_loop().time()
                    if (now - self._last_user_sync) > self.user_sync_interval:
                        await self.sync_users()

            except Exception as e:
                logger.error(f"Sync-Loop Fehler: {e}")

            await asyncio.sleep(self.sync_interval)

    def stop(self):
        """Stoppt den Sync-Loop."""
        self._running = False
        logger.info("Sync-Loop gestoppt")
