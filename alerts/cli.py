"""Entry point del sistema de alertas.

Uso:
    python -m alerts.cli send                 # envio normal (decide 9/10 AM)
    python -m alerts.cli send --slot 09       # marca como run 9 AM
    python -m alerts.cli send --slot 10       # marca como run 10 AM (retry)
    python -m alerts.cli send --dry-run       # imprime HTML, no envia
    python -m alerts.cli send --force         # envia aunque ya se haya enviado hoy

Logica del scheduling diario:
  - 9 AM (slot 09):
      * Si hay contenido nuevo -> envia + marca sent hoy.
      * Si no hay contenido    -> skip, no marca.
  - 10 AM (slot 10):
      * Si ya se envio hoy -> skip.
      * Si no se envio hoy -> envia (aunque este vacio) + marca.

Estado persistido en data/alert_sent_log.json (commiteado).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = REPO_ROOT / "data" / "alert_sent_log.json"


def _today_str():
    return datetime.utcnow().date().isoformat()


def _load_state():
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def cmd_send(args):
    from alerts.build import build_alert, has_content, count_items
    from alerts.template import render_html, render_subject

    payload = build_alert()
    n = count_items(payload)
    has = has_content(payload)
    today = _today_str()
    state = _load_state()
    already_sent_today = state.get(today, {}).get("sent", False)

    print("[alerts] fecha=" + today + " slot=" + args.slot +
          " contenido=" + str(n) + " items already_sent_today=" + str(already_sent_today))

    should_send = False
    if args.force:
        should_send = True
        reason = "forced"
    elif already_sent_today:
        should_send = False
        reason = "ya enviado hoy"
    elif args.slot == "09":
        if has:
            should_send = True
            reason = "9 AM con contenido"
        else:
            should_send = False
            reason = "9 AM sin contenido - espera al retry de 10 AM"
    elif args.slot == "10":
        should_send = True
        reason = "10 AM (retry)"
    else:
        should_send = True
        reason = "envio manual"

    print("[alerts] decision: " + ("ENVIAR" if should_send else "SKIP") + " (" + reason + ")")

    if not should_send:
        return 0

    html_body = render_html(payload)
    subject = render_subject(payload)

    if args.dry_run:
        print("[alerts] DRY RUN - no envio. HTML primeros 2000 chars:")
        print(html_body[:2000])
        print("...")
        print()
        print("[subject] " + subject)
        return 0

    from alerts.send import send_email
    # Lista de destinatarios = todos los usuarios registrados en users.json.
    # Si users.json esta vacio o no existe, fallback a ALERT_RECIPIENT (legacy).
    recipients = _list_recipients()
    if not recipients:
        print("[alerts] no hay usuarios registrados ni ALERT_RECIPIENT — nada que enviar.")
        return 0
    sent_to = []
    errors = 0
    for r in recipients:
        try:
            send_email(subject, html_body, recipient=r)
            sent_to.append(r)
            print("[alerts] enviado a " + r)
        except Exception as e:
            errors += 1
            print("[alerts] ERROR enviando a " + r + ": " + type(e).__name__ + ": " + str(e),
                  file=sys.stderr)
    if errors and not sent_to:
        return 1

    state[today] = {
        "sent": True,
        "sent_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "slot": args.slot,
        "items": n,
        "recipients": sent_to,
        "errors": errors,
    }
    _save_state(state)
    return 0


def _list_recipients():
    """Devuelve la lista de emails a notificar."""
    import json
    import os
    users_path = REPO_ROOT / "data" / "users.json"
    if users_path.exists():
        try:
            users = json.loads(users_path.read_text(encoding="utf-8"))
            emails = [u.get("email") for u in users if u.get("email")]
            if emails:
                return emails
        except Exception:
            pass
    fallback = os.environ.get("ALERT_RECIPIENT")
    return [fallback] if fallback else []


def main(argv=None):
    p = argparse.ArgumentParser(prog="alerts", description="Sistema de alertas Radar Legislativo")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("send", help="Construye y manda el email")
    s.add_argument("--slot", choices=["09", "10", "manual"], default="manual",
                   help="Slot horario (afecta logica 9/10 AM). Default manual.")
    s.add_argument("--dry-run", action="store_true", help="No envia, imprime HTML")
    s.add_argument("--force", action="store_true",
                   help="Envia aunque ya se haya marcado como enviado hoy")
    s.set_defaults(func=cmd_send)
    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
