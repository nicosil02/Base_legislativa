"""Transcripcion ordenada por turnos: quien habla y cuando.

1. Separa voces del audio (sherpa-onnx: pyannote + titanet, sin cuenta ni token).
2. Junta las frases de Whisper (con hora) en turnos por voz.
3. Gemma lee los turnos con la lista de legisladores y dice quien habla en cada uno.
   La etiqueta de voz falla (junta a dos personas o parte a una), por eso se nombra
   turno por turno y no voz por voz. Un legislador solo se nombra con pista fuerte
   (le dieron la palabra, se presenta o le agradecen por su nombre) y con el nombre
   exacto de la lista; los "a favor" sueltos de una votacion no se nombran (esos votos
   ya salen de las actas). Lo demas queda "Sin identificar".

Guarda en sesiones_turnos (parte "transcripciones" de proyectos.db, core/partes.py).

    python -m congreso_live.oradores pendientes [--max-min 150]   # sesiones recientes sin turnos
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
import urllib.request
from pathlib import Path

CACHE = Path.home() / ".cache" / "vali_oradores"
_REL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
MODELOS = {
    "segmentacion.tar.bz2": _REL + "speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2",
    "voz.onnx": _REL + "speaker-recongition-models/nemo_en_titanet_small.onnx",
}
UMBRAL = 0.85  # 28 voces en una comision de 68 min (0.6 con otro modelo daba 57)
POR_LLAMADA = 60  # turnos por lectura de Gemma
CARGOS = ("presiden", "secretari", "ministr", "viceministr", "director", "gerente", "jefe", "superintendent",
          "defensor", "fiscal", "alcalde", "gobernador", "invitad", "funcionari", "asesor", "representante")


def init_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS sesiones_turnos (
        video_id TEXT PRIMARY KEY, turnos TEXT NOT NULL, hecho_at TEXT NOT NULL)""")


def _modelos() -> tuple[Path, Path]:
    CACHE.mkdir(parents=True, exist_ok=True)
    seg = CACHE / "sherpa-onnx-pyannote-segmentation-3-0" / "model.onnx"
    if not seg.exists():
        import tarfile
        tar = CACHE / "segmentacion.tar.bz2"
        urllib.request.urlretrieve(MODELOS["segmentacion.tar.bz2"], tar)
        with tarfile.open(tar) as t:
            t.extractall(CACHE, filter="data")
        tar.unlink()
    voz = CACHE / "voz.onnx"
    if not voz.exists():
        urllib.request.urlretrieve(MODELOS["voz.onnx"], voz)
    return seg, voz


def voces(audio) -> list[tuple[float, float, int]]:
    """[(inicio, fin, voz)] de un arreglo float32 a 16 kHz."""
    import sherpa_onnx
    seg, voz = _modelos()
    cfg = sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(model=str(seg)), num_threads=4),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(voz), num_threads=4),
        clustering=sherpa_onnx.FastClusteringConfig(num_clusters=-1, threshold=UMBRAL),
        min_duration_on=0.3, min_duration_off=0.5)
    r = sherpa_onnx.OfflineSpeakerDiarization(cfg).process(audio).sort_by_start_time()
    return [(s.start, s.end, s.speaker) for s in r]


def turnos(frases: list[dict], tramos: list[tuple[float, float, int]]) -> list[dict]:
    """Frases de Whisper [{start, end, text}] juntas por voz: [{voz, ini, texto}]."""
    out = []
    for f in frases:
        solape: dict[int, float] = {}
        for a, b, k in tramos:
            o = min(f["end"], b) - max(f["start"], a)
            if o > 0:
                solape[k] = solape.get(k, 0) + o
        k = max(solape, key=solape.get) if solape else -1
        if out and out[-1]["voz"] == k:
            out[-1]["texto"] += " " + f["text"]
        else:
            out.append({"voz": k, "ini": round(f["start"]), "texto": f["text"]})
    return out


def _gente(tipo: str) -> list[str]:
    from consultas.integrantes import integrantes
    pais = "EC" if tipo.endswith("(EC)") else "PE"
    return sorted(p["nombre"] for p in integrantes() if p["pais"] == pais)


def _prompt(ts: list[dict], desde: int, gente: list[str], tipo: str) -> str:
    corto = lambda t: t if len(t) < 700 else t[:450] + " [...] " + t[-250:]
    texto = "\n\n".join(f"[{desde + i}] VOZ {t['voz']} {hora(t['ini'])}\n{corto(t['texto'])}" for i, t in enumerate(ts))
    return f"""Transcripcion automatica de una sesion ({tipo}) separada en turnos numerados. La etiqueta de VOZ
la pone un programa que separa voces y FALLA a veces: puede juntar a dos personas o partir a una. Usala solo
como pista. La transcripcion escribe mal apellidos.

Para CADA turno di quien habla. Quien conduce la sesion es "Presidencia"; quien toma lista o lee la votacion es
"Secretaria tecnica". Invitados: su cargo (ej. "Ministro de Comercio Exterior y Turismo", "Directora general").
Un legislador SOLO si hay pista fuerte: le dieron la palabra por su nombre al final del turno anterior, se
presenta, o le agradecen por su nombre al inicio del turno siguiente. Entonces copia su nombre EXACTO de esta
lista y ningun otro: {"; ".join(gente)}
Sin pista fuerte: "desconocido". No adivines por el tema.

Turnos:
{texto}"""


_ESQ = {"type": "array", "items": {"type": "object", "properties": {
    "turno": {"type": "integer"}, "quien": {"type": "string"}}, "required": ["turno", "quien"]}}


def nombrar(ts: list[dict], tipo: str, generar=None, espera: int = 65) -> list[dict]:
    """Agrega "quien" a cada turno ("" = sin identificar). Nunca falla: si Gemma no
    responde, esos turnos quedan con "pendiente" y renombrar() los retoma despues.
    Solo pide los bloques que tienen turnos sin nombre o pendientes."""
    from core import llm
    generar = generar or (lambda p: llm.generar(p, modelo=llm.GEMMA, json=True, schema=_ESQ, respaldo=False))
    gente = _gente(tipo)
    lista = set(gente)
    for i in range(0, len(ts), POR_LLAMADA):
        bloque = ts[i:i + POR_LLAMADA]
        if all("quien" in t and not t.get("pendiente") for t in bloque):
            continue
        desde = max(0, i - 2)  # dos turnos de antes: ahi suelen dar la palabra
        quien = None
        for intento in (1, 2):  # el cupo de Gemma es por minuto: esperar uno y reintentar
            try:
                quien = {x["turno"]: str(x.get("quien") or "").strip()
                         for x in json.loads(generar(_prompt(ts[desde:i + POR_LLAMADA], desde, gente, tipo)))
                         if isinstance(x, dict) and isinstance(x.get("turno"), int) and x["turno"] >= i}
                break
            except Exception as e:
                print(f"[oradores] Gemma fallo en turnos {i}+ (intento {intento}): {str(e)[:150]}")
                if intento == 1 and espera:
                    time.sleep(espera)
        for n, t in enumerate(bloque, start=i):
            if quien is None:
                t.setdefault("quien", "")
                t["pendiente"] = True
                continue
            t.pop("pendiente", None)
            q = quien.get(n, "")
            legislador = q in lista
            if q.lower() in ("desconocido", "") or ("," in q and not legislador):
                q = ""  # vacio o nombre que no esta en la lista: inventado
            elif legislador and len(t["texto"].split()) < 6:
                q = ""  # "a favor" suelto: el voto ya sale de las actas
            elif not legislador and not any(c in q.lower() for c in CARGOS):
                q = ""  # ni de la lista ni un cargo: no se confia
            t["quien"] = q
    return ts


def renombrar(conn: sqlite3.Connection) -> int:
    """Nombra los turnos que quedaron pendientes (Gemma sin cupo). No baja audio."""
    init_schema(conn)
    hechas = 0
    for vid, turnos_json, tipo in conn.execute(
            """SELECT u.video_id, u.turnos, t.tipo FROM sesiones_turnos u
               JOIN sesiones_transcripciones t USING (video_id)
               WHERE u.turnos LIKE '%"pendiente": true%'""").fetchall():
        ts = nombrar(json.loads(turnos_json), tipo)
        conn.execute("UPDATE sesiones_turnos SET turnos = ? WHERE video_id = ?",
                     (json.dumps(ts, ensure_ascii=False), vid))
        conn.commit()
        faltan = sum(1 for t in ts if t.get("pendiente"))
        hechas += not faltan
        print(f"[oradores] {vid}: renombrado, {faltan} turnos siguen pendientes")
    return hechas


def hora(s: int) -> str:
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"


def como_texto(ts: list[dict]) -> str:
    """Los turnos legibles: "Nombre (0:19:39)" y su texto, separados por linea en blanco."""
    return "\n\n".join(f"{t['quien'] or 'Sin identificar'} ({hora(t['ini'])})\n{t['texto']}" for t in ts)


def procesar(conn: sqlite3.Connection, video_id: str, tipo: str, audio, frases: list[dict]) -> int:
    """Separa voces, arma turnos, los nombra y los guarda. Devuelve cuantos turnos."""
    import numpy as np
    if not hasattr(audio, "dtype"):
        audio = _leer_wav(audio)
    ts = nombrar(turnos(frases, voces(np.asarray(audio, dtype=np.float32))), tipo)
    init_schema(conn)
    conn.execute("INSERT OR REPLACE INTO sesiones_turnos VALUES (?,?,datetime('now'))",
                 (video_id, json.dumps(ts, ensure_ascii=False)))
    conn.commit()
    return len(ts)


def _leer_wav(path) -> "np.ndarray":
    import wave

    import numpy as np
    with wave.open(str(path)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768


def pendientes(max_min: float = 150, dias: int = 3, db_path=None) -> int:
    """Sesiones de los ultimos `dias` sin turnos (las transcritas en vivo): baja el audio,
    transcribe con hora y procesa, hasta `max_min` minutos. Las mas nuevas primero."""
    from congreso_live.facebook_ec import url_video
    from congreso_live.live_transcribe import cargar_whisper, descargar_audio_completo, transcribir_audio
    from congreso_live.transcripciones import _find_db_path
    conn = sqlite3.connect(str(db_path or _find_db_path()), timeout=30)
    init_schema(conn)
    renombrar(conn)
    filas = conn.execute(
        """SELECT video_id, tipo FROM sesiones_transcripciones t
           WHERE fecha >= date('now', ?) AND duracion_seg >= 600 AND tipo NOT LIKE 'Entrevista%'
             AND video_id NOT IN (SELECT video_id FROM sesiones_turnos)
           ORDER BY fecha DESC, tipo NOT LIKE '%(EC)'""", (f"-{dias} days",)).fetchall()
    print(f"[oradores] {len(filas)} sesiones sin turnos")
    t0, hechas, modelo = time.time(), 0, None
    for vid, tipo in filas:
        if (time.time() - t0) / 60 > max_min:
            break
        wav = descargar_audio_completo(vid, url_video(vid))
        if wav is None:
            print(f"[oradores] {vid}: sin audio")
            continue
        modelo = modelo or cargar_whisper()
        try:
            n = procesar(conn, vid, tipo, wav, transcribir_audio(wav, modelo))
        except Exception as e:
            print(f"[oradores] {vid}: fallo ({str(e)[:200]})")
            continue
        finally:
            wav.unlink(missing_ok=True)
        hechas += 1
        print(f"[oradores] {vid} ({tipo}): {n} turnos, {(time.time() - t0) / 60:.0f} min")
    conn.close()
    return hechas


if __name__ == "__main__":
    import sys
    if sys.argv[1:2] == ["pendientes"]:
        mx = float(sys.argv[sys.argv.index("--max-min") + 1]) if "--max-min" in sys.argv else 150
        print(f"[oradores] {pendientes(mx)} sesiones procesadas")
        raise SystemExit
    fr = [{"start": 0, "end": 2, "text": "Tiene la palabra la diputada Paz."}, {"start": 2, "end": 3, "text": "Gracias."},
          {"start": 3, "end": 9, "text": "Presidente, quiero decir que el proyecto es bueno para mi region."},
          {"start": 9, "end": 10, "text": "A favor."}]
    ts = turnos(fr, [(0, 2.1, 0), (2.1, 9, 1), (9, 10, 2)])
    assert [t["voz"] for t in ts] == [0, 1, 2] and ts[1]["texto"].startswith("Gracias. Presidente"), ts
    import consultas.integrantes as ci
    ci.integrantes = lambda: [{"pais": "PE", "nombre": "PAZ ROJAS, ANA"}]
    resp = json.dumps([{"turno": 0, "quien": "Presidencia"}, {"turno": 1, "quien": "PAZ ROJAS, ANA"},
                       {"turno": 2, "quien": "PAZ ROJAS, ANA"}])
    ts = nombrar(ts, "Comision: Salud", generar=lambda p: resp)
    assert [t["quien"] for t in ts] == ["Presidencia", "PAZ ROJAS, ANA", ""], ts  # "A favor." suelto no se nombra
    ts2 = nombrar([{"voz": 0, "ini": 0, "texto": "uno dos tres cuatro cinco seis siete"}], "Comision: Salud",
                  generar=lambda p: json.dumps([{"turno": 0, "quien": "PEREZ, JUAN"}]))
    assert ts2[0]["quien"] == "", ts2  # no esta en la lista: inventado
    assert como_texto(ts).startswith("Presidencia (0:00:00)\nTiene la palabra")
    print("ok")
