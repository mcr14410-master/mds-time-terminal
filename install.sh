#!/bin/bash
# MDS Time Terminal - Installation auf Raspberry Pi
# Ausführen: chmod +x install.sh && ./install.sh

set -e

echo "=== MDS Time Terminal Installation ==="

# Systemabhängigkeiten
echo ">> System-Pakete installieren..."
sudo apt-get update
sudo apt-get install -y python3-venv python3-pip python3-dev \
    i2c-tools libgpiod-dev

# I2C aktivieren (falls nicht aktiv)
if ! grep -q "^dtparam=i2c_arm=on" /boot/firmware/config.txt 2>/dev/null; then
    echo ">> I2C aktivieren..."
    sudo raspi-config nonint do_i2c 0
    echo "HINWEIS: Neustart erforderlich für I2C!"
fi

# Python Virtual Environment
echo ">> Python venv erstellen..."
python3 -m venv .venv
source .venv/bin/activate

# Dependencies installieren
echo ">> Python-Pakete installieren..."
pip install --upgrade pip
pip install -r requirements.txt

# Konfiguration
if [ ! -f config.yaml ]; then
    echo ">> config.yaml erstellen..."
    cp config.example.yaml config.yaml
    echo "WICHTIG: config.yaml anpassen (Server-URL, GPIO-Pins etc.)"
fi

# Systemd Service
echo ">> Systemd Service installieren..."
sudo cp systemd/mds-terminal.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable mds-terminal.service

# Backlight-Berechtigung (für Display-Steuerung ohne root)
echo ">> Backlight-Berechtigung einrichten..."
UDEV_RULE='SUBSYSTEM=="backlight", ACTION=="add", RUN+="/bin/chmod a+w /sys/class/backlight/%k/brightness"'
echo "$UDEV_RULE" | sudo tee /etc/udev/rules.d/99-backlight.rules > /dev/null
sudo udevadm trigger

# Screen-Blanking deaktivieren (wird vom Terminal selbst gesteuert)
echo ">> Screen-Blanking deaktivieren..."
if ! grep -q "consoleblank=0" /boot/firmware/cmdline.txt 2>/dev/null; then
    sudo sed -i 's/$/ consoleblank=0/' /boot/firmware/cmdline.txt
    echo "HINWEIS: Neustart erforderlich für Screen-Blanking Änderung!"
fi

echo ""
echo "=== Installation abgeschlossen ==="
echo ""
echo "Nächste Schritte:"
echo "  1. config.yaml anpassen: nano config.yaml"
echo "  2. I2C testen: sudo i2cdetect -y 1"
echo "  3. Service starten: sudo systemctl start mds-terminal"
echo "  4. Logs prüfen: journalctl -u mds-terminal -f"
echo "  5. Browser: http://localhost:8080"
echo ""
