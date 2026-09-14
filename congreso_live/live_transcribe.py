"""Transcripcion en vivo (bajo demanda) de sesiones que estan transmitiendo
ahora mismo - yt-dlp + faster-whisper, 100% gratis, corre local.

No es un pipeline continuo 24/7 (eso requeriria un proceso corriendo todo
el tiempo en algun lado) - esto captura los ultimos N segundos de audio
real de un stream en vivo y los transcribe, para uso interactivo desde la
app (un boton "transcribir ahora").

Verificado en vivo 2026-09-14/15: funciona perfecto desde una IP local -
transcribio 52s de audio real de la Comision de Constitucion en 5s de
procesamiento (mas rapido que tiempo real, modelo "small" en CPU).

OJO - mismo bloqueo que ya documentamos para sync-transcripciones: las
IPs de datacenter (GitHub Actions, y muy probablemente Streamlit Cloud
tambien) estan marcadas por el anti-bot de YouTube. Este modulo solo esta
verificado funcionando desde una IP residencial/local.
"""
from __future__ import annotations

import os
import shutil
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


if __name__ == "__main__":
    _demo()
