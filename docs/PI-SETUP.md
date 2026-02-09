# MDS Time Terminal - Raspberry Pi Einrichtung

Anleitung zur Einrichtung eines Raspberry Pi 4 als Stempelterminal mit Touchscreen.

## Hardware

- Raspberry Pi 4 (2GB RAM)
- Raspberry Pi Touch Display 2 (7", 1280×720)
- PN532 NFC-Modul (I2C) — optional, für NFC-Stempelung
- KY-006 Passiv-Piezo Buzzer — optional, für akustisches Feedback

## 1. Betriebssystem

**Raspberry Pi OS Lite (64-bit, Bookworm)** — ohne Desktop.

Einstellungen im Raspberry Pi Imager:
- Hostname: `mds-terminal` (oder nach Wahl)
- SSH aktivieren
- WLAN konfigurieren (falls kein LAN)
- Benutzer: z.B. `rpi02` mit Passwort
- Locale: `de_DE.UTF-8`
- Timezone: `Europe/Berlin`

## 2. System aktualisieren + Pakete installieren

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y git i2c-tools python3-venv python3-pip python3-dev libgpiod-dev
```

## 3. I2C aktivieren (für NFC-Reader)

```bash
sudo raspi-config nonint do_i2c 0
```

## 4. Kiosk-Umgebung installieren

```bash
sudo apt install -y xserver-xorg xinit x11-xserver-utils unclutter chromium-browser
```

## 5. Neustart

```bash
sudo reboot
```

## 6. I2C prüfen

```bash
i2cdetect -y 1
```

Sollte eine leere Tabelle zeigen (oder NFC-Adresse 0x24 wenn PN532 angeschlossen).

## 7. Projekt klonen + installieren

```bash
cd /home/<USER>
git clone https://github.com/<DEIN-USERNAME>/mds-time-terminal.git
cd mds-time-terminal
chmod +x install.sh
./install.sh
```

## 8. Konfiguration anpassen

```bash
nano config.yaml
```

Mindestens setzen:
```yaml
server:
  url: "http://<MDS-SERVER-IP>:3000"
 # oder
  url: "http://<MDS-SERVER-IP>:81"   #je nach port

terminal:
  api_key: "<API-KEY-VOM-MDS-SERVER>"
```

## 9. Display-Rotation (Landscape)

### Konsole drehen

```bash
sudo nano /boot/firmware/cmdline.txt
```

Am Ende der Zeile (gleiche Zeile!) anfügen:
```
video=DSI-1:720x1280@60,rotate=90
```

### Touch-Eingabe drehen

```bash
sudo nano /etc/udev/rules.d/99-touch-rotation.rules
```

Inhalt:
```
ENV{ID_INPUT_TOUCHSCREEN}=="1", ENV{LIBINPUT_CALIBRATION_MATRIX}="0 -1 1 1 0 0"
```

> Hinweis: Die Matrix hängt von der Einbaurichtung ab.
> Falls Touch spiegelverkehrt: `"0 1 0 -1 0 1"` probieren.

## 10. Systemd Services einrichten

### Terminal-Service

```bash
sudo nano /etc/systemd/system/mds-terminal.service
```

```ini
[Unit]
Description=MDS Time Terminal
After=network.target
Wants=network.target

[Service]
Type=simple
User=<USER>
WorkingDirectory=/home/<USER>/mds-time-terminal
ExecStart=/home/<USER>/mds-time-terminal/.venv/bin/python -m service.main
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

# GPIO/I2C Zugriff
SupplementaryGroups=gpio i2c spi

[Install]
WantedBy=multi-user.target
```

### Kiosk-Service

```bash
sudo nano /etc/systemd/system/kiosk.service
```

```ini
[Unit]
Description=Chromium Kiosk
After=mds-terminal.service
Wants=mds-terminal.service

[Service]
Type=simple
User=<USER>
PAMName=login
TTYPath=/dev/tty1
StandardInput=tty
StandardOutput=journal
StandardError=journal
ExecStartPre=/bin/sleep 3
ExecStart=/usr/bin/xinit /home/<USER>/kiosk.sh -- :0 -nocursor
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### Kiosk-Script (X11 + Display-Rotation)

```bash
nano /home/<USER>/kiosk.sh
```

```bash
#!/bin/sh
export DISPLAY=":0"

# Display drehen (X11)
xrandr --output DSI-1 --rotate right 2>/dev/null

# Mauszeiger verstecken
unclutter -idle 0.5 -root &

# Warten auf Terminal-Service
sleep 3

# Chromium Kiosk (Endlos-Loop bei Crash)
while :; do
  chromium-browser \
    --kiosk \
    --start-fullscreen \
    --window-size=1280,720 \
    --window-position=0,0 \
    --app="http://localhost:8080" \
    --noerrdialogs \
    --disable-infobars \
    --no-first-run \
    --disable-session-crashed-bubble \
    --disable-features=TranslateUI \
    --disable-translate \
    --disable-notifications \
    --lang=de \
    --incognito
  sleep 2
done
```

```bash
chmod +x /home/<USER>/kiosk.sh
```

> Wichtig: Die Datei muss Unix-Zeilenumbrüche (LF) haben, nicht Windows (CRLF).
> Prüfen mit `file kiosk.sh`, fixen mit `sed -i 's/\r$//' kiosk.sh`.

## 11. User-Berechtigungen

```bash
sudo usermod -aG video,render,input,tty <USER>
```

## 12. Getty auf tty1 deaktivieren

Getty blockiert den Kiosk-Zugriff auf tty1:

```bash
sudo systemctl disable getty@tty1
sudo systemctl stop getty@tty1
```

## 13. Services aktivieren + starten

```bash
sudo systemctl daemon-reload
sudo systemctl enable mds-terminal
sudo systemctl enable kiosk
sudo reboot
```

## 14. Prüfen

Nach dem Reboot:

```bash
# Terminal-Service Status
sudo systemctl status mds-terminal

# Kiosk Status
sudo systemctl status kiosk

# Terminal-Service Logs
journalctl -u mds-terminal -f

# Kiosk Logs
journalctl -u kiosk -f

# API-Status testen
curl http://localhost:8080/api/status

# Display-Auflösung prüfen
DISPLAY=:0 xrandr
```

## MDS-Server: Terminal registrieren

Einmalig auf dem MDS-Server einen API-Key für das Terminal erzeugen:

```bash
# 1. Login-Token holen
TOKEN=$(curl -s -X POST http://localhost:3000/api/auth/login -H "Content-Type: application/json" -d '{"username":"<USER>","password":"<PASSWORT>"}' | jq -r '.token')

# 2. Terminal registrieren
curl -X POST http://localhost:3000/api/terminal/register -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"name":"Zeiterfassung Halle","location":"Eingang Fertigung"}'
```

Den zurückgegebenen `api_key` in die `config.yaml` auf dem Terminal-Pi eintragen.

bei Docker System mit offenen Port angeben zb 80 oder 81

```bash
# 1. Login-Token holen
TOKEN=$(curl -s -X POST http://localhost:81/api/auth/login -H "Content-Type: application/json" -d '{"username":"<USER>","password":"<PASSWORT>"}' | jq -r '.token')

# 2. Prüfen ob Token da ist
echo $TOKEN

# 3. Terminal registrieren
curl -X POST http://localhost:81/api/terminal/register -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"name":"Zeiterfassung Halle","location":"Eingang Fertigung"}'
```



## MDS-Server: Wichtige Hinweise

- `terminalRoutes` muss in `server.js` **vor** den generischen `/api`-Routes registriert werden (vor `toolListsRoutes` etc.), sonst blockiert die JWT-Middleware die Terminal-API-Key-Authentifizierung.
- Terminal-Endpoints nutzen `X-Terminal-Key` Header statt JWT-Token.

## Pin-Belegung (BCM)

| Funktion | Pin    | Beschreibung   |
|----------|--------|----------------|
| I2C SDA  | GPIO 2 | PN532 Daten    |
| I2C SCL  | GPIO 3 | PN532 Takt     |
| Buzzer   | GPIO 18| KY-006 PWM     |

## Offline-Betrieb

Das Terminal arbeitet offline-first:
- Stempel werden lokal in SQLite gespeichert
- Sync zum Server erfolgt automatisch alle 30 Sekunden
- User-Liste wird alle 5 Minuten vom Server aktualisiert
- Bei Server-Ausfall funktioniert das Stempeln unbegrenzt weiter (für bereits gecachte User)
- Duplikate (409) werden automatisch als gesynct markiert

## Troubleshooting

| Problem | Lösung |
|---------|--------|
| Service startet nicht (status=217/USER) | User in Service-Datei prüfen |
| Kiosk: Permission denied | `usermod -aG video,render,input,tty <USER>` |
| Kiosk: 203/EXEC | Script auf Windows-Zeilenumbrüche prüfen: `sed -i 's/\r$//' kiosk.sh` |
| Display im Hochformat | `xrandr --output DSI-1 --rotate right` im kiosk.sh prüfen |
| Touch-Eingabe verdreht | udev-Regel in `/etc/udev/rules.d/99-touch-rotation.rules` anpassen |
| Schwarzer Rand am Display | `--start-fullscreen --window-size=1280,720 --window-position=0,0` in Chromium-Flags |
| 401 bei Terminal-API | `terminalRoutes` muss in server.js VOR den `/api`-Catch-All Routes stehen |
| Watchdog killt Service | `WatchdogSec` aus der Service-Datei entfernen |
| Getty blockiert Kiosk | `sudo systemctl disable getty@tty1` |
| TypeError: offset-naive/aware | `datetime.now()` → `datetime.now(timezone.utc)` in Python-Code |
| 409 Duplikate im Sync-Log | Normal bei Neustart — werden automatisch als gesynct markiert |
| Chromium Translate-Popup | `--disable-translate --disable-features=TranslateUI --lang=de --incognito` |
