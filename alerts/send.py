"""SMTP sender. Soporta Gmail/Google Workspace via app password.

Variables de entorno requeridas:
    GMAIL_USER           - email del remitente
    GMAIL_APP_PASSWORD   - app password generado en Google Account
    ALERT_RECIPIENT      - email del destinatario (default: GMAIL_USER)

Tambien soporta un archivo .env en la raiz del proyecto.
"""
from __future__ import annotations

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path


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
    user = os.environ.get("GMAIL_USER")
    pw = os.environ.get("GMAIL_APP_PASSWORD")
    to = os.environ.get("ALERT_RECIPIENT") or user
    missing = []
    if not user:
        missing.append("GMAIL_USER")
    if not pw:
        missing.append("GMAIL_APP_PASSWORD")
    if missing:
        raise RuntimeError(
            "Faltan variables de entorno: " + ", ".join(missing) +
            ". Definilas via .env o env vars. Ver alerts/send.py docstring."
        )
    return {"user": user, "password": pw, "recipient": to}


def send_email(subject, html_body, recipient=None):
    cfg = _config()
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = "Radar Legislativo <" + cfg["user"] + ">"
    msg["To"] = recipient or cfg["recipient"]
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    plain = "Tu cliente de email no soporta HTML. Abri la version web."
    msg.attach(MIMEText(plain, "plain", "utf-8"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=20) as s:
        s.login(cfg["user"], cfg["password"])
        s.sendmail(cfg["user"], [msg["To"]], msg.as_string())
    return msg["To"]
