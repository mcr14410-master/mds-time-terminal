# MDS Time Terminal

Stempelterminal für Mitarbeiter-Zeiterfassung. Läuft auf Raspberry Pi 4 mit Touchscreen und NFC-Reader.

## Hardware

- Raspberry Pi 4 (2GB)
- Raspberry Pi Touch Display 2 (7", 1280×720)
- PN532 NFC-Modul (I2C)
- KY-006 Passiv-Piezo Buzzer (PWM)
- Standard MIFARE/NTAG NFC-Karten

## Architektur

```
Terminal-Pi (lokal, offline-fähig)
├── Python Service (FastAPI)
│   ├── NFC-Reader (PN532, I2C)
│   ├── Buzzer (GPIO PWM)
│   ├── SQLite (Offline-Queue)
│   └── Sync → MDS Server
└── Chromium Kiosk (localhost:8080)
    └── HTML/JS Terminal-UI
```

## Installation

```bash
git clone https://github.com/DEIN-USER/mds-time-terminal.git
cd mds-time-terminal
chmod +x install.sh
./install.sh
```

Anschließend `config.yaml` anpassen.

## Entwicklung

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp config.example.yaml config.yaml
python run.py
```

Browser: http://localhost:8080

## Service-Steuerung

```bash
sudo systemctl start mds-terminal
sudo systemctl stop mds-terminal
sudo systemctl status mds-terminal
journalctl -u mds-terminal -f
```

## Pin-Belegung (BCM)

| Funktion | Pin | Beschreibung |
|----------|-----|--------------|
| I2C SDA  | GPIO 2 | PN532 Daten |
| I2C SCL  | GPIO 3 | PN532 Takt |
| Buzzer   | GPIO 18 | KY-006 PWM |

## Workflow

1. Mitarbeiter hält NFC-Karte an
2. Terminal erkennt User → zeigt Aktions-Buttons
3. Touch auf KOMMEN / GEHEN / PAUSE
4. Stempelung wird lokal gespeichert + an MDS Server gesynct
5. Bei Server-Ausfall: Offline-Queue, Sync bei Wiederverbindung
