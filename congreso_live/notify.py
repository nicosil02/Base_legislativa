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
from urllib.request import Request, urlopen

import requests

log = logging.getLogger(__name__)


def acortar_url(url: str | None) -> str | None:
    """Acorta con TinyURL (gratis, sin API key). Bug real 2026-09-21
    (Nicolas: "las alertas de whatsapp a veces se mandan incompletas por
    los tamaños largos de los links"): las URLs de Google News (la fuente
    mas comun en noticias/digest.py) llegan a pesar 500-700+ caracteres -
    verificado en vivo, una sola de 581 caracteres. Con varias por
    mensaje, se comian buena parte de MENSAJE_MAX_CHARS y el resto del
    contenido se recortaba o se perdia.

    Probado en vivo 2026-09-21: is.gd/v.gd rechazan esta URL puntual
    ("database insert failed"), TinyURL la acorta sin problema
    (581 -> 26 caracteres). Fail-safe total: cualquier error (timeout,
    API caida, URL invalida) devuelve la URL ORIGINAL sin acortar - esto
    nunca debe romper el envio del mensaje."""
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
        # CallMeBot devuelve 200 incluso cuando rechaza (apikey invalida,
        # rate limit...) - el motivo viene en el HTML. Bug real 2026-09-24:
        # se logueaba "enviado" y a Nicolas no le llegaba nada.
        # El HTML repite el texto del mensaje primero; el estado real
        # (queued / error) viene al final - por eso la cola, no la cabeza.
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


# ============================================================
# self-check (Ponytail: 1 chequeo ejecutable de la logica no trivial)
# ============================================================

def _demo():
    from unittest.mock import patch

    # __name__ (no el string literal "congreso_live.notify") para que el
    # patch funcione tanto corrido como `python -m congreso_live.notify`
    # (donde este archivo se carga como __main__, un modulo distinto) como
    # importado normalmente - mismo gotcha en los dos casos.
    target = __name__ + ".urlopen"

    # URL corta: nunca dispara la red.
    with patch(target) as mock_urlopen:
        assert acortar_url("https://x.com/a") == "https://x.com/a"
        mock_urlopen.assert_not_called()

    # URL larga, TinyURL responde bien.
    larga = "https://news.google.com/rss/articles/" + "A" * 500
    respuesta_ok = type("R", (), {
        "__enter__": lambda s: s, "__exit__": lambda *a: None,
        "read": lambda s: b"https://tinyurl.com/abc123",
    })()
    with patch(target, return_value=respuesta_ok):
        assert acortar_url(larga) == "https://tinyurl.com/abc123"

    # Falla de red: nunca debe romper, devuelve la URL original.
    with patch(target, side_effect=TimeoutError("timeout")):
        assert acortar_url(larga) == larga

    print("OK notify: acortar_url acorta URLs largas, es fail-safe ante errores")


if __name__ == "__main__":
    _demo()
