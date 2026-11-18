"""
Fuentes adicionales de texto para detectar códigos:
  - audio del stream (voz, transcrita con faster-whisper)
  - chat de Twitch (IRC anónimo, solo lectura)
  - chat de YouTube (YouTube Data API v3, requiere API key tuya)
  - descripción de un video de YouTube (YouTube Data API v3)

Todas las funciones reciben `on_text(str)` y `should_run() -> bool`.
Las dependencias pesadas (av, faster_whisper, requests) se importan dentro de cada función.
"""

import random
import re
import socket
import time
from urllib.parse import urlparse, parse_qs

PSN_PATTERN  = re.compile(r"\b([A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4})\b")
XBOX_PATTERN = re.compile(r"\b([A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{5})\b")


def find_codes(text):
    """Devuelve lista de (código, plataforma) encontrados en el texto."""
    text = text.upper()
    found = [(m.group(1), "psn") for m in PSN_PATTERN.finditer(text)]
    found += [(m.group(1), "xbox") for m in XBOX_PATTERN.finditer(text)]
    return found


def youtube_video_id(url):
    p = urlparse(url)
    if p.netloc.endswith("youtu.be"):
        return p.path.lstrip("/")
    if "youtube.com" in p.netloc:
        if p.path.startswith("/live/"):
            return p.path.split("/")[2]
        return parse_qs(p.query).get("v", [""])[0]
    return ""


def twitch_channel(url):
    p = urlparse(url)
    if "twitch.tv" in p.netloc:
        return p.path.strip("/").split("/")[0]
    return ""


def _sleep_while(seconds, should_run):
    end = time.time() + seconds
    while should_run() and time.time() < end:
        time.sleep(0.5)


# ─── Audio (voz) ─────────────────────────────────────────────────────────────
def audio_loop(media_url, on_text, should_run, chunk_s=20):
    """Decodifica el audio del stream y transcribe cada `chunk_s` segundos."""
    import av
    import numpy as np
    from faster_whisper import WhisperModel

    model = WhisperModel("tiny", device="cpu", compute_type="int8")
    container = av.open(media_url)
    stream = next(s for s in container.streams if s.type == "audio")
    resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)

    buf, n, target = [], 0, chunk_s * 16000
    for frame in container.decode(stream):
        if not should_run():
            break
        out = resampler.resample(frame)
        frames = out if isinstance(out, list) else ([out] if out else [])
        for f in frames:
            arr = f.to_ndarray().reshape(-1).astype(np.float32) / 32768.0
            buf.append(arr)
            n += arr.size
        if n >= target:
            audio = np.concatenate(buf)
            buf, n = [], 0
            segments, _ = model.transcribe(audio, beam_size=1)
            on_text(" ".join(s.text for s in segments))
    container.close()


# ─── Chat de Twitch (IRC anónimo, solo lectura) ─────────────────────────────
def twitch_chat(channel, on_text, should_run):
    s = socket.create_connection(("irc.chat.twitch.tv", 6667), timeout=30)
    s.sendall(b"NICK justinfan%d\r\n" % random.randint(10000, 99999))
    s.sendall(f"JOIN #{channel.lower()}\r\n".encode())
    buf = b""
    try:
        while should_run():
            try:
                data = s.recv(4096)
            except socket.timeout:
                continue
            if not data:
                break
            buf += data
            while b"\r\n" in buf:
                line, buf = buf.split(b"\r\n", 1)
                text = line.decode("utf-8", "ignore")
                if text.startswith("PING"):
                    s.sendall(b"PONG :tmi.twitch.tv\r\n")
                elif " PRIVMSG " in text:
                    on_text(text.split(" :", 1)[-1])
    finally:
        s.close()


# ─── YouTube (Data API v3) ──────────────────────────────────────────────────
def _yt_get(path, params, api_key):
    import requests
    r = requests.get(
        f"https://www.googleapis.com/youtube/v3/{path}",
        params={**params, "key": api_key},
        timeout=15,
    )
    r.raise_for_status()
    return r.json()


def youtube_chat(video_id, api_key, on_text, should_run):
    items = _yt_get("videos", {"part": "liveStreamingDetails", "id": video_id}, api_key)["items"]
    chat_id = items[0]["liveStreamingDetails"]["activeLiveChatId"]
    token = None
    while should_run():
        params = {"part": "snippet", "liveChatId": chat_id}
        if token:
            params["pageToken"] = token
        d = _yt_get("liveChat/messages", params, api_key)
        for it in d.get("items", []):
            on_text(it["snippet"].get("displayMessage", ""))
        token = d.get("nextPageToken")
        _sleep_while(max(d.get("pollingIntervalMillis", 5000) / 1000, 2), should_run)


def youtube_description(video_id, api_key, on_text, should_run):
    last = None
    while should_run():
        d = _yt_get("videos", {"part": "snippet", "id": video_id}, api_key)
        desc = d["items"][0]["snippet"]["description"]
        if desc != last:
            on_text(desc)
            last = desc
        _sleep_while(60, should_run)
