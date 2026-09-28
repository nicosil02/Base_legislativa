"""Videos de YouTube donde aparecen las autoridades que seguimos
(entrevistas en TV, declaraciones, conferencias). Pedido de Nicolas
2026-09-28: "vinelli tuvo entrevista este finde.. quiero poder descargar
ese video y hacer la transcripcion y resumen".

Flujo:
1. `buscar()` (backfill-auto.yml, con WARP) busca en YouTube lo subido
   ESTA SEMANA con el nombre de cada autoridad y lo guarda en la tabla
   videos_autoridades. La tabla viaja a `datos` via merge_db.
2. La pagina de Noticias lista esos videos. El boton "Transcribir" crea
   data/videos_pedidos/<video_id>.json (Contents API, archivo nuevo, sin
   read-modify-write) y ese push dispara videos-pedidos.yml.
3. videos-pedidos.yml (backfill-auto --solo-pedidos) los transcribe con el mismo
   camino que las sesiones (captions o Whisper), con tipo
   "Entrevista: <autoridad>". La rutina de resumenes los resume igual que
   cualquier otra transcripcion.

Uso: python -m noticias.videos buscar DB_PATH
"""
from __future__ import annotations

import base64
import json
import logging
import os
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

# (nombre para buscar, cargo). Nombres sacados de las noticias reales de la
# base (2026-09-28). Editar aca cuando cambie el gabinete.
AUTORIDADES: dict[str, list[tuple[str, str]]] = {
    "PE": [
        ("Keiko Fujimori", "Presidenta"),
        ("Luis Galarreta", "Premier"),
        ("Marco Vinelli", "Ministro de Desarrollo Agrario"),
        ("Luis Dyer", "Ministro de Salud"),
        ("Elmer Cuba", "Ministro de Economía"),
        ("Vladimiro Huaroc", "Ministro del Ambiente"),
        ("Rogers Valencia", "Ministro de Comercio Exterior"),
        ("César Astudillo", "Ministro del Interior"),
        ("Carlos Espá", "Canciller"),
    ],
    "EC": [
        ("Daniel Noboa", "Presidente"),
        ("John Reimberg", "Ministro del Interior"),
        ("Juan Carlos Aveiga", "Ministro de Salud"),
        ("Bernardo Cordovez", "Ministro de Desarrollo Económico y Productivo"),
        ("Roberto Luque", "Ministro de Infraestructura y Transporte"),
    ],
}

# Filtro "subidos esta semana" de YouTube. hl/gl en español para que los
# titulos no vengan auto-traducidos al ingles.
_SP_ESTA_SEMANA = "EgIIAw%253D%253D"
POR_AUTORIDAD = 20
DURACION_MIN = 120  # ponytail: corta shorts/clips sueltos; bajar si se pierden declaraciones cortas utiles
PEDIDOS_DIR = "data/videos_pedidos"

SCHEMA = """
CREATE TABLE IF NOT EXISTS videos_autoridades (
  video_id TEXT PRIMARY KEY,
  pais TEXT NOT NULL,
  autoridad TEXT NOT NULL,
  cargo TEXT,
  titulo TEXT,
  canal TEXT,
  duracion_seg INTEGER,
  first_seen_at TEXT NOT NULL
)"""


def _norm(s: str | None) -> str:
    from congreso_live.detector import _norm as n
    return n(s)


def es_relevante(entry: dict, nombre: str) -> bool:
    """El apellido tiene que estar en el titulo (la busqueda de YouTube
    tambien trae videos que solo lo nombran en la descripcion o en los
    tags) y no puede ser un clip de segundos."""
    apellido = _norm(nombre.split()[-1])
    return (apellido in _norm(entry.get("title"))
            and (entry.get("duration") or 0) >= DURACION_MIN
            and entry.get("live_status") != "is_live"
            # canal con el mismo nombre = homonimo (caso real: un musico
            # "Marco Vinelli" con su propio canal, video de 2021)
            and _norm(entry.get("channel")) != _norm(nombre))


def _buscar_youtube(nombre: str, pais: str) -> list[dict]:
    from congreso_live.detector import _ydl
    url = ("https://www.youtube.com/results?search_query="
           + urllib.parse.quote(f'"{nombre}"') + f"&sp={_SP_ESTA_SEMANA}&hl=es&gl={pais}")
    opts = {"extract_flat": True, "playlistend": POR_AUTORIDAD,
            "extractor_args": {"youtube": {"lang": ["es"]}}}  # sin esto los titulos llegan traducidos al ingles
    with _ydl(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    return info.get("entries") or []


def buscar(db_path: str | Path) -> int:
    """Guarda los videos nuevos de todas las autoridades. Devuelve cuantos
    agrego. Si falla una autoridad (bloqueo de YouTube) sigue con las demas."""
    conn = sqlite3.connect(str(db_path))
    conn.execute(SCHEMA)
    ahora = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    nuevos = 0
    for pais, lista in AUTORIDADES.items():
        for nombre, cargo in lista:
            try:
                entries = _buscar_youtube(nombre, pais)
            except Exception as e:
                log.warning("busqueda de %s fallo: %s", nombre, e)
                continue
            for e in entries:
                if not e.get("id") or not es_relevante(e, nombre):
                    continue
                cur = conn.execute(
                    "INSERT OR IGNORE INTO videos_autoridades VALUES (?,?,?,?,?,?,?,?)",
                    (e["id"], pais, nombre, cargo, e.get("title"), e.get("channel"),
                     e.get("duration"), ahora))
                nuevos += cur.rowcount
    conn.commit()
    conn.close()
    return nuevos


def tipo_de(autoridad: str, pais: str) -> str:
    """tipo para sesiones_transcripciones. Las paginas de Agenda excluyen
    'Entrevista:%' para no mezclar esto con sesiones del Congreso."""
    return f"Entrevista: {autoridad}" + (" (EC)" if pais == "EC" else "")


# ---------- pedidos de transcripcion (boton en la pagina de Noticias) ----------

def pedir_transcripcion(video_id: str, autoridad: str, pais: str, titulo: str) -> None:
    """Crea data/videos_pedidos/<video_id>.json en GitHub. Ese push dispara
    backfill-auto.yml. Un archivo por pedido: no hay que leer ni mezclar
    nada, y pedir dos veces el mismo video da 422 (ya existe), que se
    toma como exito."""
    token, repo = os.environ.get("GH_TOKEN"), os.environ.get("GH_REPO")
    if not token or not repo:
        raise RuntimeError("Faltan GH_TOKEN/GH_REPO para pedir la transcripción")
    contenido = json.dumps({"video_id": video_id, "autoridad": autoridad, "pais": pais,
                            "titulo": titulo}, ensure_ascii=False)
    body = {"message": f"videos: pedir transcripcion {video_id}",
            "content": base64.b64encode(contenido.encode("utf-8")).decode("ascii"),
            "branch": os.environ.get("GH_BRANCH", "main")}
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/contents/{PEDIDOS_DIR}/{video_id}.json",
        data=json.dumps(body).encode("utf-8"), method="PUT",
        headers={"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json",
                 "Content-Type": "application/json", "User-Agent": "ValiIntelligence/1.0"})
    try:
        urllib.request.urlopen(req, timeout=15)
    except urllib.error.HTTPError as e:
        if e.code != 422:
            raise RuntimeError(f"GitHub PUT {e.code}: {e.read()[:200]!r}") from None


def pedidos(raiz: str | Path = ".") -> list[dict]:
    """Pedidos como candidatos de backfill_auto ({id, titulo, tipo})."""
    salida = []
    for p in sorted(Path(raiz, PEDIDOS_DIR).glob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        salida.append({"id": d["video_id"], "titulo": d.get("titulo") or "",
                       "tipo": tipo_de(d["autoridad"], d.get("pais", "PE"))})
    return salida


def _demo():
    import tempfile
    assert es_relevante({"title": "#Entrevista | Marco Vinelli - Ministro", "duration": 990}, "Marco Vinelli")
    assert es_relevante({"title": "MINISTRO VINELLI EN CUARTO PODER", "duration": 900}, "Marco Vinelli")
    assert not es_relevante({"title": "Marco Vinelli: El Niño", "duration": 35}, "Marco Vinelli")
    assert not es_relevante({"title": "KEIKO'S PLAN B", "duration": 118}, "Marco Vinelli")
    assert not es_relevante({"title": "César Astudillo en vivo", "duration": 900, "live_status": "is_live"},
                            "César Astudillo")
    assert not es_relevante({"title": "Marco Vinelli (PE) - Casa Lunario", "duration": 3492,
                             "channel": "Marco Vinelli"}, "Marco Vinelli")
    assert tipo_de("Daniel Noboa", "EC") == "Entrevista: Daniel Noboa (EC)"
    with tempfile.TemporaryDirectory() as td:
        d = Path(td, PEDIDOS_DIR)
        d.mkdir(parents=True)
        (d / "abc.json").write_text(json.dumps(
            {"video_id": "abc", "autoridad": "Marco Vinelli", "pais": "PE", "titulo": "t"}), encoding="utf-8")
        assert pedidos(td) == [{"id": "abc", "titulo": "t", "tipo": "Entrevista: Marco Vinelli"}]
    print("OK videos: filtro por apellido/duracion, tipo y lectura de pedidos")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) == 3 and sys.argv[1] == "buscar":
        print(f"videos: {buscar(sys.argv[2])} nuevo(s)")
    else:
        _demo()
