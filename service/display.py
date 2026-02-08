"""
Display-Steuerung für das MDS Time Terminal.

Steuert das Backlight des Raspberry Pi Touchscreens:
- Wacht auf bei NFC-Scan oder Touch-Event
- Dimmt nach konfigurierbarem Idle-Timeout
- Schaltet nach längerem Idle komplett ab
- Auto-Detection des Backlight-Pfads

Stufen: awake (100%) -> dim (50%) -> off (0%)
"""

import os
import time
import logging

from service import config

logger = logging.getLogger(__name__)


class Display:
    STATE_AWAKE = "awake"
    STATE_DIM = "dim"
    STATE_OFF = "off"

    def __init__(self):
        self._backlight_path = None
        self._max_brightness = 255
        self._state = self.STATE_AWAKE
        self._last_activity = time.monotonic()
        self._enabled = False

        # Config
        self._brightness = config.get("display", "brightness") or 100
        self._dim_after = config.get("display", "dim_after_seconds") or 120
        self._dim_brightness = config.get("display", "dim_brightness") or 50
        self._off_after = config.get("display", "off_after_seconds") or 1800

    def init_hardware(self) -> bool:
        """Sucht den Backlight-Pfad und initialisiert die Steuerung."""
        backlight_base = "/sys/class/backlight"

        if not os.path.exists(backlight_base):
            logger.warning("Kein Backlight-Verzeichnis gefunden - Display-Steuerung deaktiviert")
            return False

        for entry in os.listdir(backlight_base):
            brightness_path = os.path.join(backlight_base, entry, "brightness")
            max_path = os.path.join(backlight_base, entry, "max_brightness")

            if os.path.exists(brightness_path):
                self._backlight_path = brightness_path

                if os.path.exists(max_path):
                    try:
                        with open(max_path, "r") as f:
                            self._max_brightness = int(f.read().strip())
                    except Exception:
                        pass

                if os.access(brightness_path, os.W_OK):
                    self._enabled = True
                    logger.info(
                        f"Display-Steuerung aktiv: {brightness_path} "
                        f"(max={self._max_brightness}, dim={self._dim_after}s/{self._dim_brightness}%, "
                        f"off={self._off_after}s)"
                    )
                else:
                    logger.warning(
                        f"Backlight gefunden ({brightness_path}) aber keine Schreibrechte. "
                        f"Tipp: sudo chmod a+w {brightness_path}"
                    )
                    return False

                self.wake()
                return True

        logger.warning("Kein steuerbares Backlight gefunden - Display-Steuerung deaktiviert")
        return False

    @property
    def state(self) -> str:
        return self._state

    @property
    def idle_seconds(self) -> float:
        return time.monotonic() - self._last_activity

    def wake(self):
        """Display einschalten und Idle-Timer zuruecksetzen."""
        self._last_activity = time.monotonic()

        if self._state == self.STATE_AWAKE:
            return

        self._set_brightness_pct(self._brightness)
        self._state = self.STATE_AWAKE
        logger.debug("Display: awake")

    def check_idle(self):
        """Prueft Idle-Zeit und wechselt ggf. den Zustand.
        awake -> dim -> off
        """
        if not self._enabled:
            return

        idle = self.idle_seconds

        if self._state == self.STATE_AWAKE and idle >= self._dim_after:
            self._set_brightness_pct(self._dim_brightness)
            self._state = self.STATE_DIM
            logger.debug("Display: dim")

        elif self._state == self.STATE_DIM and idle >= self._off_after:
            self._set_brightness_pct(0)
            self._state = self.STATE_OFF
            logger.debug("Display: off")

    def _set_brightness_pct(self, pct: int):
        """Setzt Brightness als Prozentwert (0-100)."""
        if not self._enabled or not self._backlight_path:
            return

        pct = max(0, min(100, pct))
        value = int(self._max_brightness * pct / 100)

        try:
            with open(self._backlight_path, "w") as f:
                f.write(str(value))
        except Exception as e:
            logger.error(f"Backlight setzen fehlgeschlagen: {e}")

    def cleanup(self):
        """Display beim Beenden einschalten."""
        if self._enabled:
            self._set_brightness_pct(self._brightness)
            self._state = self.STATE_AWAKE
