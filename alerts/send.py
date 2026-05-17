"""Email sender via Resend API (https://resend.com).

Resend es un servicio transaccional moderno con free tier de 3000 emails/mes
y 100/dia. NO requiere SMTP ni acceso a Google Workspace admin.

Variables de entorno requeridas:
    RESEND_API_KEY    - API key (re_XXXXX), generada en https://resend.com/api-keys
    ALERT_RECIPIENT   - email del destinatario

Variables de entorno opcionales:
    RESEND_FROM       - direccion remitente. Por default usa el
                        onboarding@resend.dev de Resend (no necesita
                        verificacion de dominio). Para mandar desde
                        @valiconsultores.com hace falta verificar el
                        dominio en Resend con DNS records.

Tambien soporta un archivo .env en la raiz del proyecto.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path


API_URL = "https://api.resend.com/emails"
DEFAULT_FROM = "Radar Legislativo <onboarding@resend.dev>"


def _load_dotenv(path):
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip(chr(34)).strip(chr(39))
        if key and key not in os.environ:
            os.environ[key] = val


def _config():
    repo_root = Path(__file__).resolve().parent.parent
    _load_dotenv(repo_root / ".env")
    api_key = os.environ.get("RESEND_API_KEY")
    to = os.environ.get("ALERT_RECIPIENT")
    sender = os.environ.get("RESEND_FROM") or DEFAULT_FROM
    missing = []
    if not api_key:
        missing.append("RESEND_API_KEY")
    if not to:
        missing.append("ALERT_RECIPIENT")
    if missing:
        raise RuntimeError(
            "Faltan variables de entorno: " + ", ".join(missing) +
            ". Definilas via .env o env vars. Ver alerts/send.py docstring."
        )
    return {"api_key": api_key, "recipient": to, "sender": sender}


def send_email(subject, html_body, recipient=None):
    cfg = _config()
    payload = {
        "from": cfg["sender"],
        "to": [recipient or cfg["recipient"]],
        "subject": subject,
        "html": html_body,
    }
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        API_URL,
        data=body,
        method="POST",
        headers={
            "Authorization": "Bearer " + cfg["api_key"],
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            resp_body = resp.read().decode("utf-8", errors="replace")
            data = json.loads(resp_body) if resp_body else {}
            email_id = data.get("id", "?")
            print("[resend] enviado id=" + email_id)
            return payload["to"][0]
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            "Resend HTTP " + str(e.code) + ": " + err_body[:500]
        ) from None
