"""
NFC Reader - PN532 über I2C.

Liest NFC-Tag UIDs und gibt sie als Events weiter.
Enthält Mock-Modus für Entwicklung ohne Hardware.
"""

import asyncio
import logging
import time
from service import config

logger = logging.getLogger(__name__)

# Hardware-Abhängigkeiten optional laden
_hw_available = False
try:
    import board
    import busio
    from adafruit_pn532.i2c import PN532_I2C
    _hw_available = True
except (ImportError, NotImplementedError):
    logger.warning("NFC Hardware-Bibliotheken nicht verfügbar - Mock-Modus aktiv")


class NFCReader:
    """
    PN532 NFC Reader über I2C.
    
    Liest Tag-UIDs und ruft Callback auf.
    Debounce verhindert Mehrfach-Scans der gleichen Karte.
    """

    def __init__(self, on_tag_read=None):
        """
        Args:
            on_tag_read: async Callback(uid: str) - wird bei Tag-Erkennung aufgerufen
        """
        cfg = config.get("nfc")
        self.enabled = cfg.get("enabled", True)
        self.poll_interval = cfg.get("poll_interval", 0.3)
        self.debounce_time = cfg.get("debounce", 2.0)
        self.on_tag_read = on_tag_read

        self._pn532 = None
        self._running = False
        self._last_uid = None
        self._last_read_time = 0

    def init_hardware(self) -> bool:
        """Initialisiert PN532. Gibt True zurück bei Erfolg."""
        if not self.enabled:
            logger.info("NFC Reader deaktiviert (config)")
            return False

        if not _hw_available:
            logger.warning("NFC Hardware nicht verfügbar - Mock-Modus")
            return False

        try:
            cfg = config.get("nfc")
            i2c_bus_num = cfg.get("i2c_bus", 1)

            i2c = busio.I2C(board.SCL, board.SDA)
            self._pn532 = PN532_I2C(i2c, debug=False)

            ic, ver, rev, support = self._pn532.firmware_version
            logger.info(f"PN532 gefunden: Firmware {ver}.{rev}")

            # SAM konfigurieren (Standard-Modus)
            self._pn532.SAM_configuration()

            return True

        except Exception as e:
            logger.error(f"PN532 Initialisierung fehlgeschlagen: {e}")
            self._pn532 = None
            return False

    async def start_polling(self):
        """Startet NFC-Polling Loop."""
        self._running = True
        logger.info(f"NFC Polling gestartet (Intervall: {self.poll_interval}s, Debounce: {self.debounce_time}s)")

        while self._running:
            try:
                uid = self._read_tag()
                if uid:
                    await self._handle_tag(uid)
            except Exception as e:
                logger.error(f"NFC Poll-Fehler: {e}")

            await asyncio.sleep(self.poll_interval)

    def stop(self):
        """Stoppt Polling."""
        self._running = False
        logger.info("NFC Polling gestoppt")

    def _read_tag(self) -> str | None:
        """
        Liest NFC-Tag. Gibt UID als Hex-String zurück oder None.
        """
        if self._pn532 is None:
            return None

        try:
            uid_bytes = self._pn532.read_passive_target(timeout=0.2)
            if uid_bytes is None:
                return None

            uid = uid_bytes.hex().upper()
            return uid

        except Exception as e:
            # I2C-Fehler passieren gelegentlich, nicht jedes Mal loggen
            logger.debug(f"NFC Lesefehler: {e}")
            return None

    async def _handle_tag(self, uid: str):
        """Verarbeitet gelesene UID mit Debounce."""
        now = time.time()

        # Debounce: gleiche Karte innerhalb debounce_time ignorieren
        if uid == self._last_uid and (now - self._last_read_time) < self.debounce_time:
            return

        self._last_uid = uid
        self._last_read_time = now

        logger.info(f"NFC Tag gelesen: {uid}")

        if self.on_tag_read:
            await self.on_tag_read(uid)

    # ============================================
    # Mock-Funktionen für Tests ohne Hardware
    # ============================================

    async def simulate_tag(self, uid: str):
        """Simuliert einen Tag-Scan (für Entwicklung/Tests)."""
        logger.info(f"Simulierter NFC Scan: {uid}")
        if self.on_tag_read:
            await self.on_tag_read(uid)

    @property
    def is_hardware_ready(self) -> bool:
        return self._pn532 is not None
