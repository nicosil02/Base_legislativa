"""Entry point del sistema de alertas.

Uso:
    python -m alerts.cli send --slot am       # horario fijo 9am Lima
    python -m alerts.cli send --slot pm       # horario fijo 2pm Lima
    python -m alerts.cli send --slot manual   # envio manual/testing, sin marcar
    python -m alerts.cli send --dry-run       # imprime HTML, no envia
    python -m alerts.cli send --force         # envia aunque ya se haya enviado ese slot hoy

Logica del scheduling diario (redisenada 2026-09-20 - Nicolas: "a veces
no me dice nada, o sea me llega sin ningun update... debería llegar 2
veces al día, 1 a las 8-9am y otra a las 2pm... que reporte la del am
todo lo que paso post 2pm del dia anterior que no se reporto"):
  - 2 horarios fijos por dia (ver refrescar-pe.yml, gateado por
    github.event.schedule): "am" (9am Lima) y "pm" (2pm Lima).
  - Cada uno SIEMPRE envia, tenga contenido o no ("sin novedades" es una
    respuesta valida, visible - antes el retry de 10am se quedaba
    callado si a las 9am no habia contenido, eso generaba la sensacion
    de "a veces no dice nada"). Solo se salta si ESE slot especifico ya
    se mando hoy (evita duplicar en un rerun/retry del workflow).
  - La ventana de contenido es "desde el ultimo envio real" (cualquier
    slot, cualquier dia) - asi el envio de las 9am cubre automaticamente
    todo lo que paso desde las 2pm del dia anterior, sin necesidad de
    logica de fecha especial.

Estado persistido en data/alert_sent_log.json (commiteado), ahora
por-slot-por-dia: {"2026-09-20": {"am": {...}, "pm": {...}}}.
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
    from alerts.build import build_alert, count_items
    from alerts.template import render_html, render_subject

    today = _today_str()
    state = _load_state()
    dia = state.get(today, {})
    ya_enviado_este_slot = (
        args.slot in ("am", "pm") and isinstance(dia, dict)
        and dia.get(args.slot, {}).get("sent", False)
    )

    # Filtro "desde la ultima alerta real": recorre TODO el historial
    # (dias x slots) buscando la entrada sent=True mas reciente. Asi cada
    # cambio sale 1 vez en la primera alerta despues de su fecha - sin
    # solapar entre el envio de las 9am y el de las 2pm, y sin perder
    # cambios si fallo algun envio (se acumulan hasta el siguiente).
    # Fallback: si no hay entradas previas, build_alert usa 24h default.
    # Nota: entradas viejas (formato plano pre-2026-09-20, un solo envio
    # por dia) no matchean `isinstance(entry, dict)` dentro del loop de
    # abajo y se ignoran sin romper nada - la ventana simplemente se
    # resetea una vez al pasar al nuevo formato por-slot.
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

    # 2 horarios fijos (9am y 2pm Lima, ver refrescar-pe.yml) en vez del
    # viejo "9am solo si hay contenido, retry a las 10am" - Nicolas
    # 2026-09-20: "a veces no me dice nada, o sea me llega sin ningun
    # update" (el viejo esquema se quedaba callado en el retry de 10am si
    # a las 9am ya no habia contenido). Ahora SIEMPRE se manda en cada
    # horario fijo, contenido o no ("sin novedades" es una respuesta
    # valida y visible, no silencio ambiguo) - el unico skip real es no
    # duplicar el mismo slot dos veces el mismo dia (reintento/rerun).
    if args.force:
        should_send, reason = True, "forced"
    elif args.slot in ("am", "pm"):
        if ya_enviado_este_slot:
            should_send, reason = False, f"ya se envio el slot {args.slot} hoy"
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
                        "(9am/2pm Lima, ver refrescar-pe.yml) - siempre envian, "
                        "salvo que ese slot ya se haya mandado hoy. 'manual' "
                        "(default) es para pruebas: siempre envia, no marca estado.")
    s.add_argument("--dry-run", action="store_true", help="No envia, imprime HTML")
    s.add_argument("--force", action="store_true",
                   help="Envia aunque ese slot ya se haya marcado como enviado hoy")
    s.set_defaults(func=cmd_send)
    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
