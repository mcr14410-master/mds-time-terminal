/**
 * MDS Time Terminal - Frontend Logik
 * 
 * Kommuniziert per WebSocket mit dem lokalen Terminal-Service
 * und per REST-API für Stempelungen und PIN-Login.
 */

// ============================================
// State
// ============================================

let ws = null;
let currentUser = null;       // { id, name, first_name, last_name }
let currentStatus = null;     // { state, valid_actions, worked_minutes, ... }
let autoResetTimer = null;
let countdownInterval = null;
let clockInterval = null;

const ENTRY_LABELS = {
    clock_in: "Kommen",
    clock_out: "Gehen",
    break_start: "Pause Start",
    break_end: "Pause Ende",
};

const STATUS_LABELS = {
    absent: "Nicht anwesend",
    present: "Anwesend",
    break: "In Pause",
};

// ============================================
// Initialisierung
// ============================================

document.addEventListener("DOMContentLoaded", () => {
    startClock();
    connectWebSocket();
    initDisplayWake();
});

// ============================================
// Display Wake bei Touch
// ============================================

function initDisplayWake() {
    let lastTouch = 0;
    document.addEventListener("touchstart", () => {
        const now = Date.now();
        // Max alle 2 Sekunden ein Wake-Signal senden
        if (now - lastTouch < 2000) return;
        lastTouch = now;
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ action: "touch" }));
        }
    }, { passive: true });
}

// ============================================
// Uhr
// ============================================

function startClock() {
    updateClock();
    clockInterval = setInterval(updateClock, 1000);
}

function updateClock() {
    const now = new Date();
    const time = now.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
    const date = now.toLocaleDateString("de-DE", {
        weekday: "long", day: "2-digit", month: "long", year: "numeric"
    });

    const clockEl = document.getElementById("idle-clock");
    if (clockEl) clockEl.textContent = time;

    const dateEl = document.getElementById("idle-date");
    if (dateEl) dateEl.textContent = date;

    const actionTimeEl = document.getElementById("action-time");
    if (actionTimeEl) actionTimeEl.textContent = time;
}

// ============================================
// WebSocket
// ============================================

function connectWebSocket() {
    const protocol = location.protocol === "https:" ? "wss:" : "ws:";
    const url = `${protocol}//${location.host}/ws`;

    ws = new WebSocket(url);

    ws.onopen = () => {
        console.log("WebSocket verbunden");
    };

    ws.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        handleWSEvent(msg.event, msg.data);
    };

    ws.onclose = () => {
        console.log("WebSocket getrennt - Reconnect in 3s");
        setTimeout(connectWebSocket, 3000);
    };

    ws.onerror = () => {
        ws.close();
    };
}

function handleWSEvent(event, data) {
    switch (event) {
        case "connected":
            updateIndicators(data);
            break;

        case "nfc_user":
            handleNFCUser(data.user, data.status);
            break;

        case "nfc_unknown":
            showError("Unbekannte Karte");
            break;

        case "stamp_success":
            // Wird auch als Broadcast empfangen
            break;
    }
}

function updateIndicators(data) {
    const nfc = document.getElementById("indicator-nfc");
    const server = document.getElementById("indicator-server");
    const sync = document.getElementById("indicator-sync");

    if (nfc) nfc.classList.toggle("active", data.nfc_ready);
    if (server) server.classList.toggle("active", data.server_online);
    if (sync) {
            sync.classList.toggle("hidden", data.pending_sync === 0);
        }
}

// ============================================
// Screen Management
// ============================================

function showScreen(name) {
    clearAutoReset();
    document.querySelectorAll(".screen").forEach(s => s.classList.remove("active"));
    const screen = document.getElementById(`screen-${name}`);
    if (screen) screen.classList.add("active");
}

function resetToIdle() {
    clearAutoReset();
    currentUser = null;
    currentStatus = null;
    pinValue = "";
    updatePinDisplay();
    showScreen("idle");
}

// ============================================
// Auto-Reset Timer mit Countdown-Bar
// ============================================

function startAutoReset(seconds, countdownId) {
    clearAutoReset();

    const bar = document.getElementById(countdownId);
    if (bar) {
        bar.innerHTML = '<div class="countdown-bar" style="width: 100%"></div>';
    }

    const startTime = Date.now();
    const duration = seconds * 1000;

    countdownInterval = setInterval(() => {
        const elapsed = Date.now() - startTime;
        const remaining = Math.max(0, 1 - elapsed / duration);
        const barEl = bar?.querySelector(".countdown-bar");
        if (barEl) barEl.style.width = `${remaining * 100}%`;
    }, 50);

    autoResetTimer = setTimeout(() => {
        clearAutoReset();
        resetToIdle();
    }, duration);
}

function clearAutoReset() {
    if (autoResetTimer) clearTimeout(autoResetTimer);
    if (countdownInterval) clearInterval(countdownInterval);
    autoResetTimer = null;
    countdownInterval = null;
}

// ============================================
// NFC User erkannt
// ============================================

function handleNFCUser(user, status) {
    // Falls schon auf dem Action-Screen für denselben User → Quick-Stamp
    // (Karte nochmal auflegen = häufigste Aktion ausführen)
    if (currentUser && currentUser.id === user.id &&
        document.getElementById("screen-action").classList.contains("active")) {
        quickStamp(status);
        return;
    }

    currentUser = user;
    currentStatus = status;

    showActionScreen();
}

function quickStamp(status) {
    // Bei Quick-Stamp: Erste gültige Aktion ausführen
    if (status.valid_actions.length === 1) {
        stamp(status.valid_actions[0]);
    }
    // Bei mehreren Optionen: Action-Screen bleibt, kein Auto-Stamp
}

// ============================================
// Action Screen
// ============================================

function showActionScreen() {
    if (!currentUser || !currentStatus) return;

    document.getElementById("action-user").textContent = currentUser.name;

    // Status-Text
    const statusText = STATUS_LABELS[currentStatus.state] || "";
    let detail = "";
    if (currentStatus.state === "present" && currentStatus.net_minutes > 0) {
        detail = ` seit ${formatMinutes(currentStatus.net_minutes)}`;
    }
    document.getElementById("action-status-text").textContent = statusText + detail;

    // Buttons aktivieren/deaktivieren basierend auf valid_actions
    const actions = currentStatus.valid_actions || [];
    document.getElementById("btn-clock-in").disabled = !actions.includes("clock_in");
    document.getElementById("btn-clock-out").disabled = !actions.includes("clock_out");
    document.getElementById("btn-break-start").disabled = !actions.includes("break_start");
    document.getElementById("btn-break-end").disabled = !actions.includes("break_end");

    // Disabled Buttons ausblenden für cleane UI
    document.getElementById("btn-clock-in").classList.toggle("hidden", !actions.includes("clock_in"));
    document.getElementById("btn-clock-out").classList.toggle("hidden", !actions.includes("clock_out"));
    document.getElementById("btn-break-start").classList.toggle("hidden", !actions.includes("break_start"));
    document.getElementById("btn-break-end").classList.toggle("hidden", !actions.includes("break_end"));

    showScreen("action");
    startAutoReset(15, ""); // Auto-Reset nach 15s Inaktivität (ohne Bar)
}

// ============================================
// Stempeln
// ============================================

async function stamp(entryType) {
    if (!currentUser) return;

    clearAutoReset();

    try {
        const resp = await fetch("/api/stamp", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                user_id: currentUser.id,
                entry_type: entryType,
            }),
        });

        const data = await resp.json();

        if (!resp.ok) {
            showError(data.detail || "Fehler beim Stempeln");
            return;
        }

        // Erfolg anzeigen
        showSuccess(entryType, data);

    } catch (err) {
        console.error("Stamp error:", err);
        showError("Verbindungsfehler zum Terminal-Service");
    }
}

// ============================================
// Erfolg-Screen
// ============================================

function showSuccess(entryType, data) {
    const screen = document.getElementById("screen-success");
    screen.classList.remove("error-type");

    const now = new Date();
    const time = now.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
    const label = ENTRY_LABELS[entryType] || entryType;

    document.getElementById("success-message").textContent =
        `${label} – ${currentUser.name}`;
    document.getElementById("success-time").textContent = time;

    // Detail-Info
    const detailEl = document.getElementById("success-detail");
    let detail = "";

    if (data.status) {
        if (entryType === "clock_out" && data.status.net_minutes > 0) {
                    // Sofort 3 Zeilen mit Platzhalter
                    detailEl.innerText = `Arbeitszeit heute: ${formatMinutes(data.status.net_minutes)}\nSaldo heute: ...\nZeitkonto: ...`;

                    // Kurz warten bis Sync durch ist, dann Server-Info holen
                    setTimeout(() => {
                        fetch(`/api/user/${currentUser.id}/info`)
                    .then(r => r.json())
                    .then(info => {
                        if (info.server_info) {
                            const si = info.server_info;
                            const worked = si.today?.worked_minutes ?? data.status.net_minutes;
                            const targetDay = si.today?.target_minutes ?? 0;
                            const saldoToday = worked - targetDay;
                            const saldoTotal = si.balance_minutes;

                            let lines = `Arbeitszeit heute: ${formatMinutes(worked)}`;
                            lines += `\nSaldo heute: ${formatSaldo(saldoToday)}`;
                            lines += `\nZeitkonto: ${formatSaldo(saldoTotal)}`;
                            detailEl.innerText = lines;
                        }
                    })
                    .catch(() => {});
                    }, 1500);

        } else if (entryType === "clock_in") {
            detail = "Guten Morgen!";
        } else if (entryType === "break_start") {
            detail = "Gute Pause!";
        } else if (entryType === "break_end") {
            detail = `Pause: ${formatMinutes(data.status.break_minutes)}`;
        }
    }

    if (!data.server_online) {
        detail += (detail ? " · " : "") + "⚠ Offline gespeichert";
    }

    if (entryType !== "clock_out" || !data.status || data.status.net_minutes <= 0) {
        detailEl.textContent = detail;
    }

    showScreen("success");
    startAutoReset(8, "success-countdown");

// Indicators aktualisieren (kurz warten bis Sync durch)
    setTimeout(() => {
        fetch("/api/status").then(r => r.json()).then(updateIndicators).catch(() => {});
    }, 2000);
}

// ============================================
// Error-Screen
// ============================================

function showError(message) {
    document.getElementById("error-message").textContent = message;
    showScreen("error");
    startAutoReset(5, "error-countdown");
}

// ============================================
// PIN Eingabe
// ============================================

let pinValue = "";

function pinInput(digit) {
    if (pinValue.length >= 6) return;
    pinValue += digit;
    updatePinDisplay();

    // Auto-Submit bei 4 Zeichen (konfigurierbar)
    if (pinValue.length === 4) {
        pinSubmit();
    }
}

function pinClear() {
    if (pinValue.length > 0) {
        pinValue = pinValue.slice(0, -1);
        updatePinDisplay();
    }
}

function updatePinDisplay() {
    const display = document.getElementById("pin-display");
    let text = "";
    for (let i = 0; i < 4; i++) {
        text += i < pinValue.length ? "●" : "_";
    }
    display.textContent = text;
}

async function pinSubmit() {
    if (pinValue.length < 4) return;

    const pin = pinValue;
    pinValue = "";

    try {
        const resp = await fetch("/api/pin-login", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ pin_code: pin }),
        });

        const data = await resp.json();

        if (!resp.ok) {
            document.getElementById("pin-error").textContent = data.detail || "PIN falsch";
            document.getElementById("pin-error").classList.remove("hidden");
            updatePinDisplay();
            setTimeout(() => {
                document.getElementById("pin-error").classList.add("hidden");
            }, 3000);
            return;
        }

        // Login erfolgreich
        document.getElementById("pin-error").classList.add("hidden");
        currentUser = data.user;
        currentStatus = data.status;
        showActionScreen();

    } catch (err) {
        console.error("PIN login error:", err);
        document.getElementById("pin-error").textContent = "Verbindungsfehler";
        document.getElementById("pin-error").classList.remove("hidden");
        updatePinDisplay();
    }
}

// ============================================
// Info-Screen
// ============================================

async function showInfo() {
    if (!currentUser) return;
    clearAutoReset();

    document.getElementById("info-user-name").textContent = `Zeitkonto – ${currentUser.name}`;

    // Lokale Daten sofort anzeigen
    if (currentStatus) {
        document.getElementById("info-today").textContent = formatMinutes(currentStatus.net_minutes || 0);
    }

    // Server-Daten laden
    try {
        const resp = await fetch(`/api/user/${currentUser.id}/info`);
        const data = await resp.json();

        if (data.server_info) {
            const si = data.server_info;

            // Heute
            if (si.today) {
                document.getElementById("info-today").textContent =
                    formatMinutes(si.today.worked_minutes || 0);
                if (si.today.overtime_minutes !== undefined) {
                    setDiff("info-today-diff", si.today.overtime_minutes);
                }
            }

            // Woche
            if (si.week) {
                document.getElementById("info-week").textContent =
                    formatMinutes(si.week.worked_minutes || 0);
                setDiff("info-week-diff", si.week.overtime_minutes);
            }

            // Monat
            if (si.month) {
                document.getElementById("info-month").textContent =
                    formatMinutes(si.month.worked_minutes || 0);
                setDiff("info-month-diff", si.month.overtime_minutes);
            }

            // Zeitkonto
            if (si.balance_minutes !== null && si.balance_minutes !== undefined) {
                const bal = si.balance_minutes;
                const el = document.getElementById("info-balance");
                el.textContent = formatSaldo(bal);
                el.className = "info-value " + (bal >= 0 ? "positive" : "negative");
            }

            // Resturlaub
            if (si.vacation_days_remaining !== null) {
                document.getElementById("info-vacation").textContent =
                    `${si.vacation_days_remaining} Tage`;
            }

            // Letzte Buchungen
            if (si.recent_entries) {
                const list = document.getElementById("info-entries-list");
                list.innerHTML = "";
                for (const entry of si.recent_entries) {
                    const ts = new Date(entry.timestamp);
                    const row = document.createElement("div");
                    row.className = "info-entry-row";
                    row.innerHTML = `
                        <span>${ENTRY_LABELS[entry.entry_type] || entry.entry_type}</span>
                        <span>${ts.toLocaleDateString("de-DE")} ${ts.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" })}</span>
                    `;
                    list.appendChild(row);
                }
            }

            document.getElementById("info-offline-hint").classList.add("hidden");
        } else {
            // Offline - lokale Daten
            document.getElementById("info-offline-hint").classList.remove("hidden");
            document.getElementById("info-week").textContent = "--:--";
            document.getElementById("info-month").textContent = "--:--";
            document.getElementById("info-balance").textContent = "--:--";
            document.getElementById("info-balance").className = "info-value";
            document.getElementById("info-vacation").textContent = "-- Tage";
        }

    } catch (err) {
        console.error("Info fetch error:", err);
        document.getElementById("info-offline-hint").classList.remove("hidden");
    }

    showScreen("info");
    startAutoReset(30, "info-countdown");
}

// ============================================
// Korrektur-Screen
// ============================================

let corrType = "";
let corrDay = "today";
let corrTimeDigits = "";
let corrReason = "";

function showCorrectionScreen() {
    if (!currentUser) return;
    
    // Reset
    corrType = "";
    corrDay = "today";
    corrTimeDigits = "";
    corrReason = "";
    
    // UI zurücksetzen
    document.querySelectorAll(".btn-corr-type").forEach(b => b.classList.remove("active"));
    document.getElementById("corr-day-today").classList.add("active");
    document.getElementById("corr-day-yesterday").classList.remove("active");
    document.getElementById("corr-time-display").textContent = "--:--";
    document.getElementById("corr-error").classList.add("hidden");
    document.querySelectorAll(".btn-corr-reason").forEach(b => b.classList.remove("active"));
    document.getElementById("btn-corr-submit").disabled = true;
    
    showScreen("correction");
    startAutoReset(60, "");
}

function corrSetType(type) {
    corrType = type;
    document.querySelectorAll(".btn-corr-type").forEach(b => {
        b.classList.toggle("active", b.dataset.type === type);
    });
    corrValidate();
}

function corrSetDay(day) {
    corrDay = day;
    document.getElementById("corr-day-today").classList.toggle("active", day === "today");
    document.getElementById("corr-day-yesterday").classList.toggle("active", day === "yesterday");
}

function corrTimeInput(digit) {
    if (corrTimeDigits.length >= 4) return;
    corrTimeDigits += digit;
    corrUpdateTimeDisplay();
    corrValidate();
}

function corrTimeClear() {
    corrTimeDigits = corrTimeDigits.slice(0, -1);
    corrUpdateTimeDisplay();
    corrValidate();
}

function corrUpdateTimeDisplay() {
    const d = corrTimeDigits.padEnd(4, "_");
    document.getElementById("corr-time-display").textContent = `${d[0]}${d[1]}:${d[2]}${d[3]}`;
}

function corrSetReason(reason) {
    corrReason = reason;
    document.querySelectorAll(".btn-corr-reason").forEach(b => {
        b.classList.toggle("active", b.textContent.trim() === reason);
    });
    corrValidate();
}

function corrValidate() {
    const timeValid = corrTimeDigits.length === 4;
    let valid = corrType && timeValid && corrReason;
    
    // Uhrzeit plausibel? (00:00 - 23:59)
    if (timeValid) {
        const h = parseInt(corrTimeDigits.substring(0, 2));
        const m = parseInt(corrTimeDigits.substring(2, 4));
        if (h > 23 || m > 59) valid = false;
    }
    
    document.getElementById("btn-corr-submit").disabled = !valid;
}

async function submitCorrection() {
    if (!currentUser || !corrType || corrTimeDigits.length < 4 || !corrReason) return;
    
    const h = corrTimeDigits.substring(0, 2);
    const m = corrTimeDigits.substring(2, 4);
    
    clearAutoReset();
    document.getElementById("btn-corr-submit").disabled = true;
    
    try {
        const resp = await fetch("/api/correction", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                user_id: currentUser.id,
                entry_type: corrType,
                date: corrDay,
                time: `${h}:${m}`,
                reason: corrReason,
            }),
        });
        
        const data = await resp.json();
        
        if (!resp.ok) {
            document.getElementById("corr-error").textContent = data.detail || "Fehler beim Speichern";
            document.getElementById("corr-error").classList.remove("hidden");
            document.getElementById("btn-corr-submit").disabled = false;
            return;
        }
        
        // Erfolg
        const typeLabels = { clock_in: "Kommen", clock_out: "Gehen", break_start: "Pause Start", break_end: "Pause Ende" };
        const dayLabel = corrDay === "yesterday" ? "gestern" : "heute";
        
        const screen = document.getElementById("screen-success");
        screen.querySelector(".success-icon").style.color = "#f97316"; // Orange für Korrektur
        document.getElementById("success-message").textContent = `Korrektur eingereicht`;
        document.getElementById("success-time").textContent = `${typeLabels[corrType]} · ${dayLabel} ${h}:${m}`;
        document.getElementById("success-detail").textContent = `Muss vom Vorgesetzten bestätigt werden`;
        
        showScreen("success");
        startAutoReset(5, "success-countdown");
        
    } catch (err) {
        document.getElementById("corr-error").textContent = "Verbindungsfehler";
        document.getElementById("corr-error").classList.remove("hidden");
        document.getElementById("btn-corr-submit").disabled = false;
    }
}

// ============================================
// Hilfsfunktionen
// ============================================

function formatMinutes(totalMinutes) {
    const negative = totalMinutes < 0;
    const abs = Math.abs(Math.round(totalMinutes));
    const h = Math.floor(abs / 60);
    const m = abs % 60;
    const str = `${h}:${String(m).padStart(2, "0")}`;
    return negative ? `-${str}` : str;
}

function formatSaldo(minutes) {
    const sign = minutes >= 0 ? "+" : "-";
    const abs = Math.abs(Math.round(minutes));
    const h = Math.floor(abs / 60);
    const m = abs % 60;
    return `${sign}${h}:${String(m).padStart(2, "0")}`;
}

function setDiff(elementId, overtimeMinutes) {
    const el = document.getElementById(elementId);
    if (!el) return;
    const val = parseInt(overtimeMinutes) || 0;
    el.textContent = formatSaldo(val);
    el.className = "info-diff " + (val >= 0 ? "positive" : "negative");
}

// Keyboard-Fallback für Entwicklung (NFC simulieren)
document.addEventListener("keydown", (e) => {
    // F1 = Test NFC scan simulieren
    if (e.key === "F1" && ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({
            action: "simulate_nfc",
            uid: "AABBCCDD",
        }));
    }
    // Escape = zurück zum Idle
    if (e.key === "Escape") {
        resetToIdle();
    }
});
