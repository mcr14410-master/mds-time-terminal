"""
MDS Time Terminal - Hauptanwendung.

FastAPI Server mit:
- WebSocket für NFC-Events und Buzzer-Steuerung
- REST API für PIN-Login und Stempelung
- Statische Dateien (Terminal-UI)
- Background Tasks (NFC-Polling, Sync)
"""

import asyncio
import logging
import logging.handlers
import os
import json
from datetime import datetime, timezone
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from service import config, db
from service.nfc_reader import NFCReader
from service.buzzer import Buzzer
from service.sync import SyncService
from service.display import Display


# ============================================
# Logging Setup
# ============================================

def setup_logging():
    cfg = config.get("logging")
    level = getattr(logging, cfg.get("level", "INFO"))

    # Projektverzeichnis
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    log_file = os.path.join(base_dir, cfg.get("file", "terminal.log"))
    max_bytes = cfg.get("max_size_mb", 10) * 1024 * 1024

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # File Handler (Rotation)
    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=max_bytes, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)

    # Console Handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)


logger = logging.getLogger(__name__)


# ============================================
# Globale Komponenten
# ============================================

nfc: NFCReader = None
buzzer: Buzzer = None
sync_service: SyncService = None
display: Display = None
ws_connections: set[WebSocket] = set()


# ============================================
# WebSocket Broadcast
# ============================================

async def broadcast(event: str, data: dict = None):
    """Sendet Event an alle verbundenen WebSocket-Clients."""
    message = json.dumps({"event": event, "data": data or {}})
    dead = set()
    for ws in ws_connections:
        try:
            await ws.send_text(message)
        except Exception:
            dead.add(ws)
    ws_connections.difference_update(dead)


# ============================================
# NFC Tag Callback
# ============================================

async def on_nfc_tag(uid: str):
    """Wird aufgerufen wenn ein NFC-Tag gelesen wird."""
    logger.info(f"NFC Tag: {uid}")

    # Display aufwecken
    if display:
        display.wake()

    # Scan-Ton
    await buzzer.scan()

    # User in lokalem Cache suchen
    user = db.find_user_by_rfid(uid)

    if user is None:
        # Unbekannte Karte
        await buzzer.error()
        await broadcast("nfc_unknown", {"uid": uid})
        logger.warning(f"Unbekannte NFC-Karte: {uid}")
        return

    # User gefunden - Status und Info an UI senden
    status = db.get_user_status(user["id"])

    await broadcast("nfc_user", {
        "user": {
            "id": user["id"],
            "name": f"{user['first_name']} {user['last_name']}",
            "first_name": user["first_name"],
            "last_name": user["last_name"],
        },
        "status": status,
    })


# ============================================
# Stempel-Logik
# ============================================

async def perform_stamp(user_id: int, entry_type: str) -> dict:
    """
    Führt Stempelung durch.
    1. Lokal speichern
    2. Buzzer-Feedback
    3. Sync versuchen
    4. Status zurückgeben
    """
    user = db.get_user_by_id(user_id)
    if not user:
        raise ValueError("User nicht gefunden")

    # Aktuelle Uhrzeit
    now = datetime.now(timezone.utc).isoformat()

    # Validierung: Ist diese Aktion gerade erlaubt?
    current_status = db.get_user_status(user_id)
    if entry_type not in current_status["valid_actions"]:
        await buzzer.error()
        valid_labels = [db.ENTRY_LABELS.get(a, a) for a in current_status["valid_actions"]]
        raise ValueError(
            f"'{db.ENTRY_LABELS.get(entry_type, entry_type)}' nicht möglich. "
            f"Erlaubt: {', '.join(valid_labels)}"
        )

    # Lokal speichern
    stamp_id = db.save_stamp(user_id, entry_type, now)

    # Erfolgs-Ton
    await buzzer.success()

    # Sofort Sync versuchen (non-blocking)
    if sync_service.server_online:
        asyncio.create_task(sync_service.sync_stamps())

    # Neuen Status berechnen
    new_status = db.get_user_status(user_id)
    pending = db.get_pending_count()

    result = {
        "stamp_id": stamp_id,
        "user": {
            "id": user["id"],
            "name": f"{user['first_name']} {user['last_name']}",
        },
        "entry_type": entry_type,
        "timestamp": now,
        "status": new_status,
        "server_online": sync_service.server_online,
        "pending_sync": pending,
    }

    # Broadcast an alle Clients
    await broadcast("stamp_success", result)

    return result


# ============================================
# Display Idle Check
# ============================================

async def display_idle_loop():
    """Prüft periodisch ob das Display in den Schlaf geschickt werden soll."""
    while True:
        await asyncio.sleep(5)
        if display:
            display.check_idle()


# ============================================
# App Lifecycle
# ============================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / Shutdown."""
    global nfc, buzzer, sync_service, display

    setup_logging()
    logger.info("=== MDS Time Terminal startet ===")

    # Datenbank initialisieren
    db.init_db()

    # Komponenten erstellen
    buzzer = Buzzer()
    buzzer.init_hardware()

    display = Display()
    display.init_hardware()

    sync_service = SyncService()

    nfc = NFCReader(on_tag_read=on_nfc_tag)
    nfc_ready = nfc.init_hardware()

    # Background Tasks starten
    tasks = []

    if nfc_ready:
        tasks.append(asyncio.create_task(nfc.start_polling()))

    tasks.append(asyncio.create_task(sync_service.start_sync_loop()))
    tasks.append(asyncio.create_task(display_idle_loop()))

    logger.info("=== Terminal bereit ===")
    await buzzer.success()  # Startup-Ton

    yield

    # Shutdown
    logger.info("=== Terminal wird beendet ===")
    nfc.stop()
    sync_service.stop()
    buzzer.cleanup()
    display.cleanup()

    for task in tasks:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    logger.info("=== Terminal beendet ===")


# ============================================
# FastAPI App
# ============================================

app = FastAPI(title="MDS Time Terminal", lifespan=lifespan)


# ============================================
# WebSocket
# ============================================

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    ws_connections.add(ws)
    logger.info(f"WebSocket Client verbunden ({len(ws_connections)} aktiv)")

    # Initialen Status senden
    await ws.send_text(json.dumps({
        "event": "connected",
        "data": {
            "server_online": sync_service.server_online if sync_service else False,
            "nfc_ready": nfc.is_hardware_ready if nfc else False,
            "pending_sync": db.get_pending_count(),
            "terminal_name": config.get("terminal", "name"),
        }
    }))

    try:
        while True:
            data = await ws.receive_text()
            msg = json.loads(data)
            await handle_ws_message(ws, msg)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"WebSocket Fehler: {e}")
    finally:
        ws_connections.discard(ws)
        logger.info(f"WebSocket Client getrennt ({len(ws_connections)} aktiv)")


async def handle_ws_message(ws: WebSocket, msg: dict):
    """Verarbeitet Nachrichten vom Frontend."""
    action = msg.get("action")

    if action == "simulate_nfc":
        # Für Tests: NFC-Scan simulieren
        uid = msg.get("uid", "")
        if uid and nfc:
            await nfc.simulate_tag(uid)

    elif action == "buzzer_test":
        tone = msg.get("tone", "scan")
        if buzzer:
            method = getattr(buzzer, tone, buzzer.scan)
            await method()

    elif action == "touch":
        # Display aufwecken bei Touch-Event vom Frontend
        if display:
            display.wake()


# ============================================
# REST API Endpoints
# ============================================

class StampRequest(BaseModel):
    user_id: int
    entry_type: str


class CorrectionRequest(BaseModel):
    user_id: int
    entry_type: str
    date: str       # 'today' | 'yesterday'
    time: str       # 'HH:MM'
    reason: str


class PinLoginRequest(BaseModel):
    pin_code: str


@app.post("/api/stamp")
async def api_stamp(req: StampRequest):
    """Stempelung per Touch-Button (nach NFC/PIN Login)."""
    try:
        result = await perform_stamp(req.user_id, req.entry_type)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/correction")
async def api_correction(req: CorrectionRequest):
    """Korrektur-Buchung: vergessene Stempelung nachtragen."""
    user = db.get_user_by_id(req.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User nicht gefunden")

    if not req.reason or len(req.reason.strip()) < 3:
        raise HTTPException(status_code=400, detail="Grund muss mind. 3 Zeichen haben")

    valid_types = ["clock_in", "clock_out", "break_start", "break_end"]
    if req.entry_type not in valid_types:
        raise HTTPException(status_code=400, detail="Ungültiger Buchungstyp")

    # Datum berechnen
    from datetime import date as date_type, timedelta
    if req.date == "yesterday":
        target_date = date_type.today() - timedelta(days=1)
    else:
        target_date = date_type.today()

    # Timestamp zusammenbauen (lokal)
    timestamp = f"{target_date.isoformat()}T{req.time}:00"

    # Lokal speichern (mit Korrektur-Flag)
    stamp_id = db.save_correction(req.user_id, req.entry_type, timestamp, req.reason.strip())

    # Buzzer
    await buzzer.success()

    # Sofort Sync versuchen
    if sync_service.server_online:
        asyncio.create_task(sync_service.sync_stamps())

    # Status aktualisieren und broadcast
    new_status = db.get_user_status(req.user_id)
    pending = db.get_pending_count()

    result = {
        "stamp_id": stamp_id,
        "user": {
            "id": user["id"],
            "name": f"{user['first_name']} {user['last_name']}",
        },
        "entry_type": req.entry_type,
        "timestamp": timestamp,
        "is_correction": True,
        "status": new_status,
        "server_online": sync_service.server_online,
        "pending_sync": pending,
    }

    await broadcast("correction_success", result)

    return result


@app.post("/api/pin-login")
async def api_pin_login(req: PinLoginRequest):
    """Login per PIN-Eingabe (Fallback ohne NFC)."""
    user = db.find_user_by_pin(req.pin_code)
    if not user:
        await buzzer.error()
        raise HTTPException(status_code=404, detail="PIN nicht erkannt")

    await buzzer.scan()

    status = db.get_user_status(user["id"])

    return {
        "user": {
            "id": user["id"],
            "name": f"{user['first_name']} {user['last_name']}",
            "first_name": user["first_name"],
            "last_name": user["last_name"],
        },
        "status": status,
    }


@app.get("/api/user/{user_id}/status")
async def api_user_status(user_id: int):
    """Aktueller Status eines Users."""
    user = db.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User nicht gefunden")

    status = db.get_user_status(user_id)
    return {"user_id": user_id, "status": status}


@app.get("/api/user/{user_id}/info")
async def api_user_info(user_id: int):
    """
    Detaillierte User-Info für Info-Screen.
    Versucht Server-Daten, Fallback auf lokale Daten.
    """
    user = db.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User nicht gefunden")

    # Server-Info versuchen
    server_info = None
    if sync_service and sync_service.server_online:
        server_info = await sync_service.get_user_info(user_id=user["id"])

    # Lokaler Status
    local_status = db.get_user_status(user_id)

    return {
        "user": {
            "id": user["id"],
            "name": f"{user['first_name']} {user['last_name']}",
        },
        "local_status": local_status,
        "server_info": server_info,  # None wenn offline
        "server_online": sync_service.server_online if sync_service else False,
    }


@app.get("/api/users")
async def api_users():
    """Alle aktiven User (für PIN-Login Grid)."""
    users = db.get_all_active_users()
    return users


@app.get("/api/status")
async def api_terminal_status():
    """Terminal-Status (Netzwerk, NFC, Queue)."""
    return {
        "server_online": sync_service.server_online if sync_service else False,
        "nfc_ready": nfc.is_hardware_ready if nfc else False,
        "pending_sync": db.get_pending_count(),
        "terminal": config.get("terminal"),
    }


# ============================================
# Statische Dateien (Terminal-UI)
# ============================================

web_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")

@app.get("/")
async def serve_index():
    return FileResponse(os.path.join(web_dir, "index.html"))

# CSS, JS, Bilder etc.
app.mount("/static", StaticFiles(directory=web_dir), name="static")


# ============================================
# Einstiegspunkt
# ============================================

def main():
    import uvicorn
    cfg = config.get("web")
    uvicorn.run(
        "service.main:app",
        host=cfg.get("host", "0.0.0.0"),
        port=cfg.get("port", 8080),
        log_level="info",
    )


if __name__ == "__main__":
    main()
