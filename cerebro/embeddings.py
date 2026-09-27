"""Busqueda por significado sobre TODO el corpus (PLs PE/EC, noticias,
sesiones transcritas) con embeddings de Gemini + sqlite-vec.

Por que: la relevancia por cliente y el agrupado de noticias usaban TF-IDF
(palabras sueltas) - de ahi los falsos positivos por homonimos que se
arreglaron a mano uno por uno ("tributo" homenaje vs impuesto, "presidente"
de club de futbol, etc.). Prueba real 2026-09-27 (_test_embeddings.yml,
contra el perfil de Bayer): gemini-embedding-2 puso lo agricola en 0.68-0.72
y lo ajeno en 0.43-0.53 ("Rinden tributo a Chabuca Granda" en 0.43).

Donde vive: data/cerebro.db, FUERA de git a proposito - son vectores (casi
no comprimen) y el repo ya se inflo a 14 GB por las versiones de
proyectos.db.gz. Se publica como adjunto del release "cerebro" (se pisa en
cada actualizacion, sin historial) - ver .github/workflows/cerebro.yml y
descargar_si_falta().

Uso:
    python -m cerebro.embeddings sincronizar      # CI: embebe lo nuevo
    python -m cerebro.embeddings buscar "biometria datos personales"
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import struct
import sys
import time
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CEREBRO_DB = REPO_ROOT / "data" / "cerebro.db"
RELEASE_URL = "https://github.com/nicosil02/Base_legislativa/releases/download/cerebro/cerebro.db"

MODELO = "gemini-embedding-2"
DIM = 256  # MRL: 256 alcanza para separar bien (prueba de arriba) y ocupa 1/12 de 3072
LOTE = 100  # tope real de la API por pedido (400 INVALID_ARGUMENT arriba de 100)
MAX_CHARS = 2000


# ------------------------------------------------------------------ Gemini

def _cliente_gemini():
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        try:
            import streamlit as st
            key = st.secrets.get("GEMINI_API_KEY")
        except Exception:
            key = None
    if not key:
        raise RuntimeError("Falta GEMINI_API_KEY")
    from google import genai
    return genai.Client(api_key=key)


def embeber(textos: list[str]) -> list[list[float]]:
    """Un vector normalizado por texto. OJO: con gemini-embedding-2 hay que
    mandar cada texto como su propio Content - una lista de strings la API
    la toma como UN solo contenido multi-parte y devuelve 1 vector para todo
    el lote (verificado en la prueba de arriba)."""
    from google.genai import types

    cliente = _cliente_gemini()
    cfg = types.EmbedContentConfig(output_dimensionality=DIM)
    out: list[list[float]] = []
    for i in range(0, len(textos), LOTE):
        lote = [types.Content(parts=[types.Part(text=(t or " ")[:MAX_CHARS])])
                for t in textos[i:i + LOTE]]
        for intento in range(6):
            try:
                resp = cliente.models.embed_content(model=MODELO, contents=lote, config=cfg)
                break
            except Exception as e:  # 429 del tier gratuito: esperar y reintentar
                if intento == 5 or "429" not in str(e) and "RESOURCE_EXHAUSTED" not in str(e):
                    raise
                time.sleep(20 * (intento + 1))
        for e in resp.embeddings:
            v = e.values
            n = sum(x * x for x in v) ** 0.5 or 1.0
            out.append([x / n for x in v])
    return out


def _blob(v: list[float]) -> bytes:
    return struct.pack(f"{len(v)}f", *v)


# ------------------------------------------------------------------ DB

def conectar(path: Path | None = None) -> sqlite3.Connection:
    import sqlite_vec

    path = path or CEREBRO_DB
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.executescript(f"""
        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY,
            clave TEXT UNIQUE NOT NULL,   -- ej. pl_PE_2026_438, noticia_123, sesion_fb_111
            tipo TEXT NOT NULL,           -- pl | noticia | sesion
            pais TEXT NOT NULL,           -- PE | EC
            titulo TEXT, fecha TEXT, url TEXT, extra TEXT,
            hash TEXT NOT NULL            -- del texto embebido: si cambia, se re-embebe
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS vec_items USING vec0(
            embedding float[{DIM}] distance_metric=cosine,
            tipo text, pais text
        );
    """)
    return conn


def descargar_si_falta(path: Path | None = None, max_edad_seg: int = 3 * 3600) -> Path | None:
    """Para la app (Streamlit Cloud): baja el cerebro.db publicado si no hay
    copia local o si la local tiene mas de max_edad_seg. None si no se pudo
    (sin red, release todavia no creado)."""
    path = path or CEREBRO_DB
    if path.exists() and time.time() - path.stat().st_mtime < max_edad_seg:
        return path
    try:
        tmp = path.with_suffix(".tmp")
        path.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(RELEASE_URL, timeout=60) as r, open(tmp, "wb") as f:
            f.write(r.read())
        tmp.replace(path)
        return path
    except Exception as e:
        print(f"[cerebro] no pude bajar {RELEASE_URL}: {e}")
        return path if path.exists() else None


# ------------------------------------------------------------------ corpus

def _db(nombre: str) -> Path | None:
    for p in (REPO_ROOT / nombre, Path.cwd() / nombre):
        if p.exists() and p.stat().st_size > 0:
            return p
    return None


def corpus() -> list[dict]:
    """Todo lo que el cerebro conoce: {clave, tipo, pais, titulo, fecha, url,
    extra, texto}. `texto` es lo que se embebe."""
    items: list[dict] = []
    pe = _db("proyectos.db")
    if pe:
        c = sqlite3.connect(f"file:{pe}?mode=ro", uri=True)
        for r in c.execute("SELECT per_par_id, pley_num, proyecto_ley, titulo, sumilla, "
                           "fec_presentacion, tema, estado, url_portal FROM proyectos"):
            items.append({"clave": f"pl_PE_{r[0]}_{r[1]}", "tipo": "pl", "pais": "PE",
                          "titulo": f"PL {r[2]}: {r[3]}", "fecha": (r[5] or "")[:10], "url": r[8],
                          "extra": json.dumps({"tema": r[6], "estado": r[7]}, ensure_ascii=False),
                          "texto": f"{r[3] or ''}. {r[4] or ''}"})
        try:
            filas = c.execute("""SELECT n.id, n.titulo, n.resumen, n.url,
                                        COALESCE(n.fecha_pub, n.first_seen_at), f.pais, f.nombre
                                 FROM noticias n JOIN noticias_fuentes f ON f.id = n.fuente_id""").fetchall()
        except sqlite3.OperationalError:
            filas = []
        for r in filas:
            items.append({"clave": f"noticia_{r[0]}", "tipo": "noticia", "pais": r[5] or "PE",
                          "titulo": r[1], "fecha": (r[4] or "")[:10], "url": r[3],
                          "extra": json.dumps({"fuente": r[6]}, ensure_ascii=False),
                          "texto": f"{r[1] or ''}. {r[2] or ''}"})
        try:
            ses = c.execute("SELECT video_id, tipo, titulo, fecha, texto FROM sesiones_transcripciones").fetchall()
        except sqlite3.OperationalError:
            ses = []
        c.close()
        resumenes = {}
        rpath = REPO_ROOT / "data" / "transcripciones_resumenes.json"
        if rpath.exists():
            resumenes = {r["video_id"]: r for r in json.loads(rpath.read_text(encoding="utf-8"))}
        from congreso_live.facebook_ec import url_video
        for vid, tipo_ses, titulo, fecha, texto in ses:
            res = resumenes.get(vid) or {}
            # Con resumen: resumen + ideas (lo mas denso en significado). Sin
            # resumen todavia: el comienzo de la transcripcion; se re-embebe
            # solo cuando llegue el resumen (cambia el hash).
            cuerpo = (res.get("resumen", "") + " " + " ".join(res.get("ideas_clave", []))).strip() \
                or (texto or "")[:MAX_CHARS]
            items.append({"clave": f"sesion_{vid}", "tipo": "sesion",
                          "pais": "EC" if (tipo_ses or "").endswith("(EC)") else "PE",
                          "titulo": f"{tipo_ses} · {titulo}", "fecha": fecha, "url": url_video(vid),
                          "extra": json.dumps({"organo": tipo_ses}, ensure_ascii=False),
                          "texto": f"{titulo}. {cuerpo}"})
    ec = _db("proyectos_ec.db")
    if ec:
        c = sqlite3.connect(f"file:{ec}?mode=ro", uri=True)
        for r in c.execute("SELECT n_tramite, titulo, estado, comision_asignada, "
                           "fec_presentacion, tema, url_portal FROM proyectos"):
            items.append({"clave": f"pl_EC_{r[0]}", "tipo": "pl", "pais": "EC",
                          "titulo": f"PL {r[0]}: {r[1]}", "fecha": (r[4] or "")[:10], "url": r[6],
                          "extra": json.dumps({"tema": r[5], "estado": r[2], "comision": r[3]},
                                              ensure_ascii=False),
                          "texto": f"{r[1] or ''}. Comision: {r[3] or '-'}"})
        c.close()
    return items


def _hash(texto: str) -> str:
    return hashlib.sha1(texto[:MAX_CHARS].encode("utf-8")).hexdigest()[:16]


def sincronizar(max_nuevos: int | None = None) -> dict:
    """Embebe solo lo nuevo o cambiado (por hash del texto). Idempotente."""
    conn = conectar()
    ya = {r["clave"]: (r["id"], r["hash"]) for r in conn.execute("SELECT id, clave, hash FROM items")}
    pendientes = [it for it in corpus() if ya.get(it["clave"], (None, None))[1] != _hash(it["texto"])]
    if max_nuevos:
        pendientes = pendientes[:max_nuevos]
    hechos = 0
    for i in range(0, len(pendientes), LOTE):
        lote = pendientes[i:i + LOTE]
        vecs = embeber([it["texto"] for it in lote])
        for it, v in zip(lote, vecs):
            previo = ya.get(it["clave"])
            if previo:
                conn.execute("DELETE FROM vec_items WHERE rowid=?", (previo[0],))
                conn.execute("DELETE FROM items WHERE id=?", (previo[0],))
            cur = conn.execute(
                "INSERT INTO items (clave, tipo, pais, titulo, fecha, url, extra, hash) VALUES (?,?,?,?,?,?,?,?)",
                (it["clave"], it["tipo"], it["pais"], it["titulo"], it["fecha"], it["url"],
                 it["extra"], _hash(it["texto"])))
            conn.execute("INSERT INTO vec_items (rowid, embedding, tipo, pais) VALUES (?,?,?,?)",
                         (cur.lastrowid, _blob(v), it["tipo"], it["pais"]))
        conn.commit()
        hechos += len(lote)
        print(f"[cerebro] {hechos}/{len(pendientes)} embebidos")
    total = conn.execute("SELECT count(*) FROM items").fetchone()[0]
    conn.close()
    return {"nuevos": hechos, "total": total}


# ------------------------------------------------------------------ consultas

def buscar(consulta: str, k: int = 20, tipo: str | None = None, pais: str | None = None,
           conn: sqlite3.Connection | None = None) -> list[dict]:
    """Los k items mas parecidos en significado a `consulta` (texto libre).
    `similitud` = 1 - distancia coseno (1 = identico)."""
    conn = conn or conectar()
    return vecinos(embeber([consulta])[0], k=k, tipo=tipo, pais=pais, conn=conn)


def vecinos(vector: list[float], k: int = 20, tipo: str | None = None,
            pais: str | None = None, conn: sqlite3.Connection | None = None) -> list[dict]:
    conn = conn or conectar()
    filtros, params = "", [_blob(vector), k]
    if tipo:
        filtros += " AND v.tipo = ?"
        params.append(tipo)
    if pais:
        filtros += " AND v.pais = ?"
        params.append(pais)
    filas = conn.execute(
        f"""SELECT i.*, v.distance FROM vec_items v JOIN items i ON i.id = v.rowid
            WHERE v.embedding MATCH ? AND k = ? {filtros}
            ORDER BY v.distance""", params).fetchall()
    return [{**dict(r), "similitud": round(1 - r["distance"], 4)} for r in filas]


def vector_de(clave: str, conn: sqlite3.Connection | None = None) -> list[float] | None:
    conn = conn or conectar()
    r = conn.execute("SELECT v.embedding FROM vec_items v JOIN items i ON i.id = v.rowid "
                     "WHERE i.clave = ?", (clave,)).fetchone()
    return list(struct.unpack(f"{DIM}f", r[0])) if r else None


# ------------------------------------------------------------------ self-check

def _demo():
    """Sin red: vectores falsos, prueba insert/KNN/filtros de sqlite-vec."""
    import tempfile
    from unittest.mock import patch

    def _fake(textos):
        out = []
        for t in textos:
            v = [0.0] * DIM
            v[0 if "agro" in t else 1 if "futbol" in t else 2] = 1.0
            out.append(v)
        return out

    tmp = Path(tempfile.mkdtemp()) / "c.db"
    items = [
        {"clave": "a", "tipo": "noticia", "pais": "PE", "titulo": "A", "fecha": "", "url": "", "extra": "{}", "texto": "agro plaguicidas"},
        {"clave": "b", "tipo": "noticia", "pais": "PE", "titulo": "B", "fecha": "", "url": "", "extra": "{}", "texto": "futbol clasico"},
        {"clave": "c", "tipo": "pl", "pais": "EC", "titulo": "C", "fecha": "", "url": "", "extra": "{}", "texto": "agro semillas"},
    ]
    with patch.dict(globals(), {"CEREBRO_DB": tmp, "embeber": _fake, "corpus": lambda: items}):
        r = sincronizar()
        assert r == {"nuevos": 3, "total": 3}, r
        assert sincronizar()["nuevos"] == 0  # idempotente: nada cambio
        items[0]["texto"] = "agro plaguicidas SENASA"
        assert sincronizar()["nuevos"] == 1  # cambio el texto -> se re-embebe solo ese
        top = buscar("agro", k=3)
        assert {t["clave"] for t in top[:2]} == {"a", "c"} and top[0]["similitud"] > 0.99, top
        assert [t["clave"] for t in buscar("agro", k=3, pais="EC")] == ["c"]
        assert [t["clave"] for t in buscar("agro", k=3, tipo="noticia")][0] == "a"
    print("OK cerebro.embeddings: sincroniza incremental, KNN y filtros por pais/tipo")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "demo"
    if cmd == "sincronizar":
        print(sincronizar(int(sys.argv[2]) if len(sys.argv) > 2 else None))
    elif cmd == "buscar":
        for r in buscar(" ".join(sys.argv[2:]), k=10):
            print(f"{r['similitud']:.3f} [{r['tipo']}/{r['pais']}] {r['fecha']} {r['titulo'][:100]}")
    else:
        _demo()
