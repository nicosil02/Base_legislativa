"""Tests de congreso_live/live_transcribe.py (sin red: captura, Whisper y
deteccion en vivo van mockeados)."""
import queue
import sqlite3
import time

import pytest

np = pytest.importorskip("numpy")

import congreso_live.live_transcribe as lt  # noqa: E402
import congreso_live.state as st  # noqa: E402
from congreso_live.live_transcribe import SR, corte_de_frase, detectar_votacion  # noqa: E402


@pytest.fixture
def sin_avisos(monkeypatch, tmp_path):
    """Estado de avisos en tmp y sin envios ni lectura de Seguimiento."""
    enviados = []
    monkeypatch.setattr(st, "STATE_PATH", tmp_path / "congreso_live_state.json")
    monkeypatch.setattr(st, "seguidas_activas", lambda: set())
    monkeypatch.setattr("congreso_live.notify.enviar_whatsapp", lambda msg: enviados.append(msg) or True)
    monkeypatch.setattr("congreso_live.agenda_preview.agenda_extra_para", lambda v: "")
    return enviados


def _fake_transcribir(textos):
    it = iter(textos)

    def f(audio, modelo, contexto=None):
        texto = next(it, "")
        return [{"start": 0, "end": 1, "text": texto}] if texto else []
    return f


def test_corte_de_frase():
    pytest.importorskip("faster_whisper")
    assert corte_de_frase(np.zeros(SR // 2, dtype=np.float32)) is None  # < 1 s: esperar
    assert corte_de_frase(np.zeros(3 * SR, dtype=np.float32)) == 0  # solo silencio


def test_detectar_votacion():
    # Frases reales: Senado PE y Asamblea EC.
    assert detectar_votacion("al voto el acuerdo", "votación cerrada han votado a favor 50 señores senadores")
    assert detectar_votacion("", "contamos con 88 votos afirmativos, 60 votos negativos")
    assert detectar_votacion("", "propongo pasar a un cuarto intermedio")
    # Ruido real que no debe avisar: actas y comentaristas de TV.
    assert not detectar_votacion("", "las actas han sido aprobadas señores senadores")
    assert not detectar_votacion("", "aprobó con ocho votos afirmativos este informe")
    e = detectar_votacion("x" * 2000 + " se vota el texto sustitutorio", " 60 votos a favor")
    assert "texto sustitutorio" in e and len(e) < 1300


def test_ffmpeg_bin_resuelve(monkeypatch):
    pytest.importorskip("imageio_ffmpeg")
    monkeypatch.delenv("FFMPEG_BIN", raising=False)
    p = lt._ffmpeg_bin()
    assert p.exists() and p.name in ("ffmpeg.exe", "ffmpeg")


def test_acumulacion(monkeypatch, tmp_path, sin_avisos):
    # El texto crece frase a frase y el loop corta tras 2 misses seguidos.
    vivos = iter([[{"id": "TEST123"}], [], []])

    def fake_abrir(video_id):
        cola = queue.Queue()
        for _ in range(3):  # 3 frases de 1 s y el stream se corta
            cola.put(np.zeros(SR, dtype=np.float32))
        cola.put(None)
        return cola, lambda: None

    monkeypatch.setattr(lt, "abrir_audio_en_vivo", fake_abrir)
    monkeypatch.setattr(lt, "corte_de_frase", lambda audio: len(audio))
    monkeypatch.setattr(lt, "transcribir_audio",
                        _fake_transcribir(["Primera parte de la sesion.", "Segunda parte, sigue hablando.", ""]))
    monkeypatch.setattr("congreso_live.detector.vivos_de_interes", lambda: next(vivos))
    db_path = tmp_path / "test.db"
    r = lt.capturar_y_acumular_en_vivo("TEST123", "Comision: Test", "Sesion de prueba",
                                       intervalo_seg=0, modelo="modelo-fake", db_path=db_path)
    assert r["chunks"] == 2 and r["duracion_seg"] == 2
    conn = sqlite3.connect(db_path)
    texto = conn.execute("SELECT texto FROM sesiones_transcripciones WHERE video_id='TEST123'").fetchone()[0]
    conn.close()
    assert texto == "Primera parte de la sesion. Segunda parte, sigue hablando."


def test_tolera_fallo_transitorio(monkeypatch, tmp_path, sin_avisos):
    # Vivo, UNA excepcion de deteccion, vivo de nuevo: no corta la captura.
    secuencia = iter([[{"id": "TEST123"}], "EXCEPCION", [{"id": "TEST123"}], [], []])
    aperturas = iter([True, False, True])  # el stream se cae y una reapertura falla

    def vivos():
        v = next(secuencia)
        if v == "EXCEPCION":
            raise RuntimeError("Sign in to confirm you're not a bot")
        return v

    def fake_abrir(video_id):
        if not next(aperturas):
            return None
        cola = queue.Queue()
        cola.put(np.zeros(SR, dtype=np.float32))
        cola.put(None)
        return cola, lambda: None

    monkeypatch.setattr(lt, "abrir_audio_en_vivo", fake_abrir)
    monkeypatch.setattr(lt, "corte_de_frase", lambda audio: len(audio))
    monkeypatch.setattr(lt, "transcribir_audio", _fake_transcribir(["Antes del fallo.", "Despues del fallo."]))
    monkeypatch.setattr("congreso_live.detector.vivos_de_interes", vivos)
    r = lt.capturar_y_acumular_en_vivo("TEST123", "Comision: Test", "Sesion de prueba",
                                       intervalo_seg=0, modelo="modelo-fake", db_path=tmp_path / "test.db")
    assert r["chunks"] == 2


def test_transcribir_vod(monkeypatch, tmp_path):
    monkeypatch.setattr(lt, "descargar_audio_completo", lambda video_id: "fake.wav")
    monkeypatch.setattr(lt, "transcribir_audio", lambda wav, modelo: [
        {"start": 0, "end": 10, "text": "Se discutio el proyecto de ley X."}])
    db_path = tmp_path / "test.db"
    r = lt.transcribir_vod("VOD123", "Comision: Salud", "Sesion de prueba",
                           modelo="modelo-fake", db_path=db_path)
    assert r["ok"] and r["chars"] > 0
    conn = sqlite3.connect(db_path)
    texto, duracion = conn.execute(
        "SELECT texto, duracion_seg FROM sesiones_transcripciones WHERE video_id='VOD123'").fetchone()
    conn.close()
    assert (texto, duracion) == ("Se discutio el proyecto de ley X.", 10)


def test_watch_and_transcribe_max_total(monkeypatch, sin_avisos):
    # Arranca un hilo por sesion en vivo, avisa una vez y sale solo al limite.
    vistos = []
    monkeypatch.setattr(lt, "capturar_y_acumular_en_vivo",
                        lambda video_id, tipo, titulo, intervalo_seg: vistos.append(video_id))
    vivos = [{"id": "A", "tipo": "Comision: Test", "titulo": "Sesion A",
              "url": "https://www.youtube.com/watch?v=A"}]
    monkeypatch.setattr("congreso_live.detector.vivos_de_interes", lambda: vivos)
    lt.watch_and_transcribe(intervalo_seg=1, poll_seg=1, max_total_minutos=1.5 / 60)
    assert "A" in st.load_state().get("alertados", [])
    assert vistos and set(vistos) == {"A"}
    assert len(sin_avisos) == 1


def test_watch_and_transcribe_idle_exit(monkeypatch):
    # Sin nada en vivo sale por idle_exit_minutos, no por max_total_minutos.
    monkeypatch.setattr("congreso_live.detector.vivos_de_interes", lambda: [])
    t0 = time.time()
    lt.watch_and_transcribe(intervalo_seg=1, poll_seg=1, max_total_minutos=0.1, idle_exit_minutos=1.5 / 60)
    assert time.time() - t0 < 5


def test_avisar_si_no_avisado_no_duplica(sin_avisos):
    v = {"id": "B", "tipo": "Pleno: Senado", "titulo": "Sesion B", "url": "https://www.youtube.com/watch?v=B"}
    lt._avisar_si_no_avisado(v)
    assert len(sin_avisos) == 1
    lt._avisar_si_no_avisado(v)
    assert len(sin_avisos) == 1
