"""
Modo de prueba — Stream Code Redeemer Bot
Genera un "stream" falso con códigos apareciendo en pantalla
y simula el canjeo sin tocar APIs reales.

Uso:
    python test_mode.py
"""

import cv2
import numpy as np
import threading
import time
import random
import string
import sqlite3
import re
import logging
from datetime import datetime
from pathlib import Path

# ─── Logging ────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()],
)
log = logging.getLogger(__name__)

# ─── Patrones (igual que bot.py) ────────────────────────────────────────────
PSN_PATTERN  = re.compile(r"\b([A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4})\b")
XBOX_PATTERN = re.compile(r"\b([A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{5})\b")

# ─── Base de datos (igual que bot.py) ───────────────────────────────────────
DB_PATH = Path("test_codes.db")

def init_db():
    con = sqlite3.connect(DB_PATH)
    con.execute("""
        CREATE TABLE IF NOT EXISTS codes (
            code TEXT PRIMARY KEY,
            platform TEXT,
            status TEXT DEFAULT 'pending',
            detected_at TEXT,
            redeemed_at TEXT
        )
    """)
    con.commit(); con.close()

def is_already_seen(code):
    con = sqlite3.connect(DB_PATH)
    row = con.execute("SELECT 1 FROM codes WHERE code=?", (code,)).fetchone()
    con.close()
    return row is not None

def save_code(code, platform, status="pending"):
    con = sqlite3.connect(DB_PATH)
    con.execute(
        "INSERT OR IGNORE INTO codes (code,platform,status,detected_at) VALUES (?,?,?,?)",
        (code, platform, status, datetime.utcnow().isoformat()),
    )
    con.commit(); con.close()

def mark_redeemed(code, status):
    con = sqlite3.connect(DB_PATH)
    con.execute(
        "UPDATE codes SET status=?, redeemed_at=? WHERE code=?",
        (status, datetime.utcnow().isoformat(), code),
    )
    con.commit(); con.close()

# ─── Generador de códigos falsos ─────────────────────────────────────────────
def _rand(n):
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=n))

def fake_psn_code():
    return f"{_rand(4)}-{_rand(4)}-{_rand(4)}"

def fake_xbox_code():
    return f"{_rand(5)}-{_rand(5)}-{_rand(5)}-{_rand(5)}-{_rand(5)}"

# ─── Simulador de stream ──────────────────────────────────────────────────────
class FakeStream:
    """
    Genera frames BGR que imitan un stream de Twitch/YouTube.
    Cada cierto tiempo aparece un código en pantalla.
    """
    W, H = 1280, 720

    def __init__(self):
        self.frame       = self._make_base_frame()
        self.code_text   = ""
        self.code_timer  = 0
        self.lock        = threading.Lock()
        self._running    = True
        threading.Thread(target=self._update_loop, daemon=True).start()

    def _make_base_frame(self):
        # Fondo degradado azul oscuro (simula un juego)
        frame = np.zeros((self.H, self.W, 3), dtype=np.uint8)
        for y in range(self.H):
            b = int(30 + y * 40 / self.H)
            g = int(10 + y * 20 / self.H)
            r = int(5  + y * 10 / self.H)
            frame[y, :] = (b, g, r)
        # Texto de "stream" decorativo
        cv2.putText(frame, "LIVE STREAM - PlayStation Store",
                    (40, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (200, 200, 200), 2)
        cv2.putText(frame, "Watch & Win! Codes dropping every few seconds...",
                    (40, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (150, 150, 150), 1)
        # Borde rojo "REC"
        cv2.rectangle(frame, (0,0), (self.W-1, self.H-1), (0,0,180), 4)
        cv2.circle(frame, (1220, 30), 10, (0, 0, 220), -1)
        cv2.putText(frame, "REC", (1230, 38),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,0,220), 2)
        return frame

    def _update_loop(self):
        """Cada 6-12 s aparece un código nuevo en pantalla durante 4 s."""
        platforms = ["psn", "psn", "xbox"]  # PSN aparece más seguido
        while self._running:
            wait = random.uniform(6, 12)
            time.sleep(wait)
            platform = random.choice(platforms)
            code = fake_psn_code() if platform == "psn" else fake_xbox_code()
            with self.lock:
                self.code_text  = code
                self.code_timer = time.time() + 4  # visible 4 s

    def read(self):
        """Devuelve (True, frame) igual que cv2.VideoCapture.read()."""
        base = self._make_base_frame()
        with self.lock:
            if self.code_text and time.time() < self.code_timer:
                self._draw_code(base, self.code_text)
            else:
                self.code_text = ""
        return True, base

    def _draw_code(self, frame, code):
        # Caja semitransparente centrada
        overlay = frame.copy()
        cx, cy  = self.W // 2, self.H // 2
        cv2.rectangle(overlay, (cx-320, cy-60), (cx+320, cy+60), (20,20,20), -1)
        cv2.addWeighted(overlay, 0.75, frame, 0.25, 0, frame)
        cv2.rectangle(frame, (cx-320, cy-60), (cx+320, cy+60), (0,180,255), 2)
        # Etiqueta plataforma
        label = "PSN CODE" if "-" in code and len(code) < 15 else "XBOX CODE"
        color = (255, 140, 0) if "PSN" in label else (0, 200, 80)
        cv2.putText(frame, label,
                    (cx-310, cy-20), cv2.FONT_HERSHEY_SIMPLEX, 0.9, color, 2)
        # El código grande
        cv2.putText(frame, code,
                    (cx-300, cy+40), cv2.FONT_HERSHEY_DUPLEX, 1.3, (255,255,255), 2)

    def release(self):
        self._running = False


# ─── API de canjeo simulada ───────────────────────────────────────────────────
_already_taken = set()   # simula códigos "ya canjeados por otro"

def mock_redeem(code, platform):
    """Simula canjeo: 70% éxito, 20% ya canjeado por otro, 10% error."""
    time.sleep(0.4)  # simula latencia de red
    r = random.random()
    if r < 0.70:
        return "redeemed"
    elif r < 0.90:
        return "already_taken"
    else:
        return "failed"

REWARDS = {
    "psn" : ["GT6 DLC Car Pack", "PS Store $10 Credit", "PS Plus 1 mes",
             "Gran Turismo 7 Skin", "Mortal Kombat DLC"],
    "xbox": ["500 Microsoft Points", "Xbox Game Pass 7 días",
             "Halo Infinite Bundle", "Forza Horizon DLC", "Xbox $5 Credit"],
}

# ─── Pipeline principal ───────────────────────────────────────────────────────
def run_test():
    try:
        import easyocr
        reader = easyocr.Reader(["en"], gpu=False)
        log.info("Modelo OCR cargado.")
        use_ocr = True
    except ImportError:
        log.warning("easyocr no instalado — usando detección directa del frame (modo demo).")
        use_ocr = False

    init_db()
    stream  = FakeStream()
    fps     = 30
    skip    = fps * 3   # analizar cada 3 s
    counter = 0

    log.info("=" * 55)
    log.info("  MODO PRUEBA ACTIVO — stream falso con códigos")
    log.info("  Presiona Ctrl+C para detener")
    log.info("=" * 55)

    try:
        while True:
            ret, frame = stream.read()
            if not ret:
                break

            counter += 1
            if counter % skip != 0:
                time.sleep(1 / fps)
                continue

            # Extraer texto
            if use_ocr:
                results  = reader.readtext(frame, detail=0)
                text     = " ".join(results).upper()
            else:
                # Sin OCR: leer el texto que el stream pone directamente
                with stream.lock:
                    text = stream.code_text.upper()

            # Buscar códigos
            found = []
            for m in PSN_PATTERN.finditer(text):
                found.append((m.group(1), "psn"))
            for m in XBOX_PATTERN.finditer(text):
                found.append((m.group(1), "xbox"))

            for code, platform in found:
                if is_already_seen(code):
                    log.warning("⏭  SKIP   [%s] %s — ya visto antes", platform.upper(), code)
                    continue

                log.info("🔍 DETECT [%s] %s", platform.upper(), code)
                save_code(code, platform)

                result  = mock_redeem(code, platform)
                reward  = random.choice(REWARDS[platform])

                if result == "redeemed":
                    log.info("✅ CANJEADO → %s  |  Premio: %s", code, reward)
                    mark_redeemed(code, "redeemed")
                elif result == "already_taken":
                    log.warning("❌ YA CANJEADO por otro usuario → %s", code)
                    mark_redeemed(code, "already_taken")
                else:
                    log.error("⚠  ERROR al canjear → %s", code)
                    mark_redeemed(code, "failed")

            time.sleep(1 / fps)

    except KeyboardInterrupt:
        log.info("\nBot detenido por el usuario.")
    finally:
        stream.release()
        # Resumen final
        con = sqlite3.connect(DB_PATH)
        rows = con.execute("SELECT platform, status, COUNT(*) FROM codes GROUP BY platform, status").fetchall()
        con.close()
        if rows:
            log.info("\n── Resumen de la sesión ──────────────")
            for platform, status, count in rows:
                log.info("  %s | %-15s | %d código(s)", platform.upper(), status, count)
            log.info("─────────────────────────────────────")


if __name__ == "__main__":
    run_test()
