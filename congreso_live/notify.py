"""Envio de notificaciones por WhatsApp.

Fase 0 usa CallMeBot (gratis, uso personal): mandas un WhatsApp a su numero,
te da una API key, y se envia con un simple GET. Sin infra.
  Setup: https://www.callmebot.com/blog/free-api-whatsapp-messages/
  Secrets (env): CALLMEBOT_PHONE (ej +51999...), CALLMEBOT_APIKEY

Si no hay credenciales, loguea el mensaje y devuelve False (no rompe el sync).
ponytail: CallMeBot alcanza para alertas personales. Para equipo/volumen,
cambiar a Twilio WhatsApp aqui mismo (misma firma).
"""
from __future__ import annotations

import logging
import os
from urllib.parse import quote

import requests

log = logging.getLogger(__name__)


def enviar_whatsapp(mensaje: str) -> bool:
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
        log.info("[notify] WhatsApp enviado (%d chars)", len(mensaje))
        return True
    except Exception as e:
        log.warning("[notify] fallo envio WhatsApp: %s", e)
        return False
