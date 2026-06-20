"""CLI Fase 0: detecta Pleno/comisiones ordinarias EN VIVO y avisa por WhatsApp.

  python -m congreso_live.cli check            # detecta + notifica lo nuevo
  python -m congreso_live.cli check --dry-run  # solo muestra, no envia ni guarda

Estado en data/congreso_live_state.json (dedupe + log de sesiones), commiteado
por el workflow igual que data/alert_sent_log.json.
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from congreso_live.detector import vivos_de_interes
from congreso_live.notify import enviar_whatsapp

STATE_PATH = Path("data/congreso_live_state.json")
MAX_LOG = 300

log = logging.getLogger(__name__)


def _load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"alertados": [], "sesiones": []}


def _save_state(state: dict) -> None:
    state["sesiones"] = state.get("sesiones", [])[-MAX_LOG:]
    state["alertados"] = state.get("alertados", [])[-MAX_LOG:]
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=1),
                          encoding="utf-8")


def cmd_check(args) -> int:
    vivos = vivos_de_interes()
    log.info("en vivo de interes: %d", len(vivos))
    state = _load_state()
    ya = set(state.get("alertados", []))
    nuevos = [v for v in vivos if v["id"] not in ya]

    for v in vivos:
        marca = "NUEVO" if v["id"] in {n["id"] for n in nuevos} else "ya avisado"
        print(f"  [{marca}] {v['tipo']} — {v['titulo'][:70]}  {v['url']}")

    if args.dry_run:
        print(f"(dry-run) {len(nuevos)} nuevo(s), nada enviado.")
        return 0

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for v in nuevos:
        msg = (f"🔴 Congreso EN VIVO — {v['tipo']}\n{v['titulo']}\n{v['url']}")
        enviar_whatsapp(msg)
        state.setdefault("alertados", []).append(v["id"])
        state.setdefault("sesiones", []).append({**v, "visto_at": now})

    _save_state(state)
    print(f"{len(nuevos)} aviso(s) nuevo(s) enviados.")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="congreso_live")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="detecta en vivo y notifica lo nuevo")
    c.add_argument("--dry-run", action="store_true")
    c.set_defaults(func=cmd_check)
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
