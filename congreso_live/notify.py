"""Envio de avisos: Telegram si esta configurado, CallMeBot (WhatsApp) de respaldo.

Env: TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID, o CALLMEBOT_PHONE + CALLMEBOT_APIKEY.
Sin credenciales loguea el mensaje y devuelve False (no rompe el sync).
ponytail: CallMeBot alcanza para alertas personales. Para equipo/volumen,
cambiar a Twilio WhatsApp aqui mismo (misma firma).
"""
from __future__ import annotations

import json
import logging
import os
from urllib.parse import quote
from urllib.request import Request, urlopen

import requests

log = logging.getLogger(__name__)


def acortar_url(url: str | None) -> str | None:
    """Acorta con TinyURL (las URLs de Google News pesan 500+ caracteres y
    se comen el largo del mensaje). is.gd/v.gd rechazan algunas. Ante
    cualquier error devuelve la URL original: nunca debe romper el envio."""
    if not url or len(url) < 40:
        return url  # ya es corta, no vale el round-trip de red
    try:
        req = Request(
            "https://tinyurl.com/api-create.php?url=" + quote(url, safe=""),
            headers={"User-Agent": "Mozilla/5.0 (radar-legislativo)"},
        )
        with urlopen(req, timeout=8) as resp:
            corta = resp.read().decode().strip()
        if corta.startswith("https://tinyurl.com/"):
            return corta
        log.warning("[notify] acortar_url respuesta inesperada: %s", corta[:100])
    except Exception as e:
        log.warning("[notify] acortar_url fallo para %s...: %s", url[:60], e)
    return url


def enviar_telegram(mensaje: str, token: str, chat_id: str) -> bool:
    """Telegram Bot API (gratis y sin cupo). Usa Markdown legacy (entiende
    la *negrita* de WhatsApp); si un `_` o `*` suelto rompe el parser, se
    reintenta en texto plano."""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for parse_mode in ("Markdown", None):
        data = {"chat_id": chat_id, "text": mensaje[:4096],
                "disable_web_page_preview": True}
        if parse_mode:
            data["parse_mode"] = parse_mode
        try:
            r = requests.post(url, data=data, timeout=20)
            if r.ok:
                log.info("[notify] Telegram enviado (%d chars)", len(mensaje))
                return True
            log.warning("[notify] Telegram rechazo (%s): %s", parse_mode, r.text[:200])
        except Exception as e:
            log.warning("[notify] fallo envio Telegram: %s", e)
            return False
    return False


def enviar_whatsapp(mensaje: str) -> bool:
    # El texto completo queda en el log de Actions como respaldo si el envio falla.
    log.info("[notify] ALERTA_TXT %s", json.dumps(mensaje, ensure_ascii=False))
    # Nombre historico: todos los callers llaman enviar_whatsapp. Si hay
    # Telegram configurado va por ahi; CallMeBot queda como respaldo.
    tg_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    tg_chat = os.environ.get("TELEGRAM_CHAT_ID")
    if tg_token and tg_chat:
        return enviar_telegram(mensaje, tg_token, tg_chat)
    phone = os.environ.get("CALLMEBOT_PHONE")
    apikey = os.environ.get("CALLMEBOT_APIKEY")
    if not phone or not apikey:
        log.warning("[notify] sin CALLMEBOT_PHONE/APIKEY; mensaje no enviado:\n%s",
                    mensaje)
        return False
    url = (f"https://api.callmebot.com/whatsapp.php?phone={quote(phone)}"
           f"&text={quote(mensaje)}&apikey={quote(apikey)}")
    try:
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        # CallMeBot devuelve 200 aunque rechace; el estado real viene al
        # final del HTML (al principio repite el mensaje).
        cuerpo = " ".join(r.text.split())[-300:]
        if "error" in cuerpo.lower() or "invalid" in cuerpo.lower():
            log.warning("[notify] CallMeBot rechazo el WhatsApp: %s", cuerpo)
            return False
        log.info("[notify] WhatsApp enviado (%d chars) - CallMeBot: %s",
                 len(mensaje), cuerpo)
        return True
    except Exception as e:
        log.warning("[notify] fallo envio WhatsApp: %s", e)
        return False
