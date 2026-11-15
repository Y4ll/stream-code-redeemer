# Stream Code Redeemer Bot 🎮

Bot que monitorea un stream en vivo, detecta códigos de canjeo con OCR y los canjea automáticamente en **PlayStation Network** y **Xbox**.

---

## ¿Cómo funciona?

```
Stream (Twitch/YouTube) → streamlink → frames → EasyOCR → Regex → ¿Ya canjeado? → Canjear PSN/Xbox
```

1. Captura frames del stream cada N segundos con `streamlink` + `OpenCV`
2. Aplica OCR con `EasyOCR` para leer el texto en pantalla
3. Busca patrones de código PSN (`XXXX-XXXX-XXXX`) y Xbox (`XXXXX-XXXXX-XXXXX-XXXXX-XXXXX`)
4. Verifica en SQLite si el código ya fue visto (evita duplicados)
5. Canjea automáticamente en la plataforma correspondiente

---

## Instalación

```bash
pip install -r requirements.txt
```

---

## Configuración

Copia `.env.example` a `.env` y rellena tus credenciales:

```bash
cp .env.example .env
```

| Variable | Descripción |
|----------|-------------|
| `PSN_NPSSO` | Cookie NPSSO de tu cuenta PSN |
| `XBOX_TOKEN` | Token XBL3.0 de tu cuenta Xbox |

### Obtener PSN_NPSSO
1. Inicia sesión en https://store.playstation.com
2. Ve a: https://ca.account.sony.com/api/v1/ssocookie
3. Copia el valor de `npsso`

### Obtener XBOX_TOKEN
Usa la librería [xbox-webapi-python](https://github.com/OpenXbox/xbox-webapi-python):
```bash
pip install xbox-webapi
xbox-authenticate
```

---

## Uso

```bash
# Desde variables de entorno (.env)
python bot.py https://www.twitch.tv/NOMBRE_DEL_CANAL

# Pasando credenciales directamente
python bot.py https://www.twitch.tv/NOMBRE_DEL_CANAL \
  --psn-npsso TU_NPSSO \
  --xbox-token TU_TOKEN

# Ajustar intervalo de captura (default: cada 5 segundos)
python bot.py https://www.twitch.tv/NOMBRE_DEL_CANAL --interval 3
```

---

## Base de datos

Los códigos detectados se guardan en `codes.db` (SQLite):

| Campo | Descripción |
|-------|-------------|
| `code` | El código detectado |
| `platform` | `psn` o `xbox` |
| `status` | `pending` / `redeemed` / `failed` / `no_credentials` |
| `detected_at` | Cuándo fue detectado |
| `redeemed_at` | Cuándo fue canjeado |

---

## Dependencias

- `easyocr` — OCR para extraer texto de los frames
- `opencv-python` — Captura y procesamiento de video
- `streamlink` — Obtiene la URL directa del stream
- `requests` — Llamadas a las APIs de PSN y Xbox

---

## ⚠️ Aviso

Este bot es para uso personal y educativo. Revisa los términos de servicio de cada plataforma antes de usarlo.
