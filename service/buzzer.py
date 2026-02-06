"""
Buzzer - KY-006 Passiv-Piezo über PWM.

Verschiedene Signaltöne für Feedback:
- success: Kurzer aufsteigender Doppelton
- error: Langer tiefer Ton
- scan: Kurzer Bestätigungston
- info: Sanfter mittlerer Ton
"""

import asyncio
import logging
from service import config

logger = logging.getLogger(__name__)

# Hardware optional laden
_hw_available = False
try:
    import RPi.GPIO as GPIO
    _hw_available = True
except (ImportError, RuntimeError):
    logger.warning("GPIO nicht verfügbar - Buzzer Mock-Modus")


class Buzzer:
    """PWM-Buzzer Steuerung für KY-006."""

    def __init__(self):
        cfg = config.get("buzzer")
        self.enabled = cfg.get("enabled", True)
        self.pin = cfg.get("gpio_pin", 18)
        self.volume = cfg.get("volume", 0.5)
        self._pwm = None

    def init_hardware(self) -> bool:
        """Initialisiert GPIO/PWM."""
        if not self.enabled:
            logger.info("Buzzer deaktiviert (config)")
            return False

        if not _hw_available:
            logger.warning("GPIO nicht verfügbar - Buzzer Mock-Modus")
            return False

        try:
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(self.pin, GPIO.OUT)
            self._pwm = GPIO.PWM(self.pin, 440)  # Start-Frequenz
            logger.info(f"Buzzer initialisiert auf GPIO {self.pin}")
            return True
        except Exception as e:
            logger.error(f"Buzzer Initialisierung fehlgeschlagen: {e}")
            return False

    def _tone(self, frequency: int, duration: float):
        """Spielt einen Ton (blockierend)."""
        if self._pwm is None:
            return
        try:
            self._pwm.ChangeFrequency(frequency)
            self._pwm.start(self.volume * 100)  # Duty Cycle als Lautstärke
            import time
            time.sleep(duration)
            self._pwm.stop()
        except Exception as e:
            logger.error(f"Buzzer Ton-Fehler: {e}")

    async def _tone_async(self, frequency: int, duration: float):
        """Spielt einen Ton (nicht-blockierend)."""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._tone, frequency, duration)

    async def success(self):
        """Erfolg: Aufsteigender Doppelton."""
        if not self.enabled:
            return
        logger.debug("Buzzer: success")
        if self._pwm:
            await self._tone_async(880, 0.1)
            await asyncio.sleep(0.05)
            await self._tone_async(1175, 0.15)
        else:
            logger.debug("Buzzer (mock): ♪ success")

    async def error(self):
        """Fehler: Tiefer langer Ton."""
        if not self.enabled:
            return
        logger.debug("Buzzer: error")
        if self._pwm:
            await self._tone_async(220, 0.3)
            await asyncio.sleep(0.05)
            await self._tone_async(220, 0.3)
        else:
            logger.debug("Buzzer (mock): ♪ error")

    async def scan(self):
        """Tag erkannt: Kurzer Bestätigungston."""
        if not self.enabled:
            return
        logger.debug("Buzzer: scan")
        if self._pwm:
            await self._tone_async(1320, 0.08)
        else:
            logger.debug("Buzzer (mock): ♪ scan")

    async def info(self):
        """Info: Sanfter mittlerer Ton."""
        if not self.enabled:
            return
        logger.debug("Buzzer: info")
        if self._pwm:
            await self._tone_async(660, 0.12)
        else:
            logger.debug("Buzzer (mock): ♪ info")

    def cleanup(self):
        """GPIO aufräumen."""
        if self._pwm:
            self._pwm.stop()
        if _hw_available:
            try:
                GPIO.cleanup(self.pin)
            except Exception:
                pass
        logger.info("Buzzer cleanup")
