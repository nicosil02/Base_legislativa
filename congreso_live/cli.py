"""CLI de congreso_live: deteccion en vivo, transcripciones y backfills.

  python -m congreso_live.cli check [--dry-run]   # detecta en vivo y avisa lo nuevo

Estado (dedupe de avisos) en data/congreso_live_state.json, lo commitea el workflow.
"""
from __future__ import annotations

import argparse
import logging

from congreso_live.agenda_preview import aviso_inicio
from congreso_live.detector import vivos_de_interes
from congreso_live.notify import enviar_whatsapp
from congreso_live.state import (
    comision_seguida as _comision_seguida,
    load_state as _load_state,
    save_state as _save_state,
    seguidas_activas,
)
from congreso_live.transcripciones import run_sync as sync_transcripciones
from core.db import now_iso

log = logging.getLogger(__name__)


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

    seguidas_norm = seguidas_activas()

    now = now_iso()
    enviados = 0
    for v in nuevos:
        if _comision_seguida(v["tipo"], seguidas_norm):
            msg = aviso_inicio(v)
            if msg:
                enviar_whatsapp(msg)
                enviados += 1
        state.setdefault("alertados", []).append(v["id"])
        state.setdefault("sesiones", []).append({**v, "visto_at": now})

    _save_state(state)
    print(f"{len(nuevos)} sesion(es) nueva(s) vista(s), {enviados} aviso(s) enviado(s).")
    return 0


def cmd_sync_transcripciones(args) -> int:
    stats = sync_transcripciones(max_candidatos=args.max)
    print(
        f"Transcripciones: {stats['candidatos']} sesion(es) terminadas revisadas, "
        f"{stats['pendientes']} sin transcripcion guardada, "
        f"{stats['nuevas']} nueva(s) descargada(s)."
    )
    return 0


def cmd_live_watch(args) -> int:
    """Detecta y transcribe sola cualquier sesion en vivo (varias a la vez).
    Sin --max-total-minutos corre hasta Ctrl+C."""
    try:
        from congreso_live.live_transcribe import watch_and_transcribe
    except ImportError:
        print("Falta faster-whisper/imageio-ffmpeg: "
              "pip install faster-whisper imageio-ffmpeg")
        return 1
    try:
        watch_and_transcribe(intervalo_seg=args.intervalo, poll_seg=args.poll,
                             max_total_minutos=args.max_total_minutos,
                             idle_exit_minutos=args.idle_exit_minutos)
    except KeyboardInterrupt:
        print("\n[live-watch] listo, cortado por el usuario.")
    return 0


def cmd_backfill_vod(args) -> int:
    """Sesion terminada que la captura en vivo se perdio: transcribe el VOD
    completo sin esperar los captions de YouTube (tardan horas o dias)."""
    try:
        from congreso_live.live_transcribe import transcribir_vod
    except ImportError:
        print("Falta faster-whisper/imageio-ffmpeg: "
              "pip install faster-whisper imageio-ffmpeg")
        return 1
    r = transcribir_vod(args.video_id, args.tipo, args.titulo)
    if not r["ok"]:
        print(f"FALLO: {r['motivo']}")
        return 1
    print(f"OK: {r['chars']} chars, ~{(r['duracion_seg'] or 0)//60} min cubiertos.")
    return 0


def cmd_backfill_auto(args) -> int:
    """Recupera hasta --max sesiones del canal que no estan transcritas."""
    try:
        from congreso_live.backfill_auto import procesar_pendientes
    except ImportError:
        print("Falta faster-whisper/imageio-ffmpeg: "
              "pip install faster-whisper imageio-ffmpeg")
        return 1
    from congreso_live.transcripciones import _find_db_path

    r = procesar_pendientes(_find_db_path(), max_n=args.max, solo_pedidos=args.solo_pedidos)
    print(f"Pendientes encontrados: {r['pendientes_totales']}. "
          f"Procesados: {len(r['procesados'])}, fallidos: {len(r['fallidos'])}.")
    for p in r["procesados"]:
        print(f"  OK {p['video_id']} via {p['via']}: {p['chars']} chars")
    for f in r["fallidos"]:
        print(f"  FALLO {f['video_id']}: {f['motivo']}")
    return 0


def cmd_comisiones_ec(args) -> int:
    """Transcribe las sesiones terminadas de comisiones EC (Facebook) que falten."""
    try:
        from congreso_live.facebook_ec import procesar_pendientes
    except ImportError:
        print("Falta playwright/faster-whisper: pip install playwright faster-whisper imageio-ffmpeg")
        return 1
    from congreso_live.transcripciones import _find_db_path

    r = procesar_pendientes(_find_db_path(), max_n=args.max)
    print(f"Comisiones EC: {r['vistas']} sesion(es) terminadas vistas en Facebook, "
          f"{r['pendientes_totales']} sin transcribir. Procesados: {len(r['procesados'])}, "
          f"fallidos: {len(r['fallidos'])}.")
    for p in r["procesados"]:
        print(f"  OK {p['video_id']} ({p['comision']}): {p['chars']} chars")
    for f in r["fallidos"]:
        print(f"  FALLO {f['video_id']} ({f['comision']}): {f['motivo']}")
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
    lw = sub.add_parser("live-watch",
                        help="corre por detras: detecta y transcribe SOLA cualquier sesion en vivo, sin intervencion manual")
    lw.add_argument("--intervalo", type=int, default=40,
                    help="segundos de espera antes de reintentar abrir el audio en vivo (default 40); el audio se transcribe frase por frase")
    lw.add_argument("--poll", type=int, default=60,
                    help="cada cuantos segundos revisa si hay sesiones nuevas en vivo (default 60)")
    lw.add_argument("--max-total-minutos", type=float, default=None,
                    help="si se pasa, sale solo al llegar a este limite en vez de correr para siempre (para un workflow con tiempo maximo)")
    lw.add_argument("--idle-exit-minutos", type=float, default=None,
                    help="si se pasa, sale sola si no hay NADA en vivo desde hace este tiempo, en vez de seguir poll-eando sin hacer nada hasta --max-total-minutos")
    lw.set_defaults(func=cmd_live_watch)
    bv = sub.add_parser("backfill-vod",
                        help="sesion ya terminada que la captura en vivo se perdio: baja y transcribe el audio COMPLETO del VOD")
    bv.add_argument("--video-id", required=True)
    bv.add_argument("--tipo", required=True)
    bv.add_argument("--titulo", required=True)
    bv.set_defaults(func=cmd_backfill_vod)
    ba = sub.add_parser("backfill-auto",
                        help="escanea el canal solo y recupera sesiones reales que faltan, sin intervencion manual")
    ba.add_argument("--max", type=int, default=4,
                    help="cuantas sesiones recuperar por corrida (default 4 - cada una cuesta red/CPU real)")
    ba.add_argument("--solo-pedidos", action="store_true",
                    help="solo los videos pedidos desde Noticias (data/videos_pedidos/), sin escanear el canal")
    ba.set_defaults(func=cmd_backfill_auto)
    ce = sub.add_parser("comisiones-ec",
                        help="comisiones de la Asamblea EC (Facebook): transcribe las sesiones terminadas que falten")
    ce.add_argument("--max", type=int, default=3,
                    help="cuantas sesiones transcribir por corrida (default 3 - Whisper sobre el audio completo)")
    ce.set_defaults(func=cmd_comisiones_ec)
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
