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
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path


def _ffmpeg_bin() -> Path:
    """imageio_ffmpeg trae un binario portable pero con nombre raro
    (ffmpeg-win-x86_64-vX.Y.exe) - yt-dlp con --ffmpeg-location busca
    literalmente "ffmpeg"/"ffmpeg.exe", asi que lo copiamos una vez a un
    directorio propio con el nombre esperado."""
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
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--ffmpeg-location", str(ffmpeg_local.parent),
        "-f", "bestaudio/best",
        "-o", str(clip_path),
        f"https://www.youtube.com/watch?v={video_id}",
    ]
    # Ver detector._ydl() para el porque: bloqueo de YouTube es por IP de
    # datacenter, WARP (gratis) lo esquiva - el workflow en CI exporta esto.
    proxy = os.environ.get("YT_DLP_PROXY")
    if proxy:
        cmd += ["--proxy", proxy]
    # subprocess.Popen + kill manual (no subprocess.run(timeout=...)):
    # yt-dlp lanza ffmpeg como su PROPIO subproceso para bajar streams
    # HLS. Con run(timeout=) Python mata solo el proceso hijo directo -
    # el ffmpeg nieto queda huerfano corriendo, y ademas run() con
    # capture_output=True se cuelga ESPERANDO EOF de un pipe que ese
    # huerfano todavia tiene abierto (bug real, encontrado en vivo
    # 2026-09-15: el boton se quedaba "cargando" para siempre). En
    # Windows, "taskkill /T" mata el arbol de procesos completo -
    # arregla ambos problemas de una.
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        proc.wait(timeout=segundos)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        else:
            proc.kill()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass

    part_path = clip_path.with_suffix(clip_path.suffix + ".part")
    src = part_path if part_path.exists() else clip_path
    if not src.exists() or src.stat().st_size < 10_000:
        return None

    wav_path = tmp_dir / "clip.wav"
    r = subprocess.run(
        [str(ffmpeg_local), "-y", "-i", str(src), "-ar", "16000", "-ac", "1", str(wav_path)],
        capture_output=True, timeout=30,
    )
    if r.returncode != 0 or not wav_path.exists():
        return None
    return wav_path


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
    t_inicio = time.time()
    try:
        while True:
            if max_minutos is not None and (time.time() - t_inicio) > max_minutos * 60:
                break
            vivos_ids = {v["id"] for v in vivos_de_interes()}
            if video_id not in vivos_ids:
                break  # la sesion termino (o nunca estuvo en vivo)

            wav = capturar_audio_en_vivo(video_id, segundos=intervalo_seg)
            if wav is None:
                continue
            if modelo is None:
                from faster_whisper import WhisperModel
                modelo = WhisperModel("small", device="cpu", compute_type="int8")
            segs = transcribir_audio(wav, modelo)
            nuevo_texto = " ".join(s["text"] for s in segs)
            if not nuevo_texto:
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


def watch_and_transcribe(intervalo_seg: int = 40, poll_seg: int = 60,
                         max_total_minutos: float | None = None) -> None:
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
    print(f"[live-watch] arrancando (poll cada {poll_seg}s, chunks de "
          f"{intervalo_seg}s). Ctrl+C para parar.")
    while True:
        if max_total_minutos is not None and (time.time() - t_inicio) > max_total_minutos * 60:
            print(f"[live-watch] limite de {max_total_minutos} min alcanzado, cerrando.")
            for t in hilos.values():
                t.join()
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

        for v in vivos:
            if v["id"] in hilos:
                continue
            print(f"[live-watch] nueva sesion en vivo: {v['tipo']} - {v['titulo']} ({v['id']})")
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
        [{"id": "TEST123"}], [{"id": "TEST123"}],
        [{"id": "TEST123"}], [],  # 4to check: la sesion ya termino
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


def _test_watch_and_transcribe_max_total():
    """watch_and_transcribe(max_total_minutos=...) debe arrancar un hilo
    por sesion en vivo y salir SOLO (sin Ctrl+C) apenas se cumple el
    limite - sin tocar la red (mockea vivos_de_interes y
    capturar_y_acumular_en_vivo; poll_seg=1 real segundo x ~2 vueltas,
    rapido y determinista sin mockear time.sleep - mockearlo hace que el
    loop gire sin freno mientras dura el test, generando miles de
    iteraciones inutiles antes de que se note el limite)."""
    from unittest.mock import patch

    import congreso_live.live_transcribe as lt

    vistos = []

    def _fake_acumular(video_id, tipo, titulo, intervalo_seg):
        vistos.append(video_id)

    vivos_falsos = [{"id": "A", "tipo": "Comision: Test", "titulo": "Sesion A"}]
    with patch.object(lt, "capturar_y_acumular_en_vivo", _fake_acumular), \
         patch("congreso_live.detector.vivos_de_interes", lambda: vivos_falsos):
        lt.watch_and_transcribe(intervalo_seg=1, poll_seg=1, max_total_minutos=1.5 / 60)

    assert vistos and set(vistos) == {"A"}, vistos
    print("OK live_transcribe: watch_and_transcribe(max_total_minutos=...) transcribe y sale solo")


if __name__ == "__main__":
    _demo()
    _test_acumulacion()
    _test_watch_and_transcribe_max_total()
