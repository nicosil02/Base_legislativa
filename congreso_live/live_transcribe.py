"""Transcripcion en vivo de sesiones que estan transmitiendo ahora mismo -
yt-dlp + faster-whisper, 100% gratis.

Verificado en vivo 2026-09-14/15: funciona perfecto desde una IP local -
transcribio 52s de audio real de la Comision de Constitucion en 5s de
procesamiento (mas rapido que tiempo real, modelo "small" en CPU).

Las IPs de datacenter (GitHub Actions, Streamlit Cloud) estan marcadas por
el anti-bot de YouTube - pero tunelizar por Cloudflare WARP (VPN gratis)
lo esquiva, verificado en vivo 2026-09-15. `capturar_audio_en_vivo` usa
YT_DLP_PROXY si esta seteada (ver detector._ydl() para el detalle) - el
workflow de CI instala WARP en modo proxy y exporta esa variable, asi que
esto SI corre en GitHub Actions ademas de local.
"""
from __future__ import annotations

import os
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path


def _ffmpeg_bin() -> Path:
    """imageio_ffmpeg trae un binario portable pero con nombre raro
    (ffmpeg-win-x86_64-vX.Y.exe) - yt-dlp con --ffmpeg-location busca
    literalmente "ffmpeg"/"ffmpeg.exe", asi que lo copiamos una vez a un
    directorio propio con el nombre esperado.

    FFMPEG_BIN (si esta seteada) lo saltea del todo y usa ese binario
    directo - bug real encontrado en vivo 2026-09-15, corrida #795: el
    binario portable de imageio_ffmpeg crasheaba con SIGSEGV (code -11)
    en CI, primero al intentar SOCKS5 (ya arreglado con privoxy) y
    DESPUES tambien al convertir el clip ya descargado a wav - un archivo
    LOCAL, sin red de por medio, asi que no era el proxy: es el binario
    portable en si, fragil en este runner. El ffmpeg de apt de Ubuntu
    (bien probado en ese mismo runner) no tiene ese problema."""
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
    """Descarga los proximos `segundos` de audio de un video EN VIVO a un
    .wav temporal (16kHz mono, formato que espera Whisper). Devuelve el
    path, o None si no se pudo capturar nada util.

    Bloqueante: tarda aproximadamente `segundos` de reloj - no hay forma
    de ir mas rapido que tiempo real para capturar audio que todavia no
    se transmitio."""
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
    # Ver detector._ydl() para el porque: bloqueo de YouTube es por IP de
    # datacenter, WARP (gratis) lo esquiva - el workflow en CI exporta esto.
    #
    # CAUSA RAIZ real encontrada en vivo 2026-09-15, confirmada con el
    # stderr de yt-dlp (corridas #788 y #791, antes tirado a DEVNULL):
    #   "ffmpeg does not support SOCKS proxies. Downloading is likely to
    #   fail." + "ffmpeg exited with code -11" (segfault) - para un stream
    #   EN VIVO yt-dlp SIEMPRE delega la descarga a ffmpeg (--hls-prefer-
    #   native no lo evita), y ffmpeg no entiende socks5://.
    # Intento anterior (env["http_proxy"]) NO alcanzo: yt-dlp le pasa SU
    # PROPIO --proxy a ffmpeg de forma explicita (un arg, no una env var),
    # asi que ffmpeg seguia viendo el socks5:// crudo pase lo que pase en
    # el entorno. Fix real: si hay un puente HTTP (privoxy, ver
    # FFMPEG_HTTP_PROXY en el workflow), usarlo COMO el --proxy de yt-dlp
    # para esta descarga especifica - lo que yt-dlp le reenvia a ffmpeg
    # ya es un proxy HTTP normal, que si entiende.
    proxy = os.environ.get("FFMPEG_HTTP_PROXY") or os.environ.get("YT_DLP_PROXY")
    if proxy:
        cmd += ["--proxy", proxy, "--hls-prefer-native"]
    # subprocess.Popen + kill manual (no subprocess.run(timeout=...)):
    # yt-dlp lanza ffmpeg como su PROPIO subproceso para bajar streams
    # HLS. Con run(timeout=) Python mata solo el proceso hijo directo -
    # el ffmpeg nieto queda huerfano corriendo, y ademas run() con
    # capture_output=True se cuelga ESPERANDO EOF de un pipe que ese
    # huerfano todavia tiene abierto (bug real, encontrado en vivo
    # 2026-09-15: el boton se quedaba "cargando" para siempre). En
    # Windows, "taskkill /T" mata el arbol de procesos completo.
    #
    # En Linux (lo que corre GitHub Actions) faltaba el equivalente: sin
    # start_new_session, proc.kill() solo mata a yt-dlp, el ffmpeg nieto
    # queda huerfano y el archivo de salida nunca se cierra bien - bug
    # real encontrado en vivo 2026-09-15, corrida #780: CADA intento de
    # capturar un chunk fallaba (mas de 1000 veces en 11 min, para las 3
    # sesiones en simultaneo) despues de que la deteccion ya funcionaba
    # perfecto. start_new_session=True pone yt-dlp en su propio grupo de
    # procesos, y os.killpg mata ese grupo entero (yt-dlp + ffmpeg nieto)
    # de una - el equivalente real de "taskkill /T" para POSIX.
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
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        else:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except ProcessLookupError:
                proc.kill()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass

    part_path = clip_path.with_suffix(clip_path.suffix + ".part")
    src = part_path if part_path.exists() else clip_path
    if not src.exists() or src.stat().st_size < 10_000:
        # Diagnostico fino (bug real encontrado en vivo 2026-09-15: incluso
        # con el kill del arbol de procesos ya arreglado, CADA intento
        # seguia fallando sin pista de si yt-dlp no escribio nada, escribio
        # poco, o el problema era otro).
        tam = src.stat().st_size if src.exists() else None
        # Las ultimas 500 chars del stderr se llenaban con avisos tardios
        # sin relacion (ej. "No title found in player responses") y
        # tapaban el error real (el de SOCKS/ffmpeg suele salir bastante
        # antes) - bug real encontrado en vivo 2026-09-15, corrida #791.
        # En vez de adivinar donde cae el error, buscamos las lineas que
        # SI importan en TODO el stderr, y si no hay ninguna, recien ahi
        # mostramos la cola como fallback.
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


def descargar_audio_completo(video_id: str) -> Path | None:
    """Baja el audio COMPLETO de un video YA TERMINADO (VOD) - a diferencia
    de capturar_audio_en_vivo (pensada para clips cortos de streams en
    vivo, con timeout de unos segundos), esta espera lo que haga falta
    para bajar el archivo entero. Usa YT_DLP_PROXY (WARP) igual que el
    resto del modulo - corre en CI igual que en local."""
    ffmpeg_local = _ffmpeg_bin()
    tmp_dir = Path(tempfile.mkdtemp(prefix="vali_vod_"))
    audio_path = tmp_dir / "audio.m4a"
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--ffmpeg-location", str(ffmpeg_local.parent),
        "-f", "bestaudio",
        "-o", str(audio_path),
        f"https://www.youtube.com/watch?v={video_id}",
    ]
    proxy = os.environ.get("YT_DLP_PROXY")
    if proxy:
        cmd += ["--proxy", proxy]
    r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    if r.returncode != 0 or not audio_path.exists():
        # No tragarse el error: bug real 2026-09-16 (backfill-vod #8) - con
        # stderr=DEVNULL un fallo de yt-dlp quedaba completamente opaco
        # ("no se pudo bajar/convertir el audio" sin mas detalle).
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


def transcribir_vod(video_id: str, tipo: str, titulo: str, modelo=None, db_path=None) -> dict:
    """Sesion YA TERMINADA: baja el audio completo y lo transcribe de una
    con Whisper, sin esperar los captions automaticos de YouTube (esos
    tardan de horas a dias - ver transcripciones.py). Pensado para
    recuperar una sesion que la captura EN VIVO se perdio por algun bug
    de deteccion (ver congreso_live.cli backfill-vod) - bug real
    encontrado en vivo 2026-09-15: la Comision de Salud estuvo casi 2h en
    vivo sin transcribirse ni un segundo por el bug de detector.py."""
    from datetime import datetime, timezone

    from congreso_live.transcripciones import _find_db_path, init_schema
    from noticias.temas import clasificar as _clasificar_temas

    wav = descargar_audio_completo(video_id)
    if wav is None:
        return {"ok": False, "motivo": "no se pudo bajar/convertir el audio"}
    if modelo is None:
        from faster_whisper import WhisperModel
        modelo = WhisperModel("small", device="cpu", compute_type="int8")
    segs = transcribir_audio(wav, modelo)
    texto = " ".join(s["text"] for s in segs)
    if not texto:
        return {"ok": False, "motivo": "no se detecto habla en el audio"}

    db_path = db_path or _find_db_path()
    conn = sqlite3.connect(str(db_path))
    init_schema(conn)
    temas = _clasificar_temas(titulo, texto[:5000])
    duracion = int(segs[-1]["end"]) if segs else None
    conn.execute(
        """INSERT OR REPLACE INTO sesiones_transcripciones
           (video_id, tipo, titulo, fecha, duracion_seg, texto, temas, fetched_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (video_id, tipo, titulo, datetime.now(timezone.utc).date().isoformat(),
         duracion, texto, ",".join(temas), datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")),
    )
    conn.commit()
    conn.close()
    return {"ok": True, "chars": len(texto), "duracion_seg": duracion}


def transcribir_audio(wav_path: Path, modelo) -> list[dict]:
    """Corre un WhisperModel (faster_whisper) ya cargado sobre el wav.
    Devuelve lista de {start, end, text}, descartando segmentos de baja
    confianza. Whisper "alucina" texto sin sentido (tipico: un token
    repetido muchas veces, ej. "y y y y y...") cuando el audio no tiene
    habla clara - silencio, pausa entre oradores, ruido de sala. Bug real
    visto en vivo 2026-09-15. `no_speech_prob` y `avg_logprob` son las
    metricas de confianza que el propio modelo calcula por segmento -
    mas confiable que inventar un filtro de texto a mano."""
    segments, _info = modelo.transcribe(
        str(wav_path), language="es", beam_size=1,
        vad_filter=True,  # corta silencios antes de mandarlos al modelo
    )
    out = []
    for s in segments:
        if s.no_speech_prob > 0.6 or s.avg_logprob < -1.0:
            continue
        texto = s.text.strip()
        if texto:
            out.append({"start": s.start, "end": s.end, "text": texto})
    return out


def capturar_y_acumular_en_vivo(
    video_id: str,
    tipo: str,
    titulo: str,
    intervalo_seg: int = 40,
    max_minutos: float | None = None,
    modelo=None,
    db_path=None,
) -> dict:
    """Loop bloqueante: mientras la sesion siga en la lista de "en vivo"
    (o hasta `max_minutos`), captura un chunk de audio real cada
    `intervalo_seg` segundos, lo transcribe, y va ACUMULANDO el texto en
    la fila de `sesiones_transcripciones` para este video_id - la misma
    tabla que llenan los captions "del dia siguiente" via
    transcripciones.run_sync(). Reusar la tabla es deliberado: la rutina
    de resumenes ya sabe leer de ahi, no hace falta un pipeline nuevo -
    solo que la rutina tiene que aprender a RE-resumir cuando el texto
    crecio desde la ultima vez (ver notas del prompt de la rutina).

    Uso tipico (desde una sesion de Python en la PC de alguien, con IP
    no bloqueada por YouTube - ver docstring del modulo):
        from congreso_live.detector import vivos_de_interes
        from congreso_live.live_transcribe import capturar_y_acumular_en_vivo
        v = vivos_de_interes()[0]
        capturar_y_acumular_en_vivo(v["id"], v["tipo"], v["titulo"])
    """
    import time
    from datetime import datetime, timezone

    from congreso_live.detector import vivos_de_interes
    from congreso_live.transcripciones import _find_db_path, init_schema
    from noticias.temas import clasificar as _clasificar_temas

    db_path = db_path or _find_db_path()
    # timeout=30: live-watch puede correr VARIAS sesiones en paralelo (hilos
    # distintos, cada uno con su propia conexion) - SQLite serializa
    # escrituras entre conexiones del mismo archivo, un timeout mas largo
    # que el default (5s) evita "database is locked" si dos hilos escriben
    # casi al mismo tiempo (poco probable con chunks de ~40s, pero barato
    # de evitar).
    conn = sqlite3.connect(str(db_path), timeout=30)
    init_schema(conn)

    row = conn.execute(
        "SELECT texto, duracion_seg FROM sesiones_transcripciones WHERE video_id=?",
        (video_id,),
    ).fetchone()
    texto_acumulado = row[0] if row else ""
    duracion_acumulada = (row[1] or 0) if row else 0

    chunks_ok = 0
    misses_seguidos = 0
    t_inicio = time.time()
    try:
        while True:
            if max_minutos is not None and (time.time() - t_inicio) > max_minutos * 60:
                break
            # vivos_de_interes() vuelve a pegarle a YouTube via WARP - un
            # fallo transitorio (bot-check, WARP cargado) NO debe cortar
            # una captura que recien arranco. Bug real encontrado en vivo
            # 2026-09-15 (corrida #760): los 3 hilos que arrancaron a los
            # 96 min se murieron al toque porque este chequeo (sin
            # try/except) volvio a fallar y la excepcion sin atrapar
            # mataba el hilo entero - 0 segundos transcriptos pese a que
            # la sesion SI estaba en vivo. Ahora tolera 2 fallos/misses
            # seguidos antes de asumir que la sesion termino de verdad.
            try:
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

            wav = capturar_audio_en_vivo(video_id, segundos=intervalo_seg)
            if wav is None:
                # Antes esto fallaba en silencio - sin print, no habia forma
                # de saber desde el log si el cuello de botella era la
                # descarga de audio en si (yt-dlp/WARP) o algo mas. Bug real
                # encontrado en vivo 2026-09-15: con la deteccion ya
                # arreglada, 4 sesiones arrancaron threads pero 0 chunks en
                # 2+ min, sin ninguna pista de por que.
                print(f"[live-transcribe] {video_id}: no se pudo capturar/convertir audio, sigo")
                continue
            if modelo is None:
                from faster_whisper import WhisperModel
                modelo = WhisperModel("small", device="cpu", compute_type="int8")
            segs = transcribir_audio(wav, modelo)
            nuevo_texto = " ".join(s["text"] for s in segs)
            if not nuevo_texto:
                print(f"[live-transcribe] {video_id}: audio capturado sin habla clara, sigo")
                continue

            texto_acumulado = (texto_acumulado + " " + nuevo_texto).strip()
            duracion_acumulada += intervalo_seg
            chunks_ok += 1
            temas = _clasificar_temas(titulo, texto_acumulado[:5000])
            conn.execute(
                """INSERT OR REPLACE INTO sesiones_transcripciones
                   (video_id, tipo, titulo, fecha, duracion_seg, texto, temas, fetched_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (video_id, tipo, titulo, datetime.now(timezone.utc).date().isoformat(),
                 duracion_acumulada, texto_acumulado, ",".join(temas),
                 datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")),
            )
            conn.commit()
            print(f"[live-transcribe] chunk {chunks_ok}: "
                  f"+{len(nuevo_texto)} chars (total {len(texto_acumulado)} chars, "
                  f"{duracion_acumulada}s cubiertos)")
    finally:
        conn.close()
    return {"chunks": chunks_ok, "duracion_seg": duracion_acumulada,
            "chars": len(texto_acumulado)}


def _avisar_si_no_avisado(v: dict) -> None:
    """Avisa por WhatsApp de una sesion nueva descubierta ACA (a mitad de
    un job que ya viene transcribiendo otra) - reusa el mismo dedupe que
    cli.py::cmd_check (data/congreso_live_state.json) asi no se manda dos
    veces si cmd_check ya la habia alertado al arranque del job.

    Bug real 2026-09-17: cmd_check corre UNA sola vez, al arranque del
    job de vigilar-congreso.yml - una sesion que arranca mientras el job
    ya viene transcribiendo otra (hasta 170 min) no se avisaba hasta el
    proximo arranque de job, que con el disparador externo encolado y
    cancelado mientras tanto (mismo concurrency group) podia tardar
    horas. Ver congreso_live/state.py."""
    from datetime import datetime, timezone

    from congreso_live.notify import enviar_whatsapp
    from congreso_live.state import (
        comision_seguida, load_state, save_state, seguidas_activas,
    )

    state = load_state()
    if v["id"] in set(state.get("alertados", [])):
        return
    if comision_seguida(v["tipo"], seguidas_activas()):
        enviar_whatsapp(f"🔴 Congreso EN VIVO — {v['tipo']}\n{v['titulo']}\n{v['url']}")
    state.setdefault("alertados", []).append(v["id"])
    state.setdefault("sesiones", []).append(
        {**v, "visto_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
    save_state(state)


def watch_and_transcribe(intervalo_seg: int = 40, poll_seg: int = 60,
                         max_total_minutos: float | None = None,
                         idle_exit_minutos: float | None = None) -> None:
    """Corre para siempre (Ctrl+C para parar) o hasta `max_total_minutos` si
    se pasa - esto es "correr por detras": no hace falta pasarle un
    video_id a mano. Cada `poll_seg` segundos revisa que sesiones estan en
    vivo (Pleno de cualquier camara, o comision ordinaria - ver
    detector.vivos_de_interes()); para cada una que no tenga ya un hilo
    transcribiendola, arranca uno nuevo. Cada hilo corre
    capturar_y_acumular_en_vivo() y termina solo cuando su sesion deja de
    estar en vivo. Soporta varias sesiones en simultaneo (se vio en vivo
    2026-09-14: Constitucion y Economia transmitiendo a la vez).

    `max_total_minutos` (para CI - ver vigilar-congreso.yml): sale
    LIMPIO (join de los hilos activos, sin cortarlos a mitad de chunk)
    apenas se cumple el limite, en vez de quedarse corriendo para
    siempre. Pensado para un job con tiempo maximo (GitHub Actions corta
    duro a las 6h): un valor bien por debajo de ese limite deja margen
    para que el workflow siga con sus pasos de commit despues.

    `idle_exit_minutos` (tambien para CI): si no hay NINGUNA sesion en
    vivo (hilos vacio) desde hace mas de este tiempo, sale sola en vez de
    seguir poll-eando hasta max_total_minutos sin hacer nada util. Bug
    real encontrado en vivo 2026-09-15: sin esto, una corrida sin nada
    en vivo se quedaba ocupando el job (y bloqueando el siguiente
    disparo en la cola de concurrency) hasta 170 min por las puras. Con
    idle_exit_minutos, el workflow vuelve a responder rapido cuando no
    hay sesiones, y solo se queda las horas largas cuando SI hay algo
    que transcribir.

    Cada hilo carga su PROPIO modelo Whisper (no se comparte uno entre
    hilos) - mas memoria si hay varias sesiones a la vez, pero evita
    cualquier duda sobre si ctranslate2 es thread-safe para inferencia
    concurrente sobre la misma instancia.

    Pensado para dejar corriendo en una terminal aparte (o una tarea
    programada) en una maquina con IP no bloqueada por YouTube, o con
    YT_DLP_PROXY seteada (ver docstring del modulo)."""
    import threading
    import time

    from congreso_live.detector import vivos_de_interes

    hilos: dict[str, threading.Thread] = {}
    t_inicio = time.time()
    t_ultima_actividad = t_inicio
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


# ============================================================
# self-check (Ponytail: 1 chequeo ejecutable de la logica no trivial)
# ============================================================

def _demo():
    """No pega a la red (eso ya se verifico en vivo manualmente) - solo
    prueba que _ffmpeg_bin() resuelve y copia el binario sin explotar."""
    p = _ffmpeg_bin()
    assert p.exists(), f"ffmpeg no encontrado en {p}"
    assert p.name in ("ffmpeg.exe", "ffmpeg")
    print("OK live_transcribe: ffmpeg binario resuelto en", p)


def _test_killpg_mata_el_arbol_completo():
    """Solo POSIX (se salta en Windows - ahi el kill lo hace taskkill /T,
    ya verificado en vivo antes). Prueba que matar por process group (lo
    que ahora hace capturar_audio_en_vivo al vencer el timeout) mata
    tambien a un proceso NIETO, no solo al hijo directo - la razon real
    por la que CADA intento de captura fallaba en CI (Linux) hoy
    2026-09-15: yt-dlp lanza ffmpeg como nieto para streams HLS, y
    proc.kill() sin start_new_session solo mataba a yt-dlp, dejando el
    nieto huerfano y el archivo de salida sin cerrar bien."""
    if os.name == "nt":
        print("SKIP live_transcribe: test de killpg es solo POSIX (Windows ya usa taskkill /T)")
        return
    import time as _time

    # "padre" que lanza un "nieto" (sleep) en background y despues espera -
    # mismo patron que yt-dlp lanzando ffmpeg como subproceso.
    proc = subprocess.Popen(
        ["sh", "-c", "sleep 60 & echo $! ; wait"],
        stdout=subprocess.PIPE, text=True, start_new_session=True,
    )
    nieto_pid = int(proc.stdout.readline().strip())
    assert os.kill(nieto_pid, 0) is None, "el nieto deberia estar vivo antes del kill"

    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    proc.wait(timeout=5)

    _time.sleep(0.3)  # el kernel tarda un toque en liberar el PID
    try:
        os.kill(nieto_pid, 0)
        raise AssertionError("el nieto seguia vivo despues de killpg - el arbol no se mato entero")
    except ProcessLookupError:
        pass  # esperado: el nieto ya no existe
    print("OK live_transcribe: killpg mata al proceso nieto, no solo al hijo directo")


def _test_acumulacion():
    """Prueba la logica de acumulacion en sesiones_transcripciones SIN
    tocar la red - mockea captura/transcripcion/deteccion de "en vivo"
    para verificar que el texto crece chunk a chunk y que el loop corta
    solo cuando el video sale de la lista de en vivo."""
    import tempfile
    from unittest.mock import patch

    import congreso_live.live_transcribe as lt

    chunks_falsos = iter(["Primera parte de la sesion.",
                          "Segunda parte, sigue hablando.",
                          ""])  # el tercer chunk simula silencio (se ignora)
    vivos_falsos = iter([
        [{"id": "TEST123"}], [{"id": "TEST123"}], [{"id": "TEST123"}],
        [], [],  # 2 misses SEGUIDOS: recien ahi se asume terminada
    ])

    def _fake_capturar(video_id, segundos):
        return "fake.wav"

    def _fake_transcribir(wav_path, modelo):
        texto = next(chunks_falsos, "")
        return [{"start": 0, "end": segundos_fake, "text": texto}] if texto else []

    segundos_fake = 5
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "test.db"
        with patch.object(lt, "capturar_audio_en_vivo", _fake_capturar), \
             patch.object(lt, "transcribir_audio", _fake_transcribir), \
             patch("congreso_live.detector.vivos_de_interes", lambda: next(vivos_falsos)):
            resultado = lt.capturar_y_acumular_en_vivo(
                "TEST123", "Comision: Test", "Sesion de prueba",
                intervalo_seg=segundos_fake, modelo="modelo-fake", db_path=db_path,
            )

        assert resultado["chunks"] == 2, resultado
        conn = sqlite3.connect(str(db_path))
        texto, temas = conn.execute(
            "SELECT texto, temas FROM sesiones_transcripciones WHERE video_id='TEST123'"
        ).fetchone()
        conn.close()
    assert texto == "Primera parte de la sesion. Segunda parte, sigue hablando.", texto
    print("OK live_transcribe: acumulacion crece chunk a chunk y corta al terminar la sesion")


def _test_tolera_fallo_transitorio():
    """Un solo miss/excepcion de vivos_de_interes() (WARP flaqueando) NO
    debe cortar la captura - bug real encontrado en vivo 2026-09-15
    (corrida #760): un chequeo sin try/except mataba el hilo entero al
    primer fallo, perdiendo 96 min de sesion real. Aca simulamos: vivo,
    UNA excepcion, vivo de nuevo - debe seguir capturando sin cortar."""
    import tempfile
    from unittest.mock import patch

    import congreso_live.live_transcribe as lt

    chunks_falsos = iter(["Antes del fallo.", "Despues del fallo."])
    secuencia = iter([
        [{"id": "TEST123"}],
        "EXCEPCION",  # WARP/bot-check falla una vez
        [{"id": "TEST123"}],
        [], [],  # recien ahi termina de verdad
    ])

    def _vivos_falsos():
        v = next(secuencia)
        if v == "EXCEPCION":
            raise RuntimeError("Sign in to confirm you're not a bot")
        return v

    def _fake_capturar(video_id, segundos):
        return "fake.wav"

    def _fake_transcribir(wav_path, modelo):
        texto = next(chunks_falsos, "")
        return [{"start": 0, "end": 5, "text": texto}] if texto else []

    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "test.db"
        with patch.object(lt, "capturar_audio_en_vivo", _fake_capturar), \
             patch.object(lt, "transcribir_audio", _fake_transcribir), \
             patch("congreso_live.detector.vivos_de_interes", _vivos_falsos):
            resultado = lt.capturar_y_acumular_en_vivo(
                "TEST123", "Comision: Test", "Sesion de prueba",
                intervalo_seg=1, modelo="modelo-fake", db_path=db_path,
            )
    assert resultado["chunks"] == 2, resultado
    print("OK live_transcribe: un fallo transitorio de deteccion no corta la captura")


def _test_transcribir_vod():
    """transcribir_vod() sin tocar la red - mockea la descarga y la
    transcripcion, verifica que el texto queda guardado en
    sesiones_transcripciones. Este es el camino de backfill cuando la
    captura en vivo se perdio (ver congreso_live.cli backfill-vod)."""
    import tempfile
    from unittest.mock import patch

    import congreso_live.live_transcribe as lt

    def _fake_descargar(video_id):
        return "fake.wav"

    def _fake_transcribir(wav_path, modelo):
        return [{"start": 0, "end": 10, "text": "Se discutio el proyecto de ley X."}]

    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "test.db"
        with patch.object(lt, "descargar_audio_completo", _fake_descargar), \
             patch.object(lt, "transcribir_audio", _fake_transcribir):
            resultado = lt.transcribir_vod(
                "VOD123", "Comision: Salud", "Sesion de prueba",
                modelo="modelo-fake", db_path=db_path,
            )
        assert resultado["ok"] and resultado["chars"] > 0, resultado
        conn = sqlite3.connect(str(db_path))
        texto, duracion = conn.execute(
            "SELECT texto, duracion_seg FROM sesiones_transcripciones WHERE video_id='VOD123'"
        ).fetchone()
        conn.close()
    assert texto == "Se discutio el proyecto de ley X.", texto
    assert duracion == 10, duracion
    print("OK live_transcribe: transcribir_vod guarda el audio completo transcripto")


def _test_watch_and_transcribe_max_total():
    """watch_and_transcribe(max_total_minutos=...) debe arrancar un hilo
    por sesion en vivo y salir SOLO (sin Ctrl+C) apenas se cumple el
    limite - sin tocar la red (mockea vivos_de_interes y
    capturar_y_acumular_en_vivo; poll_seg=1 real segundo x ~2 vueltas,
    rapido y determinista sin mockear time.sleep - mockearlo hace que el
    loop gire sin freno mientras dura el test, generando miles de
    iteraciones inutiles antes de que se note el limite).

    Tambien cubre el aviso por WhatsApp de una sesion nueva (ver
    _avisar_si_no_avisado) - state.STATE_PATH apunta a un tmp file para
    no tocar el data/congreso_live_state.json real del repo."""
    import tempfile
    from pathlib import Path
    from unittest.mock import patch

    import congreso_live.live_transcribe as lt
    import congreso_live.state as st

    vistos = []

    def _fake_acumular(video_id, tipo, titulo, intervalo_seg):
        vistos.append(video_id)

    vivos_falsos = [{"id": "A", "tipo": "Comision: Test", "titulo": "Sesion A",
                     "url": "https://www.youtube.com/watch?v=A"}]
    tmp_state = Path(tempfile.mkdtemp()) / "congreso_live_state.json"
    with patch.object(lt, "capturar_y_acumular_en_vivo", _fake_acumular), \
         patch("congreso_live.detector.vivos_de_interes", lambda: vivos_falsos), \
         patch.object(st, "STATE_PATH", tmp_state):
        lt.watch_and_transcribe(intervalo_seg=1, poll_seg=1, max_total_minutos=1.5 / 60)
        assert "A" in st.load_state().get("alertados", []), "no quedo registrada como alertada"

    assert vistos and set(vistos) == {"A"}, vistos
    print("OK live_transcribe: watch_and_transcribe(max_total_minutos=...) transcribe y sale solo")


def _test_watch_and_transcribe_idle_exit():
    """Sin nada en vivo, watch_and_transcribe(idle_exit_minutos=...) debe
    salir sola apenas se cumple el tiempo ocioso - en vez de seguir
    poll-eando sin hacer nada hasta max_total_minutos (bug real
    encontrado en vivo 2026-09-15: una corrida de CI sin nada en vivo se
    quedaba ocupando el job, y bloqueando el siguiente disparo en la cola
    de concurrency, hasta 170 min por las puras)."""
    from unittest.mock import patch

    import congreso_live.live_transcribe as lt

    t0 = __import__("time").time()
    with patch("congreso_live.detector.vivos_de_interes", lambda: []):
        # max_total_minutos bien por encima de idle_exit_minutos - si
        # idle_exit_minutos algun dia se rompe, el test igual termina
        # rapido (por max_total_minutos) en vez de colgarse de verdad.
        lt.watch_and_transcribe(intervalo_seg=1, poll_seg=1,
                                max_total_minutos=0.1, idle_exit_minutos=1.5 / 60)
    tardo = __import__("time").time() - t0

    assert tardo < 5, f"salio por max_total_minutos, no por idle_exit_minutos ({tardo:.1f}s)"
    print("OK live_transcribe: watch_and_transcribe(idle_exit_minutos=...) sale sola sin nada en vivo")


def _test_avisar_si_no_avisado_no_duplica():
    """Bug real 2026-09-17: una sesion nueva descubierta a mitad de un job
    largo debe avisarse por WhatsApp (ver _avisar_si_no_avisado) - pero
    NO si cmd_check ya la habia alertado al arranque del mismo job
    (mismo dedupe, data/congreso_live_state.json)."""
    import tempfile
    from pathlib import Path
    from unittest.mock import patch

    import congreso_live.live_transcribe as lt
    import congreso_live.state as st

    v = {"id": "B", "tipo": "Pleno: Senado", "titulo": "Sesion B",
         "url": "https://www.youtube.com/watch?v=B"}
    tmp_state = Path(tempfile.mkdtemp()) / "congreso_live_state.json"
    enviados = []
    with patch.object(st, "STATE_PATH", tmp_state), \
         patch("congreso_live.notify.enviar_whatsapp", lambda msg: enviados.append(msg) or True):
        lt._avisar_si_no_avisado(v)
        assert len(enviados) == 1, "deberia avisar la primera vez"
        lt._avisar_si_no_avisado(v)
        assert len(enviados) == 1, "no deberia re-avisar la misma sesion (ya alertada)"
    print("OK live_transcribe: _avisar_si_no_avisado no duplica un aviso ya enviado")


if __name__ == "__main__":
    _demo()
    _test_killpg_mata_el_arbol_completo()
    _test_acumulacion()
    _test_avisar_si_no_avisado_no_duplica()
    _test_tolera_fallo_transitorio()
    _test_transcribir_vod()
    _test_watch_and_transcribe_max_total()
    _test_watch_and_transcribe_idle_exit()
