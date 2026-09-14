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
from congreso_live.transcripciones import run_sync as sync_transcripciones

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


def cmd_sync_transcripciones(args) -> int:
    stats = sync_transcripciones(max_candidatos=args.max)
    print(
        f"Transcripciones: {stats['candidatos']} sesion(es) terminadas revisadas, "
        f"{stats['pendientes']} sin transcripcion guardada, "
        f"{stats['nuevas']} nueva(s) descargada(s)."
    )
    return 0


def cmd_live_transcribe(args) -> int:
    """Requiere `faster-whisper` e `imageio-ffmpeg` (no estan en
    requirements.txt - ver congreso_live/live_transcribe.py). Solo
    funciona desde una IP no bloqueada por YouTube (residencial/local),
    no desde GitHub Actions ni casi seguro Streamlit Cloud."""
    try:
        from congreso_live.live_transcribe import capturar_y_acumular_en_vivo
    except ImportError:
        print("Falta faster-whisper/imageio-ffmpeg: "
              "pip install faster-whisper imageio-ffmpeg")
        return 1

    vivos = vivos_de_interes()
    if args.video_id:
        v = next((x for x in vivos if x["id"] == args.video_id), None)
        if v is None:
            print(f"{args.video_id} no esta en la lista de en vivo ahora mismo.")
            return 1
    else:
        if not vivos:
            print("No hay ninguna sesion en vivo ahora mismo.")
            return 1
        v = vivos[0]
        if len(vivos) > 1:
            print(f"Hay {len(vivos)} sesiones en vivo, transcribiendo la primera: "
                  f"{v['tipo']} - {v['titulo']}")

    print(f"Transcribiendo en vivo: {v['tipo']} - {v['titulo']} ({v['id']})")
    print(f"Chunks de {args.intervalo}s, hasta que la sesion termine"
          f"{f' o pasen {args.max_minutos} min' if args.max_minutos else ''}.")
    resultado = capturar_y_acumular_en_vivo(
        v["id"], v["tipo"], v["titulo"],
        intervalo_seg=args.intervalo, max_minutos=args.max_minutos,
    )
    print(f"Listo: {resultado['chunks']} chunk(s) transcriptos, "
          f"{resultado['duracion_seg']}s cubiertos, {resultado['chars']} caracteres.")
    return 0


def cmd_live_watch(args) -> int:
    """Corre por detras, sin intervencion manual: detecta sola cualquier
    sesion en vivo (Pleno de cualquier camara, o comision ordinaria) y la
    va transcribiendo, soportando varias en simultaneo. Pensado para
    dejar corriendo en una terminal aparte. Ctrl+C para parar."""
    try:
        from congreso_live.live_transcribe import watch_and_transcribe
    except ImportError:
        print("Falta faster-whisper/imageio-ffmpeg: "
              "pip install faster-whisper imageio-ffmpeg")
        return 1
    try:
        watch_and_transcribe(intervalo_seg=args.intervalo, poll_seg=args.poll)
    except KeyboardInterrupt:
        print("\n[live-watch] listo, cortado por el usuario.")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="congreso_live")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="detecta en vivo y notifica lo nuevo")
    c.add_argument("--dry-run", action="store_true")
    c.set_defaults(func=cmd_check)
    t = sub.add_parser("sync-transcripciones",
                       help="baja transcripciones (captions YouTube) de sesiones terminadas")
    t.add_argument("--max", type=int, default=20,
                   help="cuantas sesiones terminadas recientes revisar (default 20)")
    t.set_defaults(func=cmd_sync_transcripciones)
    lt = sub.add_parser("live-transcribe",
                        help="transcribe en vivo (bloqueante) mientras la sesion siga transmitiendo")
    lt.add_argument("video_id", nargs="?", default=None,
                    help="id del video a transcribir; si se omite, usa la primera sesion en vivo")
    lt.add_argument("--intervalo", type=int, default=40,
                    help="segundos de audio real por chunk (default 40)")
    lt.add_argument("--max-minutos", type=float, default=None,
                    help="corta despues de N minutos aunque la sesion siga en vivo (default: sin limite)")
    lt.set_defaults(func=cmd_live_transcribe)
    lw = sub.add_parser("live-watch",
                        help="corre por detras: detecta y transcribe SOLA cualquier sesion en vivo, sin intervencion manual")
    lw.add_argument("--intervalo", type=int, default=40,
                    help="segundos de audio real por chunk (default 40)")
    lw.add_argument("--poll", type=int, default=60,
                    help="cada cuantos segundos revisa si hay sesiones nuevas en vivo (default 60)")
    lw.set_defaults(func=cmd_live_watch)
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
