"""Entry point del sistema de alertas.

Uso:
    python -m alerts.cli send --slot am       # horario fijo 9am Lima
    python -m alerts.cli send --slot pm       # horario fijo 2pm Lima
    python -m alerts.cli send --slot manual   # envio manual/testing, sin marcar
    python -m alerts.cli send --dry-run       # imprime HTML, no envia
    python -m alerts.cli send --force         # envia aunque ya se haya enviado ese slot hoy

Scheduling: 2 horarios fijos por dia (9am y 2pm Lima, ver refrescar-pe.yml).
Cada uno envia solo si hay novedades y ese slot no se envio ya hoy. La ventana
de contenido es "desde el ultimo envio real", asi el de las 9am cubre lo que
paso desde las 2pm del dia anterior.

Estado por slot y dia: {"2026-09-20": {"am": {...}, "pm": {...}}}.
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


# El estado vive en proyectos.db (tabla app_state), que refrescar-pe.yml
# publica; el JSON ya no se commitea y sin esto se duplicaban envios.
def _state_db():
    import sqlite3
    from alerts.build import _find_db_file
    p = _find_db_file("proyectos.db")
    if not p:
        return None
    c = sqlite3.connect(str(p))
    c.execute("CREATE TABLE IF NOT EXISTS app_state (k TEXT PRIMARY KEY, v TEXT)")
    return c


def _load_state():
    try:
        c = _state_db()
        if c:
            r = c.execute("SELECT v FROM app_state WHERE k='alert_sent_log'").fetchone()
            c.close()
            if r:
                return json.loads(r[0])
    except Exception as e:
        print(f"[alerts] no pude leer el estado de la base: {e}")
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(state):
    texto = json.dumps(state, ensure_ascii=False, indent=2)
    try:
        c = _state_db()
        if c:
            c.execute("INSERT OR REPLACE INTO app_state VALUES ('alert_sent_log', ?)", (texto,))
            c.commit()
            c.close()
    except Exception as e:
        print(f"[alerts] no pude guardar el estado en la base: {e}")
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(texto, encoding="utf-8")


def count_novedades(payload):
    """Solo lo que cambia: dictamenes, proyectos y normativa. La agenda
    existe todos los dias y no justifica un correo por si sola."""
    return sum(len(payload[p].get(s, []) or []) for p in ("peru", "ecuador")
               for s in ("dictamenes", "proyectos", "normativa"))


def cmd_send(args):
    from alerts.build import build_alert, count_items
    from alerts.template import render_html, render_subject

    today = _today_str()
    state = _load_state()
    dia = state.get(today, {})
    ya_enviado_este_slot = (
        args.slot in ("am", "pm") and isinstance(dia, dict)
        and dia.get(args.slot, {}).get("sent", False)
    )

    # Ventana desde el envio real mas reciente (cualquier dia y slot): cada
    # cambio sale una vez y nada se pierde si fallo un envio. Sin envios
    # previos, build_alert usa 24 h. Entradas de formato viejo se ignoran.
    since_iso = None
    sent_entries = []
    for slots in state.values():
        if not isinstance(slots, dict):
            continue
        for entry in slots.values():
            if isinstance(entry, dict) and entry.get("sent") and entry.get("sent_at"):
                sent_entries.append(entry)
    if sent_entries:
        sent_entries.sort(key=lambda e: e["sent_at"], reverse=True)
        since_iso = sent_entries[0]["sent_at"]
        print(f"[alerts] filtro desde ultima alerta: since={since_iso}")
    else:
        print("[alerts] sin alerta previa, usando window default 24h")

    payload = build_alert(since_iso=since_iso)
    n = count_items(payload)

    print("[alerts] fecha=" + today + " slot=" + args.slot +
          " contenido=" + str(n) + " items ya_enviado_este_slot=" + str(ya_enviado_este_slot))

    if args.force:
        should_send, reason = True, "forced"
    elif args.slot in ("am", "pm"):
        if ya_enviado_este_slot:
            should_send, reason = False, f"ya se envio el slot {args.slot} hoy"
        # Sin novedades no se envia ni se marca el slot: el proximo correo
        # con contenido cubre todo lo acumulado.
        elif count_novedades(payload) == 0:
            should_send, reason = False, "sin novedades (solo agenda)" if n else "sin novedades"
        else:
            should_send, reason = True, f"horario fijo ({args.slot})"
    else:
        should_send, reason = True, "envio manual"

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

    if args.slot in ("am", "pm"):
        state.setdefault(today, {})[args.slot] = {
            "sent": True,
            "sent_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
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
    s.add_argument("--slot", choices=["am", "pm", "manual"], default="manual",
                   help="Slot horario. 'am'/'pm' son los 2 horarios fijos "
                        "(9am/2pm Lima, ver refrescar-pe.yml) - envian solo con "
                        "novedades y si ese slot no se mando hoy. 'manual' "
                        "(default) es para pruebas: siempre envia, no marca estado.")
    s.add_argument("--dry-run", action="store_true", help="No envia, imprime HTML")
    s.add_argument("--force", action="store_true",
                   help="Envia aunque ese slot ya se haya marcado como enviado hoy")
    s.set_defaults(func=cmd_send)
    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
