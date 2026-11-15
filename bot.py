"""
Stream Code Redeemer Bot
Detecta códigos de canjeo en streams en vivo y los canjea automáticamente
Soporta: PlayStation Network (PSN) y Xbox
"""

import re
import time
import logging
import sqlite3
import subprocess
import tempfile
import os
from pathlib import Path
from datetime import datetime

import cv2
import easyocr
import requests

# ─── Configuración de logging ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot.log"),
    ],
)
log = logging.getLogger(__name__)

# ─── Patrones de códigos ────────────────────────────────────────────────────
PSN_PATTERN  = re.compile(r"\b([A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4})\b")
XBOX_PATTERN = re.compile(r"\b([A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{5})\b")

# ─── Base de datos ──────────────────────────────────────────────────────────
DB_PATH = Path("codes.db")

def init_db():
    con = sqlite3.connect(DB_PATH)
    con.execute("""
        CREATE TABLE IF NOT EXISTS codes (
            code        TEXT PRIMARY KEY,
            platform    TEXT,
            status      TEXT DEFAULT 'pending',
            detected_at TEXT,
            redeemed_at TEXT
        )
    """)
    con.commit()
    con.close()
    log.info("Base de datos inicializada: %s", DB_PATH)

def is_already_seen(code: str) -> bool:
    con = sqlite3.connect(DB_PATH)
    row = con.execute("SELECT 1 FROM codes WHERE code = ?", (code,)).fetchone()
    con.close()
    return row is not None

def save_code(code: str, platform: str, status: str = "pending"):
    con = sqlite3.connect(DB_PATH)
    con.execute(
        "INSERT OR IGNORE INTO codes (code, platform, status, detected_at) VALUES (?, ?, ?, ?)",
        (code, platform, status, datetime.utcnow().isoformat()),
    )
    con.commit()
    con.close()

def mark_redeemed(code: str, status: str):
    con = sqlite3.connect(DB_PATH)
    con.execute(
        "UPDATE codes SET status = ?, redeemed_at = ? WHERE code = ?",
        (status, datetime.utcnow().isoformat(), code),
    )
    con.commit()
    con.close()

# ─── OCR ────────────────────────────────────────────────────────────────────
reader = None  # inicializado perezosamente para ahorrar memoria

def get_reader():
    global reader
    if reader is None:
        log.info("Cargando modelo OCR (primera vez, puede tardar)…")
        reader = easyocr.Reader(["en"], gpu=False)
    return reader

def extract_text_from_frame(frame) -> str:
    result = get_reader().readtext(frame, detail=0)
    return " ".join(result).upper()

def find_codes(text: str) -> list[tuple[str, str]]:
    """Devuelve lista de (código, plataforma)."""
    found = []
    for m in PSN_PATTERN.finditer(text):
        found.append((m.group(1), "psn"))
    for m in XBOX_PATTERN.finditer(text):
        found.append((m.group(1), "xbox"))
    return found

# ─── Canjeo PSN (web scraping / API no oficial) ─────────────────────────────
def redeem_psn(code: str, npsso: str) -> bool:
    """
    Canjea un código en PSN usando la cookie NPSSO.
    Obtén tu NPSSO desde: https://ca.account.sony.com/api/v1/ssocookie
    (con sesión activa en el navegador)
    """
    try:
        # Paso 1: obtener access token
        auth_url = "https://ca.account.sony.com/api/authz/v3/oauth/token"
        headers  = {"Content-Type": "application/x-www-form-urlencoded"}
        data = {
            "grant_type"   : "sso_access_token",
            "npsso"        : npsso,
            "scope"        : "psn:clientapp",
            "client_id"    : "09515159-7237-4370-9b40-3806e67c0891",
            "client_secret": "ucybISFppITC",
        }
        r = requests.post(auth_url, headers=headers, data=data, timeout=15)
        r.raise_for_status()
        access_token = r.json()["access_token"]

        # Paso 2: canjear código
        redeem_url = "https://store.playstation.com/store/api/11/en/US/product/UP0001-CUSA00000_00-0000000000000000/gift_code/redeem"
        headers2 = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type" : "application/json",
        }
        payload = {"code": code}
        r2 = requests.post(redeem_url, headers=headers2, json=payload, timeout=15)
        if r2.status_code == 200:
            log.info("[PSN] ✅ Código canjeado: %s", code)
            return True
        else:
            log.warning("[PSN] ❌ Error %s al canjear %s: %s", r2.status_code, code, r2.text)
            return False
    except Exception as e:
        log.error("[PSN] Excepción al canjear %s: %s", code, e)
        return False

# ─── Canjeo Xbox ─────────────────────────────────────────────────────────────
def redeem_xbox(code: str, xbl_token: str) -> bool:
    """
    Canjea un código en Xbox usando un token XBL3.0.
    Puedes obtenerlo con la librería `xbox-webapi-python`.
    """
    try:
        url     = "https://redeem.microsoft.com/api/redeem"
        headers = {
            "Authorization": f"XBL3.0 x=userhash;{xbl_token}",
            "Content-Type" : "application/json",
        }
        payload = {"code": code, "market": "US"}
        r = requests.post(url, headers=headers, json=payload, timeout=15)
        if r.status_code in (200, 201):
            log.info("[XBOX] ✅ Código canjeado: %s", code)
            return True
        else:
            log.warning("[XBOX] ❌ Error %s al canjear %s: %s", r.status_code, code, r.text)
            return False
    except Exception as e:
        log.error("[XBOX] Excepción al canjear %s: %s", code, e)
        return False

# ─── Captura del stream ──────────────────────────────────────────────────────
def get_stream_url(channel_url: str) -> str | None:
    """Usa streamlink para obtener la URL directa del stream."""
    try:
        result = subprocess.run(
            ["streamlink", "--stream-url", channel_url, "best"],
            capture_output=True, text=True, timeout=20,
        )
        url = result.stdout.strip()
        if url.startswith("http"):
            return url
        log.error("streamlink no devolvió URL: %s", result.stderr)
        return None
    except FileNotFoundError:
        log.error("streamlink no está instalado. Instálalo con: pip install streamlink")
        return None

def process_stream(stream_url: str, interval: float, psn_npsso: str, xbox_token: str):
    """Captura frames del stream, extrae texto y canjea códigos."""
    log.info("Abriendo stream: %s", stream_url)
    cap = cv2.VideoCapture(stream_url)
    if not cap.isOpened():
        log.error("No se pudo abrir el stream.")
        return

    frame_count = 0
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    skip = max(1, int(fps * interval))  # cada `interval` segundos

    while True:
        ret, frame = cap.read()
        if not ret:
            log.warning("Stream terminado o sin señal.")
            break

        frame_count += 1
        if frame_count % skip != 0:
            continue

        # Escalar para acelerar OCR
        small = cv2.resize(frame, (1280, 720))
        text  = extract_text_from_frame(small)

        codes = find_codes(text)
        for code, platform in codes:
            if is_already_seen(code):
                continue

            log.info("🔍 Código detectado [%s]: %s", platform.upper(), code)
            save_code(code, platform)

            if platform == "psn" and psn_npsso:
                ok = redeem_psn(code, psn_npsso)
                mark_redeemed(code, "redeemed" if ok else "failed")
            elif platform == "xbox" and xbox_token:
                ok = redeem_xbox(code, xbox_token)
                mark_redeemed(code, "redeemed" if ok else "failed")
            else:
                log.warning("No hay credenciales para plataforma: %s", platform)
                mark_redeemed(code, "no_credentials")

    cap.release()

# ─── Punto de entrada ────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Stream Code Redeemer Bot")
    parser.add_argument("stream_url", help="URL del canal (ej: https://www.twitch.tv/canal)")
    parser.add_argument("--interval", type=float, default=5.0,
                        help="Segundos entre capturas de frame (default: 5)")
    parser.add_argument("--psn-npsso",  default=os.getenv("PSN_NPSSO",  ""),
                        help="Cookie NPSSO de PSN (o usa la variable PSN_NPSSO)")
    parser.add_argument("--xbox-token", default=os.getenv("XBOX_TOKEN", ""),
                        help="Token XBL3.0 de Xbox (o usa la variable XBOX_TOKEN)")
    args = parser.parse_args()

    init_db()

    stream_url = get_stream_url(args.stream_url)
    if not stream_url:
        log.error("No se pudo obtener la URL del stream.")
        raise SystemExit(1)

    process_stream(
        stream_url  = stream_url,
        interval    = args.interval,
        psn_npsso   = args.psn_npsso,
        xbox_token  = args.xbox_token,
    )
