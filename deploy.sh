#!/usr/bin/env bash
set -euo pipefail

# --- Pfade ---
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE="mds-terminal"
VENV="$SCRIPT_DIR/.venv"

echo "═══════════════════════════════════════"
echo "  MDS Time Terminal Deploy"
echo "═══════════════════════════════════════"
echo "[deploy] Pfad: $SCRIPT_DIR"

# --- Minimalchecks ---
test -f "$SCRIPT_DIR/service/main.py" || { echo "❌ main.py nicht gefunden"; exit 1; }
systemctl is-enabled "$SERVICE" >/dev/null 2>&1 || { echo "❌ Service $SERVICE nicht installiert"; exit 1; }

# --- Service stoppen ---
echo "[deploy] ⏹️  Service stoppen..."
sudo systemctl stop "$SERVICE"
echo "[deploy] ✅ Service gestoppt"

# --- Git Pull ---
if [ -d "$SCRIPT_DIR/.git" ]; then
  echo "[deploy] 📥 Git pull..."
  pushd "$SCRIPT_DIR" >/dev/null
  if ! git diff --quiet 2>/dev/null || ! git diff --quiet --staged 2>/dev/null; then
    echo "[deploy] ⚠️  Lokale Änderungen -> autostash"
    git stash push -m "deploy-autostash $(date -Iseconds)" || true
    STASHED=1
  else
    STASHED=0
  fi
  git pull --rebase
  if [ "${STASHED:-0}" = "1" ]; then
    git stash pop || true
  fi
  popd >/dev/null
else
  echo "[deploy] ⚠️  Kein Git-Repo, skip pull"
fi

# --- Dependencies prüfen ---
if [ -f "$SCRIPT_DIR/requirements.txt" ] && [ -d "$VENV" ]; then
  echo "[deploy] 📦 Dependencies prüfen..."
  "$VENV/bin/pip" install -q -r "$SCRIPT_DIR/requirements.txt" 2>/dev/null \
    && echo "[deploy] ✅ Dependencies aktuell" \
    || echo "[deploy] ⚠️  Einige Packages konnten nicht installiert werden"
fi

# --- Service starten ---
echo "[deploy] ▶️  Service starten..."
sudo systemctl start "$SERVICE"
sleep 2

# --- Status ---
echo ""
echo "[deploy] 📊 Status:"
systemctl status "$SERVICE" --no-pager -l | head -15

# --- Health-Check ---
echo ""
echo "[deploy] 🏥 Health-Check:"
sleep 1
if curl -sf http://localhost:8080/ >/dev/null 2>&1; then
  echo "✅ Terminal erreichbar auf Port 8080"
else
  echo "⚠️  Terminal antwortet nicht (noch am Starten?)"
  echo "    Prüfe mit: sudo journalctl -u $SERVICE -f"
fi

echo ""
echo "═══════════════════════════════════════"
echo "  ✅ Deploy abgeschlossen!"
echo "═══════════════════════════════════════"
