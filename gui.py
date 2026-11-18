"""
Stream Code Redeemer — GUI
Interfaz gráfica con pywebview (WebKit2 / WebView2)
"""

import webview
import threading
import json
import re
import time
import random
import string
import sqlite3
import os
import sys
from datetime import datetime
from pathlib import Path

from sources import (
    find_codes, audio_loop, twitch_chat, youtube_chat,
    youtube_description, youtube_video_id, twitch_channel,
)

# ─── Base de datos ───────────────────────────────────────────────────────────
DB_PATH = Path("codes.db")

# El canje real contra PSN/Xbox está desactivado por defecto.
# Para activarlo: variable de entorno ENABLE_REAL_REDEEM=1
ENABLE_REAL_REDEEM = os.getenv("ENABLE_REAL_REDEEM") == "1"

def init_db():
    con = sqlite3.connect(DB_PATH)
    con.execute("""
        CREATE TABLE IF NOT EXISTS codes (
            code TEXT PRIMARY KEY,
            platform TEXT,
            status TEXT DEFAULT 'pending',
            detected_at TEXT,
            redeemed_at TEXT,
            reward TEXT
        )
    """)
    con.commit(); con.close()

def is_seen(code):
    con = sqlite3.connect(DB_PATH)
    r = con.execute("SELECT 1 FROM codes WHERE code=?", (code,)).fetchone()
    con.close()
    return r is not None

def save_code(code, platform, status="pending", reward=""):
    con = sqlite3.connect(DB_PATH)
    con.execute(
        "INSERT OR IGNORE INTO codes (code,platform,status,detected_at,reward) VALUES (?,?,?,?,?)",
        (code, platform, status, datetime.utcnow().isoformat(), reward),
    )
    con.commit(); con.close()

def mark_redeemed(code, status, reward=""):
    con = sqlite3.connect(DB_PATH)
    con.execute(
        "UPDATE codes SET status=?, redeemed_at=?, reward=? WHERE code=?",
        (status, datetime.utcnow().isoformat(), reward, code),
    )
    con.commit(); con.close()

def get_stats():
    con = sqlite3.connect(DB_PATH)
    total    = con.execute("SELECT COUNT(*) FROM codes").fetchone()[0]
    redeemed = con.execute("SELECT COUNT(*) FROM codes WHERE status='redeemed'").fetchone()[0]
    failed   = con.execute("SELECT COUNT(*) FROM codes WHERE status IN ('failed','already_taken')").fetchone()[0]
    skipped  = con.execute("SELECT COUNT(*) FROM codes WHERE status='skip'").fetchone()[0]
    con.close()
    return {"total": total, "redeemed": redeemed, "failed": failed, "skipped": skipped}

# ─── Helpers ─────────────────────────────────────────────────────────────────
PSN_PATTERN  = re.compile(r"\b([A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4})\b")
XBOX_PATTERN = re.compile(r"\b([A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{5})\b")

REWARDS = {
    "psn" : ["GT6 DLC Car Pack","PS Store $10 Credit","PS Plus 1 mes","Gran Turismo 7 Skin","Mortal Kombat DLC"],
    "xbox": ["500 Microsoft Points","Xbox Game Pass 7 días","Halo Infinite Bundle","Forza Horizon DLC","Xbox $5 Credit"],
}

def _rand(n): return "".join(random.choices(string.ascii_uppercase + string.digits, k=n))
def fake_psn():  return f"{_rand(4)}-{_rand(4)}-{_rand(4)}"
def fake_xbox(): return f"{_rand(5)}-{_rand(5)}-{_rand(5)}-{_rand(5)}-{_rand(5)}"

# ─── API expuesta al JS ───────────────────────────────────────────────────────
class BotAPI:
    def __init__(self):
        self._running   = False
        self._thread    = None
        self._window    = None
        self._logs      = []
        self._test_mode = False

    def set_window(self, window):
        self._window = window

    def _emit(self, event, data):
        """Llama a una función JS en la ventana."""
        if self._window:
            payload = json.dumps(data).replace("'", "\\'")
            self._window.evaluate_js(f"window.__bot_event('{event}', {payload})")

    def _log(self, level, message, code=None, platform=None):
        entry = {
            "time"    : datetime.now().strftime("%H:%M:%S"),
            "level"   : level,          # ok / warn / error / info
            "message" : message,
            "code"    : code,
            "platform": platform,
        }
        self._logs.append(entry)
        self._emit("log", entry)
        self._emit("stats", get_stats())

    # ── Métodos llamados desde JS ─────────────────────────────────────────────
    def start_bot(self, stream_url, psn_npsso, xbox_token, test_mode, opts=None):
        if self._running:
            return {"ok": False, "msg": "Ya está corriendo"}
        self._running   = True
        self._test_mode = test_mode
        self._opts      = opts or {}
        self._creds     = (psn_npsso, xbox_token)
        self._thread    = threading.Thread(
            target=self._run,
            args=(stream_url, psn_npsso, xbox_token, test_mode),
            daemon=True,
        )
        self._thread.start()
        self._emit("status", {"running": True})
        return {"ok": True}

    def stop_bot(self):
        self._running = False
        self._emit("status", {"running": False})
        return {"ok": True}

    def get_logs(self):
        return self._logs[-200:]

    def get_stats(self):
        return get_stats()

    def clear_db(self):
        con = sqlite3.connect(DB_PATH)
        con.execute("DELETE FROM codes")
        con.commit(); con.close()
        self._emit("stats", get_stats())
        return {"ok": True}

    # ── Loop principal ────────────────────────────────────────────────────────
    def _run(self, stream_url, psn_npsso, xbox_token, test_mode):
        init_db()
        self._log("info", "🚀 Bot iniciado" + (" (modo prueba)" if test_mode else ""))

        if test_mode:
            self._run_test()
        else:
            self._run_real(stream_url, psn_npsso, xbox_token)

        self._running = False
        self._emit("status", {"running": False})
        self._log("info", "⏹ Bot detenido")

    def _run_test(self):
        """Stream simulado con códigos falsos cada 6-10 s."""
        self._log("info", "📺 Stream falso conectado — códigos cada 6-10 s")
        next_code_at = time.time() + random.uniform(4, 8)

        while self._running:
            if time.time() >= next_code_at:
                platform = random.choice(["psn","psn","xbox"])
                code     = fake_psn() if platform == "psn" else fake_xbox()
                self._process_code(code, platform, mock=True)
                next_code_at = time.time() + random.uniform(6, 12)
            time.sleep(0.5)

    def _resolve_stream_url(self, stream_url):
        """Obtiene la URL directa de video. Soporta Twitch, YouTube y otros.
        Prueba streamlink primero y, si falla, yt-dlp (mejor soporte de YouTube)."""
        platform = "YouTube" if ("youtube.com" in stream_url or "youtu.be" in stream_url) else "Twitch/otro"
        self._log("info", f"🔗 Conectando a {platform}: {stream_url}")

        # 1) streamlink (API Python, funciona dentro del .exe)
        try:
            import streamlink
            streams = streamlink.Streamlink().streams(stream_url)
            if streams and "best" in streams:
                return streams["best"].to_url()
        except Exception as e:
            self._log("warn", f"streamlink no pudo resolver el stream: {e}")

        # 2) yt-dlp (API Python) — respaldo, mejor para YouTube
        try:
            import yt_dlp
            with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "format": "best"}) as ydl:
                info = ydl.extract_info(stream_url, download=False)
                url = info.get("url", "")
                if url.startswith("http"):
                    self._log("info", "ℹ️ URL obtenida con yt-dlp")
                    return url
        except Exception as e:
            self._log("warn", f"yt-dlp no pudo resolver el stream: {e}")

        return None

    def _start_sources(self, stream_url, media_url):
        """Lanza hilos para voz, chat y descripción según las opciones marcadas."""
        opts = self._opts
        psn, xbox = self._creds
        should_run = lambda: self._running

        def emit(text):
            for code, platform in find_codes(text):
                self._process_code(code, platform, psn_npsso=psn, xbox_token=xbox)

        def run(name, fn, *args):
            try:
                self._log("info", f"🎧 Fuente activa: {name}")
                fn(*args)
            except Exception as e:
                self._log("error", f"❌ {name}: {e}")

        def start(name, fn, *args):
            threading.Thread(target=run, args=(name, fn, *args), daemon=True).start()

        vid = youtube_video_id(stream_url)
        channel = twitch_channel(stream_url)
        ykey = opts.get("ytKey", "")

        if opts.get("voice"):
            start("voz (audio)", audio_loop, media_url, emit, should_run)
        if opts.get("chat"):
            if channel:
                start("chat de Twitch", twitch_chat, channel, emit, should_run)
            elif vid and ykey:
                start("chat de YouTube", youtube_chat, vid, ykey, emit, should_run)
            else:
                self._log("warn", "⚠ Chat: en YouTube necesitas API key")
        if opts.get("desc"):
            if vid and ykey:
                start("descripción de YouTube", youtube_description, vid, ykey, emit, should_run)
            else:
                self._log("warn", "⚠ Descripción: solo funciona con YouTube y API key")

    def _run_real(self, stream_url, psn_npsso, xbox_token):
        """Lee el stream real (Twitch o YouTube) con OpenCV + EasyOCR."""
        try:
            import cv2
            url = self._resolve_stream_url(stream_url)
            if not url:
                self._log("error", "❌ No se pudo obtener la URL del stream. ¿Está en vivo?")
                return
            cap = cv2.VideoCapture(url)
            if not cap.isOpened():
                self._log("error", "❌ No se pudo abrir el stream"); return
            self._log("info", "✅ Stream conectado")
            self._start_sources(stream_url, url)

            try:
                import easyocr
                reader = easyocr.Reader(["en"], gpu=False)
            except ImportError:
                self._log("error", "❌ easyocr no instalado"); cap.release(); return

            fps   = cap.get(cv2.CAP_PROP_FPS) or 30
            skip  = max(1, int(fps * 3))
            count = 0

            while self._running:
                ret, frame = cap.read()
                if not ret: break
                count += 1
                if count % skip != 0: continue
                small   = cv2.resize(frame, (1280, 720))
                results = reader.readtext(small, detail=0)
                text    = " ".join(results).upper()
                for m in PSN_PATTERN.finditer(text):
                    self._process_code(m.group(1), "psn", psn_npsso=psn_npsso)
                for m in XBOX_PATTERN.finditer(text):
                    self._process_code(m.group(1), "xbox", xbox_token=xbox_token)
            cap.release()
        except Exception as e:
            self._log("error", f"❌ Error: {e}")

    def _process_code(self, code, platform, mock=False, psn_npsso="", xbox_token=""):
        if is_seen(code):
            self._log("warn", f"⏭ Ya visto: {code}", code=code, platform=platform)
            return

        self._log("info", f"🔍 Detectado [{platform.upper()}]: {code}", code=code, platform=platform)
        save_code(code, platform)
        self._emit("code_detected", {"code": code, "platform": platform})

        if mock:
            time.sleep(0.4)
            r      = random.random()
            status = "redeemed" if r < 0.70 else ("already_taken" if r < 0.90 else "failed")
        elif not ENABLE_REAL_REDEEM:
            status = "dry_run"
        elif platform == "psn" and psn_npsso:
            status = self._redeem_psn(code, psn_npsso)
        elif platform == "xbox" and xbox_token:
            status = self._redeem_xbox(code, xbox_token)
        else:
            status = "no_credentials"

        reward = random.choice(REWARDS[platform]) if status == "redeemed" else ""
        mark_redeemed(code, status, reward)

        if status == "redeemed":
            self._log("ok", f"✅ Canjeado: {code}  →  {reward}", code=code, platform=platform)
        elif status == "already_taken":
            self._log("error", f"❌ Ya canjeado por otro: {code}", code=code, platform=platform)
        elif status == "dry_run":
            self._log("warn", f"🧪 Detectado, canje real desactivado: {code}", code=code, platform=platform)
        elif status == "no_credentials":
            self._log("warn", f"⚠ Sin credenciales para {platform.upper()}", code=code, platform=platform)
        else:
            self._log("error", f"⚠ Error al canjear: {code}", code=code, platform=platform)

    def _redeem_psn(self, code, npsso):
        try:
            import requests
            r = requests.post(
                "https://ca.account.sony.com/api/authz/v3/oauth/token",
                headers={"Content-Type":"application/x-www-form-urlencoded"},
                data={"grant_type":"sso_access_token","npsso":npsso,
                      "scope":"psn:clientapp","client_id":"09515159-7237-4370-9b40-3806e67c0891",
                      "client_secret":"ucybISFppITC"},
                timeout=15,
            )
            token = r.json().get("access_token","")
            r2 = requests.post(
                "https://store.playstation.com/store/api/11/en/US/product/UP0001-CUSA00000_00-0000000000000000/gift_code/redeem",
                headers={"Authorization":f"Bearer {token}","Content-Type":"application/json"},
                json={"code": code}, timeout=15,
            )
            return "redeemed" if r2.status_code == 200 else "failed"
        except: return "failed"

    def _redeem_xbox(self, code, token):
        try:
            import requests
            r = requests.post(
                "https://redeem.microsoft.com/api/redeem",
                headers={"Authorization":f"XBL3.0 x=userhash;{token}","Content-Type":"application/json"},
                json={"code": code, "market": "US"}, timeout=15,
            )
            return "redeemed" if r.status_code in (200,201) else "failed"
        except: return "failed"


# ─── HTML de la interfaz ──────────────────────────────────────────────────────
HTML = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Stream Code Redeemer</title>
<style>
  :root {
    --bg:      #0a0a14;
    --panel:   #12121f;
    --border:  #1e1e35;
    --accent:  #7c6af7;
    --psn:     #0070cc;
    --xbox:    #107c10;
    --ok:      #22c55e;
    --warn:    #f59e0b;
    --err:     #ef4444;
    --text:    #e2e8f0;
    --muted:   #64748b;
    --radius:  10px;
  }
  * { margin:0; padding:0; box-sizing:border-box; }
  body { background:var(--bg); color:var(--text); font-family:'Segoe UI',system-ui,sans-serif; height:100vh; display:flex; flex-direction:column; overflow:hidden; }

  /* ── Header ── */
  header { background:var(--panel); border-bottom:1px solid var(--border); padding:12px 20px; display:flex; align-items:center; gap:12px; }
  header .logo { font-size:20px; font-weight:700; color:var(--accent); }
  header .dot  { width:10px; height:10px; border-radius:50%; background:var(--err); margin-left:auto; transition:.3s; }
  header .dot.live { background:var(--ok); box-shadow:0 0 8px var(--ok); animation:pulse 2s infinite; }
  @keyframes pulse { 50%{ opacity:.5; } }
  header .status-text { font-size:13px; color:var(--muted); }

  /* ── Layout ── */
  .main { display:flex; flex:1; overflow:hidden; gap:0; }
  .sidebar { width:280px; min-width:280px; background:var(--panel); border-right:1px solid var(--border); display:flex; flex-direction:column; gap:0; overflow-y:auto; }
  .content { flex:1; display:flex; flex-direction:column; overflow:hidden; }

  /* ── Sidebar sections ── */
  .section { padding:16px; border-bottom:1px solid var(--border); }
  .section h3 { font-size:11px; font-weight:600; color:var(--muted); text-transform:uppercase; letter-spacing:.8px; margin-bottom:12px; }

  label  { display:block; font-size:12px; color:var(--muted); margin-bottom:4px; margin-top:10px; }
  label:first-of-type { margin-top:0; }
  input  { width:100%; background:#0d0d1a; border:1px solid var(--border); border-radius:6px; padding:8px 10px; color:var(--text); font-size:13px; outline:none; transition:.2s; }
  input:focus { border-color:var(--accent); }
  input[type=checkbox] { width:auto; }

  .toggle-row { display:flex; align-items:center; gap:8px; margin-top:12px; font-size:13px; }

  /* ── Buttons ── */
  .btn { width:100%; padding:10px; border-radius:var(--radius); border:none; font-size:14px; font-weight:600; cursor:pointer; transition:.2s; margin-top:12px; }
  .btn-start { background:var(--accent); color:#fff; }
  .btn-start:hover { background:#6b5ce7; }
  .btn-stop  { background:var(--err); color:#fff; }
  .btn-stop:hover { opacity:.85; }
  .btn:disabled { opacity:.4; cursor:not-allowed; }

  .btn-sm { width:auto; padding:5px 12px; font-size:12px; border-radius:6px; border:1px solid var(--border); background:transparent; color:var(--muted); cursor:pointer; }
  .btn-sm:hover { border-color:var(--accent); color:var(--accent); }

  /* ── Stats ── */
  .stats-grid { display:grid; grid-template-columns:1fr 1fr; gap:8px; }
  .stat-card  { background:#0d0d1a; border:1px solid var(--border); border-radius:8px; padding:10px 12px; }
  .stat-card .num  { font-size:22px; font-weight:700; }
  .stat-card .lbl  { font-size:11px; color:var(--muted); margin-top:2px; }
  .stat-card.ok   .num { color:var(--ok); }
  .stat-card.err  .num { color:var(--err); }
  .stat-card.warn .num { color:var(--warn); }
  .stat-card.info .num { color:var(--accent); }

  /* ── Log ── */
  .log-header { padding:12px 16px; border-bottom:1px solid var(--border); display:flex; align-items:center; justify-content:space-between; }
  .log-header h3 { font-size:12px; font-weight:600; color:var(--muted); text-transform:uppercase; letter-spacing:.8px; }
  #log-box { flex:1; overflow-y:auto; padding:10px 14px; font-family:'Consolas','Courier New',monospace; font-size:12.5px; line-height:1.75; }
  .log-entry { display:flex; gap:10px; align-items:flex-start; padding:3px 0; border-bottom:1px solid #111; }
  .log-entry:last-child { border:none; }
  .log-time { color:var(--muted); flex-shrink:0; font-size:11px; padding-top:2px; }
  .log-msg  { flex:1; }
  .log-ok   .log-msg { color:var(--ok); }
  .log-warn .log-msg { color:var(--warn); }
  .log-error .log-msg { color:var(--err); }
  .log-info .log-msg { color:#94a3b8; }

  .badge { display:inline-block; padding:1px 7px; border-radius:4px; font-size:10px; font-weight:700; vertical-align:middle; margin-right:5px; }
  .badge-psn  { background:var(--psn); color:#fff; }
  .badge-xbox { background:var(--xbox); color:#fff; }

  /* ── Scrollbar ── */
  ::-webkit-scrollbar { width:4px; } ::-webkit-scrollbar-track { background:#0a0a14; } ::-webkit-scrollbar-thumb { background:#1e1e35; border-radius:2px; }
</style>
</head>
<body>

<header>
  <span class="logo">🎮 Stream Code Redeemer</span>
  <span class="status-text" id="status-text">Detenido</span>
  <div class="dot" id="dot"></div>
</header>

<div class="main">
  <!-- Sidebar -->
  <aside class="sidebar">

    <div class="section">
      <h3>Stream</h3>
      <label>URL del canal</label>
      <input id="url" type="text" placeholder="Twitch o YouTube: https://www.youtube.com/watch?v=..." />

      <div class="toggle-row">
        <input type="checkbox" id="test-mode" checked>
        <label style="margin:0">Modo prueba (sin stream real)</label>
      </div>

      <h3 style="margin-top:14px">Fuentes (stream real)</h3>
      <div class="toggle-row"><input type="checkbox" id="src-voice" checked><label style="margin:0">Voz (audio)</label></div>
      <div class="toggle-row"><input type="checkbox" id="src-chat" checked><label style="margin:0">Chat</label></div>
      <div class="toggle-row"><input type="checkbox" id="src-desc" checked><label style="margin:0">Descripción (YouTube)</label></div>
      <label>YouTube API key (chat y descripción de YouTube)</label>
      <input id="yt-key" type="password" placeholder="AIza..." />
    </div>

    <div class="section">
      <h3>Credenciales</h3>
      <label>PSN — Cookie NPSSO</label>
      <input id="npsso" type="password" placeholder="Pega tu NPSSO aquí" />
      <label>Xbox — Token XBL3.0</label>
      <input id="xbox-token" type="password" placeholder="Pega tu token Xbox aquí" />
    </div>

    <div class="section">
      <button class="btn btn-start" id="btn-start" onclick="startBot()">▶ Iniciar Bot</button>
      <button class="btn btn-stop"  id="btn-stop"  onclick="stopBot()" disabled>⏹ Detener</button>
    </div>

    <div class="section">
      <h3>Estadísticas</h3>
      <div class="stats-grid">
        <div class="stat-card info">  <div class="num" id="s-total">0</div>    <div class="lbl">Detectados</div></div>
        <div class="stat-card ok">    <div class="num" id="s-redeemed">0</div> <div class="lbl">Canjeados</div></div>
        <div class="stat-card err">   <div class="num" id="s-failed">0</div>   <div class="lbl">Fallidos</div></div>
        <div class="stat-card warn">  <div class="num" id="s-skipped">0</div>  <div class="lbl">Ignorados</div></div>
      </div>
    </div>

  </aside>

  <!-- Log -->
  <div class="content">
    <div class="log-header">
      <h3>Registro en vivo</h3>
      <button class="btn-sm" onclick="clearLog()">Limpiar</button>
    </div>
    <div id="log-box">
      <div class="log-entry log-info">
        <span class="log-time">--:--:--</span>
        <span class="log-msg">Listo. Presiona ▶ Iniciar Bot para comenzar.</span>
      </div>
    </div>
  </div>
</div>

<script>
  // ── Eventos desde Python ──────────────────────────────────────────────────
  window.__bot_event = function(event, data) {
    if (event === 'log')    addLog(data);
    if (event === 'stats')  updateStats(data);
    if (event === 'status') setRunning(data.running);
    if (event === 'code_detected') flashCode(data);
  };

  function addLog(e) {
    const box  = document.getElementById('log-box');
    const div  = document.createElement('div');
    div.className = 'log-entry log-' + e.level;
    const badge = e.platform ? `<span class="badge badge-${e.platform}">${e.platform.toUpperCase()}</span>` : '';
    div.innerHTML = `<span class="log-time">${e.time}</span><span class="log-msg">${badge}${e.message}</span>`;
    box.appendChild(div);
    box.scrollTop = box.scrollHeight;
  }

  function updateStats(s) {
    document.getElementById('s-total').textContent    = s.total;
    document.getElementById('s-redeemed').textContent = s.redeemed;
    document.getElementById('s-failed').textContent   = s.failed;
    document.getElementById('s-skipped').textContent  = s.skipped;
  }

  function setRunning(running) {
    document.getElementById('dot').classList.toggle('live', running);
    document.getElementById('status-text').textContent = running ? 'En vivo' : 'Detenido';
    document.getElementById('btn-start').disabled = running;
    document.getElementById('btn-stop').disabled  = !running;
  }

  function flashCode(data) {
    const box = document.getElementById('log-box');
    box.scrollTop = box.scrollHeight;
  }

  function clearLog() {
    document.getElementById('log-box').innerHTML = '';
  }

  // ── Acciones del usuario ──────────────────────────────────────────────────
  async function startBot() {
    const url   = document.getElementById('url').value.trim();
    const npsso = document.getElementById('npsso').value.trim();
    const xbox  = document.getElementById('xbox-token').value.trim();
    const test  = document.getElementById('test-mode').checked;
    if (!test && !url) { alert('Ingresa la URL del stream.'); return; }
    const opts = {
      voice: document.getElementById('src-voice').checked,
      chat:  document.getElementById('src-chat').checked,
      desc:  document.getElementById('src-desc').checked,
      ytKey: document.getElementById('yt-key').value.trim(),
    };
    await pywebview.api.start_bot(url, npsso, xbox, test, opts);
  }

  async function stopBot() {
    await pywebview.api.stop_bot();
  }

  // Cargar stats al iniciar
  window.addEventListener('pywebviewready', async () => {
    const s = await pywebview.api.get_stats();
    updateStats(s);
    const logs = await pywebview.api.get_logs();
    logs.forEach(addLog);
  });
</script>
</body>
</html>
"""

# ─── Lanzar app ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    init_db()
    api    = BotAPI()
    window = webview.create_window(
        title      = "Stream Code Redeemer",
        html       = HTML,
        js_api     = api,
        width      = 980,
        height     = 640,
        min_size   = (800, 500),
        background_color = "#0a0a14",
    )
    api.set_window(window)
    webview.start(debug=False)
