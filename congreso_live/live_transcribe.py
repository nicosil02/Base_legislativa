"""Transcripcion de sesiones en vivo y de VODs con yt-dlp + faster-whisper.

En CI YouTube bloquea la IP del runner: todo sale por WARP (YT_DLP_PROXY,
ver detector._ydl). El modelo "small" en CPU va mas rapido que tiempo real.
"""
from __future__ import annotations

import os
import re
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path


def _ffmpeg_bin() -> Path:
    """Binario de ffmpeg. El de imageio_ffmpeg tiene nombre raro y yt-dlp
    busca "ffmpeg"/"ffmpeg.exe", asi que se copia una vez con ese nombre.
    FFMPEG_BIN lo reemplaza: en CI el binario portable crashea (SIGSEGV) y
    se usa el ffmpeg de apt."""
    ffmpeg_bin_env = os.environ.get("FFMPEG_BIN")
    if ffmpeg_bin_env and Path(ffmpeg_bin_env).exists():
        return Path(ffmpeg_bin_env)
    import imageio_ffmpeg
    src = Path(imageio_ffmpeg.get_ffmpeg_exe())
    ffbin_dir = Path(tempfile.gettempdir()) / "vali_ffbin"
    ffbin_dir.mkdir(exist_ok=True)
    dst = ffbin_dir / ("ffmpeg.exe" if src.suffix == ".exe" else "ffmpeg")
    if not dst.exists():
        shutil.copy(src, dst)
    return dst


def capturar_audio_en_vivo(video_id: str, segundos: int = 30) -> Path | None:
    """Graba los proximos `segundos` de un video EN VIVO a un .wav temporal
    (16 kHz mono). Bloquea unos `segundos`. None si no salio nada util."""
    ffmpeg_local = _ffmpeg_bin()
    tmp_dir = Path(tempfile.mkdtemp(prefix="vali_live_"))
    clip_path = tmp_dir / "clip.mp4"
    stderr_path = tmp_dir / "yt-dlp.stderr.log"
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--ffmpeg-location", str(ffmpeg_local.parent),
        "-f", "bestaudio/best",
        "-o", str(clip_path),
        f"https://www.youtube.com/watch?v={video_id}",
    ]
    # En vivo yt-dlp delega la descarga a ffmpeg y le pasa su --proxy, y
    # ffmpeg no entiende socks5://: se usa el puente HTTP (privoxy,
    # FFMPEG_HTTP_PROXY) como proxy de yt-dlp.
    proxy = os.environ.get("FFMPEG_HTTP_PROXY") or os.environ.get("YT_DLP_PROXY")
    if proxy:
        cmd += ["--proxy", proxy, "--hls-prefer-native"]
    # Popen + matar el arbol entero (no run(timeout=)): yt-dlp lanza ffmpeg
    # como nieto, y matar solo al hijo deja el ffmpeg huerfano, el pipe
    # abierto y el archivo sin cerrar. start_new_session permite killpg.
    stderr_f = open(stderr_path, "wb")
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=stderr_f,
            start_new_session=(os.name != "nt"),
        )
    finally:
        stderr_f.close()  # el hijo ya tiene su propio fd duplicado, este puede cerrarse
    try:
        proc.wait(timeout=segundos)
    except subprocess.TimeoutExpired:
        _matar_arbol(proc)

    part_path = clip_path.with_suffix(clip_path.suffix + ".part")
    src = part_path if part_path.exists() else clip_path
    if not src.exists() or src.stat().st_size < 10_000:
        tam = src.stat().st_size if src.exists() else None
        # Las lineas que importan, de todo el stderr: la cola suele ser ruido
        # tardio que tapa el error real.
        texto = stderr_path.read_text(encoding="utf-8", errors="replace") if stderr_path.exists() else ""
        claves = ("ERROR", "SOCKS", "exited with code", "Sign in to confirm", "Traceback")
        relevantes = [l for l in texto.splitlines() if any(k in l for k in claves)]
        err = "\n".join(relevantes) if relevantes else texto[-500:]
        print(f"[live-transcribe] {video_id}: yt-dlp no genero un archivo util "
              f"(existe={src.exists()}, tamano={tam}, path={src}) stderr: {err}")
        return None

    wav_path = tmp_dir / "clip.wav"
    r = subprocess.run(
        [str(ffmpeg_local), "-y", "-i", str(src), "-ar", "16000", "-ac", "1", str(wav_path)],
        capture_output=True, timeout=30,
    )
    if r.returncode != 0 or not wav_path.exists():
        err = (r.stderr or b"").decode("utf-8", errors="replace")[-500:]
        print(f"[live-transcribe] {video_id}: ffmpeg fallo la conversion a wav "
              f"(returncode={r.returncode}): {err}")
        return None
    return wav_path


def _matar_arbol(proc: subprocess.Popen) -> None:
    """Mata el proceso y sus hijos (yt-dlp lanza ffmpeg como nieto)."""
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except ProcessLookupError:
            proc.kill()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass


SR = 16_000  # Whisper espera mono a 16 kHz


def cargar_whisper():
    """Modelo Whisper "small" en CPU (int8), el que usa todo el proyecto."""
    from faster_whisper import WhisperModel
    return WhisperModel("small", device="cpu", compute_type="int8")


def abrir_audio_en_vivo(video_id: str):
    """Audio continuo de un stream en vivo: un solo ffmpeg leyendo el HLS
    y entregando PCM 16 kHz mono. Devuelve (cola, cerrar) o None. La cola
    recibe trozos float32 de 0,1 s y None cuando el stream se corta.
    Un clip por chunk perdia lo dicho mientras se transcribia el anterior;
    leer ffmpeg en un hilo aparte evita que Whisper frene la descarga.
    Video de Facebook (id "fb_", ver facebook_ec.py): manifiesto DASH en vez
    de HLS, y sin WARP (Facebook no bloquea las IPs de GitHub)."""
    import queue
    import threading

    import numpy as np

    from congreso_live.detector import con_rotacion_warp, yt_dlp_cmd
    from congreso_live.facebook_ec import PREFIJO_ID, es_directo, url_video

    facebook = video_id.startswith(PREFIJO_ID)
    if facebook:
        cmd = [sys.executable, "-m", "yt_dlp", "-g", "-f", "bestaudio/best", url_video(video_id)]
    else:
        cmd = yt_dlp_cmd("-g", "-f", "233/234/bestaudio/best",
                         f"https://www.youtube.com/watch?v={video_id}")
    r = con_rotacion_warp(lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=60),
                          lambda r: r.stderr if r.returncode else None)
    url = r.stdout.strip().splitlines()[0] if r.returncode == 0 and r.stdout.strip() else None
    if not url:
        print(f"[live-transcribe] {video_id}: yt-dlp -g no dio URL: {r.stderr[-500:]}")
        return None
    if facebook and not es_directo(url):
        print(f"[live-transcribe] {video_id}: el directo de Facebook ya termino")
        return None

    ff = [str(_ffmpeg_bin()), "-loglevel", "error"]
    if facebook:  # los segmentos los baja alimentar_directo y entran por stdin
        ff += ["-i", "pipe:0"]
    else:
        # ffmpeg no entiende socks5:// (ver capturar_audio_en_vivo): va por privoxy
        if os.environ.get("FFMPEG_HTTP_PROXY"):
            ff += ["-http_proxy", os.environ["FFMPEG_HTTP_PROXY"]]
        ff += ["-live_start_index", "-1", "-i", url]
    ff += ["-vn", "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"]
    proc = subprocess.Popen(ff, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            stdin=subprocess.PIPE if facebook else subprocess.DEVNULL,
                            start_new_session=(os.name != "nt"))
    parar = threading.Event()
    if facebook:
        from congreso_live.facebook_ec import alimentar_directo
        threading.Thread(target=alimentar_directo, args=(url, proc.stdin, parar),
                         daemon=True, name=f"dash-{video_id}").start()
    cola: queue.Queue = queue.Queue()

    def leer():
        while datos := proc.stdout.read(SR // 10 * 2):  # 0,1 s de int16
            cola.put(np.frombuffer(datos, dtype=np.int16).astype(np.float32) / 32768)
        cola.put(None)

    threading.Thread(target=leer, daemon=True, name=f"ffmpeg-{video_id}").start()

    def cerrar():
        parar.set()
        _matar_arbol(proc)
    return cola, cerrar


def corte_de_frase(audio, pausa: float = 0.6, max_frase: float = 15.0) -> int | None:
    """Cuantas muestras de `audio` forman una frase cerrada (el orador hizo
    una pausa de `pausa` s, o ya van `max_frase` s). None = seguir esperando,
    0 = solo silencio. Misma logica que CasiEnVivo de la sesion 13."""
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    dur = len(audio) / SR
    if dur < 1.0:
        return None
    tramos = get_speech_timestamps(audio, VadOptions(
        min_silence_duration_ms=int(pausa * 1000), max_speech_duration_s=max_frase, speech_pad_ms=200))
    if not tramos:
        return 0
    fin_voz = tramos[-1]["end"]
    if len(audio) - fin_voz >= pausa * SR:
        return fin_voz
    return len(audio) if dur >= max_frase else None


def descargar_audio_completo(video_id: str, url: str | None = None) -> Path | None:
    """Baja el audio COMPLETO de un video ya terminado (VOD) a un .wav
    16 kHz mono, sin timeout. `url` para videos que no son de YouTube
    (Facebook, ver facebook_ec.py)."""
    from congreso_live.detector import con_rotacion_warp, yt_dlp_cmd

    ffmpeg_local = _ffmpeg_bin()
    tmp_dir = Path(tempfile.mkdtemp(prefix="vali_vod_"))
    audio_path = tmp_dir / "audio.m4a"
    cmd = yt_dlp_cmd("--ffmpeg-location", str(ffmpeg_local.parent), "-f", "bestaudio",
                     "-o", str(audio_path), url or f"https://www.youtube.com/watch?v={video_id}")
    r = con_rotacion_warp(
        lambda: subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True),
        lambda r: r.stderr if r.returncode else None)
    if r.returncode != 0 or not audio_path.exists():
        print(f"[descargar_audio_completo] yt-dlp fallo (rc={r.returncode}): "
              f"{r.stderr[-2000:]}", file=sys.stderr)
        return None

    wav_path = tmp_dir / "audio.wav"
    r = subprocess.run(
        [str(ffmpeg_local), "-y", "-i", str(audio_path), "-ar", "16000", "-ac", "1", str(wav_path)],
        capture_output=True, text=True,
    )
    if r.returncode != 0 or not wav_path.exists():
        print(f"[descargar_audio_completo] ffmpeg fallo (rc={r.returncode}): "
              f"{r.stderr[-2000:]}", file=sys.stderr)
        return None
    return wav_path


def transcribir_vod(video_id: str, tipo: str, titulo: str, modelo=None, db_path=None,
                    url: str | None = None, fecha: str | None = None,
                    duracion: int | None = None) -> dict:
    """Sesion ya terminada: baja el audio completo y lo transcribe con
    Whisper, sin esperar los captions de YouTube (tardan horas o dias).
    `duracion`: la del video si se conoce (si no, hasta la ultima frase)."""
    from datetime import datetime, timezone

    from congreso_live.transcripciones import _find_db_path, guardar_transcripcion, init_schema
    from noticias.temas import clasificar as _clasificar_temas

    wav = descargar_audio_completo(video_id, url) if url else descargar_audio_completo(video_id)
    if wav is None:
        return {"ok": False, "motivo": "no se pudo bajar/convertir el audio"}
    if modelo is None:
        modelo = cargar_whisper()
    from congreso_live.agenda_preview import contexto_whisper
    segs = transcribir_audio(wav, modelo, contexto_whisper(tipo, titulo, fecha))
    texto = " ".join(s["text"] for s in segs)
    if not texto:
        return {"ok": False, "motivo": "no se detecto habla en el audio"}

    db_path = db_path or _find_db_path()
    conn = sqlite3.connect(str(db_path))
    init_schema(conn)
    temas = _clasificar_temas(titulo, texto[:5000])
    duracion = duracion or (int(segs[-1]["end"]) if segs else None)
    guardar_transcripcion(conn, video_id, tipo, titulo,
                          fecha or datetime.now(timezone.utc).date().isoformat(),
                          duracion, texto, temas)
    conn.close()
    return {"ok": True, "chars": len(texto), "duracion_seg": duracion}


def transcribir_audio(wav_path, modelo, contexto: str | None = None) -> list[dict]:
    """Corre un WhisperModel ya cargado sobre el wav (o un arreglo float32 a
    16 kHz). `contexto`: vocabulario que debe escribir bien (initial_prompt).
    Devuelve [{start, end, text}] sin los segmentos de baja confianza
    (no_speech_prob/avg_logprob): en silencio o ruido Whisper alucina
    texto ("y y y y...")."""
    segments, _info = modelo.transcribe(
        wav_path if hasattr(wav_path, "dtype") else str(wav_path), language="es", beam_size=1,
        vad_filter=True,  # corta silencios antes de mandarlos al modelo
        initial_prompt=contexto,
    )
    out = []
    for s in segments:
        if s.no_speech_prob > 0.6 or s.avg_logprob < -1.0:
            continue
        texto = s.text.strip()
        if texto:
            out.append({"start": s.start, "end": s.end, "text": texto})
    return out


# Aviso cuando en un Pleno se vota algo o pasa a cuarto intermedio, con el
# texto previo (suele decir que se vota).
# ponytail: regex sobre el texto de Whisper, sin LLM; si el extracto crudo
# no alcanza, resumirlo con Gemini antes de mandarlo.
# Exige un conteo en cifras: "ha sido aprobado" suelto salta con las actas,
# y los comentaristas de TV dicen los numeros en palabras ("con ocho votos").
_VOTACION = re.compile(
    r"(?i)votad[oa]s? a favor,? \d+|\d+ votos? (a favor|en contra|afirmativos|negativos)|"
    r"cuarto intermedio")
AVISO_VOTACION_COOLDOWN_SEG = 180  # anuncio + "ha sido aprobado" llegan en chunks seguidos


def detectar_votacion(contexto: str, nuevo: str) -> str | None:
    """Si el chunk nuevo trae un resultado de votacion, devuelve un extracto
    (lo anterior + el resultado) para el aviso; si no, None."""
    m = _VOTACION.search(nuevo)
    if not m:
        return None
    texto = (contexto + " " + nuevo).strip()
    fin = len(texto) - len(nuevo) + m.end()
    # 900 chars antes (lo que se vota) y 350 despues ("ha sido aprobado...").
    return "…" + texto[max(0, fin - 900):fin + 350].strip() + "…"


def capturar_y_acumular_en_vivo(
    video_id: str,
    tipo: str,
    titulo: str,
    intervalo_seg: int = 40,
    max_minutos: float | None = None,
    modelo=None,
    db_path=None,
) -> dict:
    """Loop bloqueante: mientras la sesion siga en vivo (o hasta
    `max_minutos`), transcribe el audio frase por frase y lo ACUMULA en la
    fila de sesiones_transcripciones del video (la misma tabla de los
    captions, asi la rutina de resumenes no necesita otro pipeline).
    `intervalo_seg`: espera antes de reintentar abrir el stream."""
    import time
    from datetime import datetime, timezone

    from congreso_live.detector import vivos_de_interes
    from congreso_live.facebook_ec import PREFIJO_ID, info_en_vivo, url_video
    from congreso_live.transcripciones import _find_db_path, guardar_transcripcion, init_schema
    from noticias.temas import clasificar as _clasificar_temas

    db_path = db_path or _find_db_path()
    # timeout=30: varios hilos (una sesion cada uno) escriben el mismo archivo.
    conn = sqlite3.connect(str(db_path), timeout=30)
    init_schema(conn)

    row = conn.execute(
        "SELECT texto, duracion_seg FROM sesiones_transcripciones WHERE video_id=?",
        (video_id,),
    ).fetchone()
    texto_acumulado = row[0] if row else ""
    duracion_acumulada = (row[1] or 0) if row else 0

    import numpy as np

    # Whisper escribe mejor lo que ya "espera" oir: titulo + agenda del dia.
    from congreso_live.agenda_preview import contexto_whisper
    contexto = contexto_whisper(tipo, titulo)
    chunks_ok = 0
    misses_seguidos = 0
    t_inicio = time.time()
    t_ultimo_aviso = 0.0
    # Resumen para clientes: desde donde y cuando fue el ultimo tramo.
    from congreso_live import resumen_vivo
    ini_resumen, t_resumen = len(texto_acumulado), time.time()
    abierto = None  # (cola, cerrar) del ffmpeg continuo
    pendiente = np.zeros(0, dtype=np.float32)
    try:
        while True:
            if max_minutos is not None and (time.time() - t_inicio) > max_minutos * 60:
                break
            if abierto is not None:
                cola, cerrar = abierto
                try:
                    trozo = cola.get(timeout=30)
                except Exception:  # queue.Empty: ffmpeg colgado sin datos
                    print(f"[live-transcribe] {video_id}: 30 s sin audio, reabro el stream")
                    trozo = None
                if trozo is None:
                    cerrar()
                    abierto = None
                    corte = len(pendiente) if len(pendiente) > SR // 2 else 0
                else:
                    pendiente = np.concatenate([pendiente, trozo])
                    corte = corte_de_frase(pendiente)
                    if corte is None:
                        continue
                if corte == 0:  # solo silencio: se descarta
                    pendiente = pendiente[-SR // 2:]
                    continue
                frase, pendiente = pendiente[:corte], pendiente[corte:]
                if modelo is None:
                    modelo = cargar_whisper()
                segs = transcribir_audio(frase, modelo, contexto)
                nuevo_texto = " ".join(s["text"] for s in segs)
                if not nuevo_texto:
                    continue

                if tipo.startswith("Pleno") and time.time() - t_ultimo_aviso > AVISO_VOTACION_COOLDOWN_SEG:
                    extracto = detectar_votacion(texto_acumulado[-1500:], nuevo_texto)
                    if extracto:
                        from congreso_live.notify import enviar_whatsapp
                        enviar_whatsapp(f"🗳️ {tipo}: votación o cuarto intermedio\n"
                                        f"{titulo}\n\n{extracto}\n\n"
                                        f"{url_video(video_id)}")
                        t_ultimo_aviso = time.time()

                texto_acumulado = (texto_acumulado + " " + nuevo_texto).strip()
                duracion_acumulada += round(len(frase) / SR)
                chunks_ok += 1
                temas = _clasificar_temas(titulo, texto_acumulado[:5000])
                guardar_transcripcion(conn, video_id, tipo, titulo,
                                      datetime.now(timezone.utc).date().isoformat(),
                                      duracion_acumulada, texto_acumulado, temas)
                print(f"[live-transcribe] frase {chunks_ok}: {nuevo_texto[:120]}")
                if (time.time() - t_resumen >= resumen_vivo.CADA_SEG
                        and len(texto_acumulado) - ini_resumen >= resumen_vivo.MIN_CHARS):
                    try:
                        msg = resumen_vivo.resumir(tipo, titulo, texto_acumulado[ini_resumen:])
                        if msg:
                            from congreso_live.notify import enviar_whatsapp
                            enviar_whatsapp(f"{msg}\n\n{url_video(video_id)}")
                    except Exception as e:  # sin clave o sin cupo de Gemini: la transcripcion sigue
                        print(f"[live-transcribe] resumen en vivo fallo: {e}")
                    ini_resumen, t_resumen = len(texto_acumulado), time.time()
                continue

            # Sin stream abierto (arranque, o ffmpeg termino): solo se sigue si
            # la sesion sigue en vivo. Un error del chequeo (WARP) no debe
            # matar el hilo; hacen falta 2 misses seguidos para cortar.
            try:
                if video_id.startswith(PREFIJO_ID):
                    vivo = info_en_vivo(video_id[len(PREFIJO_ID):]) is not None
                else:
                    vivo = video_id in {v["id"] for v in vivos_de_interes()}
            except Exception as e:
                print(f"[live-transcribe] {video_id}: error chequeando en vivo, sigo: {e}")
                vivo = True
            if not vivo:
                misses_seguidos += 1
                if misses_seguidos >= 2:
                    break  # 2 chequeos seguidos sin exito: la sesion termino de verdad
                time.sleep(intervalo_seg)  # no reintentar en caliente, misma cadencia que un chunk
                continue
            misses_seguidos = 0

            abierto = abrir_audio_en_vivo(video_id)
            if abierto is None:
                print(f"[live-transcribe] {video_id}: no se pudo abrir el audio en vivo, reintento")
                time.sleep(intervalo_seg)
    finally:
        if abierto is not None:
            abierto[1]()
        conn.close()
    return {"chunks": chunks_ok, "duracion_seg": duracion_acumulada,
            "chars": len(texto_acumulado)}


def _avisar_si_no_avisado(v: dict) -> None:
    """Avisa de una sesion nueva descubierta a mitad del job (cmd_check solo
    corre al arrancar), con el mismo dedupe que cmd_check."""
    from congreso_live.agenda_preview import agenda_extra_para
    from congreso_live.notify import enviar_whatsapp
    from congreso_live.state import (
        comision_seguida, load_state, save_state, seguidas_activas,
    )
    from core.db import now_iso

    state = load_state()
    if v["id"] in set(state.get("alertados", [])):
        return
    if comision_seguida(v["tipo"], seguidas_activas()):
        enviar_whatsapp(f"🔴 {'Asamblea EC' if v.get('pais') == 'EC' else 'Congreso'} EN VIVO — {v['tipo']}\n{v['titulo']}\n{v['url']}"
                         f"{agenda_extra_para(v)}")
    state.setdefault("alertados", []).append(v["id"])
    state.setdefault("sesiones", []).append(
        {**v, "visto_at": now_iso()})
    save_state(state)


FACEBOOK_CADA_SEG = 300


def watch_and_transcribe(intervalo_seg: int = 40, poll_seg: int = 60,
                         max_total_minutos: float | None = None,
                         idle_exit_minutos: float | None = None) -> None:
    """Cada `poll_seg` s revisa que sesiones estan en vivo y arranca un hilo
    capturar_y_acumular_en_vivo() por cada una nueva (varias a la vez).

    `max_total_minutos` (CI): sale al cumplirse, esperando los hilos, para
    dejar margen al commit antes del corte de 6 h de Actions.
    `idle_exit_minutos` (CI): sale si no hay nada en vivo desde hace ese
    tiempo, para no ocupar el job (y la cola de concurrency) sin motivo.
    Cada hilo carga su propio modelo Whisper: no se asume que ctranslate2
    sea thread-safe sobre una misma instancia."""
    import threading
    import time

    from congreso_live.detector import vivos_de_interes

    hilos: dict[str, threading.Thread] = {}
    t_inicio = time.time()
    t_ultima_actividad = t_inicio
    t_facebook = float("-inf")  # el primer poll ya mira Facebook
    print(f"[live-watch] arrancando (poll cada {poll_seg}s, chunks de "
          f"{intervalo_seg}s). Ctrl+C para parar.")
    while True:
        ahora = time.time()
        if max_total_minutos is not None and (ahora - t_inicio) > max_total_minutos * 60:
            print(f"[live-watch] limite de {max_total_minutos} min alcanzado, cerrando.")
            for t in hilos.values():
                t.join()
            return
        if (idle_exit_minutos is not None and not hilos
                and (ahora - t_ultima_actividad) > idle_exit_minutos * 60):
            print(f"[live-watch] sin nada en vivo desde hace {idle_exit_minutos} min, cerrando.")
            return

        for vid in list(hilos):
            if not hilos[vid].is_alive():
                print(f"[live-watch] {vid}: la sesion termino, dejo de transcribirse.")
                del hilos[vid]

        try:
            vivos = vivos_de_interes()
        except Exception as e:
            print(f"[live-watch] error chequeando en vivo: {e}")
            vivos = []
        # Comisiones EC por Facebook: solo las paginas de las comisiones que
        # la agenda de la Asamblea pone sesionando ahora (sin agenda, todas),
        # cada FACEBOOK_CADA_SEG (sin cache: lo que no se vio no arranca hilo).
        if ahora - t_facebook >= FACEBOOK_CADA_SEG:
            t_facebook = ahora
            try:
                from congreso_live.facebook_ec import PAGINAS, listar_en_vivo, paginas_en_agenda
                paginas = paginas_en_agenda()
                if paginas is None:
                    paginas = PAGINAS
                if paginas:
                    vivos = vivos + listar_en_vivo(paginas)
            except Exception as e:
                print(f"[live-watch] error chequeando Facebook EC: {e}")

        if hilos or vivos:
            t_ultima_actividad = ahora

        for v in vivos:
            if v["id"] in hilos:
                continue
            print(f"[live-watch] nueva sesion en vivo: {v['tipo']} - {v['titulo']} ({v['id']})")
            _avisar_si_no_avisado(v)
            t = threading.Thread(
                target=capturar_y_acumular_en_vivo,
                kwargs=dict(video_id=v["id"], tipo=v["tipo"], titulo=v["titulo"],
                            intervalo_seg=intervalo_seg),
                daemon=True,
                name=f"live-{v['id']}",
            )
            t.start()
            hilos[v["id"]] = t

        time.sleep(poll_seg)
