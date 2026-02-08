"""
Konfiguration laden und Defaults bereitstellen.
"""

import os
import yaml
import logging

logger = logging.getLogger(__name__)

DEFAULT_CONFIG = {
    "server": {
        "url": "http://localhost:3000",
        "api_path": "/api/time-tracking",
        "sync_interval": 30,
        "user_sync_interval": 300,
        "timeout": 5,
    },
    "terminal": {
        "id": 1,
        "name": "Zeiterfassung",
        "location": "",
    },
    "nfc": {
        "enabled": True,
        "type": "pn532",
        "bus": "i2c",
        "i2c_bus": 1,
        "poll_interval": 0.3,
        "debounce": 2.0,
    },
    "buzzer": {
        "enabled": True,
        "gpio_pin": 18,
        "volume": 0.5,
    },
    "web": {
        "host": "0.0.0.0",
        "port": 8080,
    },
    "display": {
        "auto_reset_seconds": 10,
        "info_timeout_seconds": 30,
        "brightness": 100,
        "dim_after_seconds": 120,
        "dim_brightness": 50,
        "off_after_seconds": 1800,
    },
    "logging": {
        "level": "INFO",
        "file": "terminal.log",
        "max_size_mb": 10,
    },
}


def deep_merge(base: dict, override: dict) -> dict:
    """Verschmilzt override in base (rekursiv)."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(path: str = None) -> dict:
    """Lädt config.yaml und merged mit Defaults."""
    if path is None:
        # config.yaml im Projektverzeichnis suchen
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(base_dir, "config.yaml")

    config = DEFAULT_CONFIG.copy()

    if os.path.exists(path):
        with open(path, "r") as f:
            user_config = yaml.safe_load(f) or {}
        config = deep_merge(DEFAULT_CONFIG, user_config)
        logger.info(f"Konfiguration geladen: {path}")
    else:
        logger.warning(f"Keine config.yaml gefunden ({path}), verwende Defaults")

    return config


# Globale Config-Instanz
_config = None


def get_config() -> dict:
    global _config
    if _config is None:
        _config = load_config()
    return _config


def get(section: str, key: str = None):
    """Shortcut: get('server', 'url') oder get('server') für ganze Section."""
    cfg = get_config()
    if section not in cfg:
        return None
    if key is None:
        return cfg[section]
    return cfg[section].get(key)
