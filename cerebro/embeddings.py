"""Busqueda por significado sobre TODO el corpus (PLs PE/EC, noticias,
sesiones transcritas) con un modelo de embeddings LOCAL + sqlite-vec.

Por que: la relevancia por cliente y el agrupado de noticias usaban TF-IDF
(palabras sueltas) - de ahi los falsos positivos por homonimos que se
arreglaron a mano uno por uno ("tributo" homenaje vs impuesto, "presidente"
de club de futbol, etc.).

Modelo (decidido 2026-09-27 con la misma prueba contra el perfil de Bayer:
2 textos agricolas vs futbol, dengue y "Rinden tributo a Chabuca Granda"):
- gemini-embedding-2: 0.68-0.72 vs 0.43-0.53 (margen ~0.15), y el tier
  gratuito corta en 1000 textos/dia (el corpus son ~24 mil).
- paraphrase-multilingual-MiniLM-L12-v2 local (fastembed/ONNX, ~120 MB,
  sin API ni cupo): 0.41-0.52 vs -0.08-0.11 (margen ~0.29). Gana.
Limite del modelo: lee ~128 tokens por texto (titulo + comienzo del
resumen) - por eso los fragmentos de perfil de cliente son cortos.

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

import functools
import hashlib
import json
import re
import sqlite3
import struct
import sys
import time
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CEREBRO_DB = REPO_ROOT / "data" / "cerebro.db"
RELEASE_URL = "https://github.com/nicosil02/Base_legislativa/releases/download/cerebro/cerebro.db"

MODELO = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
DIM = 384
LOTE = 256
MAX_CHARS = 2000  # igual el modelo corta en ~128 tokens; esto solo acota memoria


@functools.lru_cache(maxsize=1)
def _modelo():
    from fastembed import TextEmbedding
    return TextEmbedding(MODELO)


def embeber(textos: list[str]) -> list[list[float]]:
    """Un vector normalizado (norma 1) por texto."""
    out: list[list[float]] = []
    for v in _modelo().embed([(t or " ")[:MAX_CHARS] for t in textos], batch_size=LOTE):
        n = float((v * v).sum()) ** 0.5 or 1.0
        out.append([float(x) / n for x in v])
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
            clave TEXT UNIQUE NOT NULL,   -- ej. pl_PE_00438-2026-2031-CD, noticia_123, sesion_fb_111
            tipo TEXT NOT NULL,           -- pl | noticia | sesion
            pais TEXT NOT NULL,           -- PE | EC
            titulo TEXT, fecha TEXT, url TEXT, extra TEXT,
            hash TEXT NOT NULL            -- del texto embebido: si cambia, se re-embebe
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS vec_items USING vec0(
            embedding float[{DIM}] distance_metric=cosine,
            tipo text, pais text
        );
        -- Un cliente = varios fragmentos de su perfil (uno por tema); la
        -- afinidad es la del fragmento MAS parecido. Bayer se preocupa de
        -- agroquimicos Y de desabastecimiento de medicamentos: un solo vector
        -- promedio no se parece bien a ninguno de los dos.
        CREATE TABLE IF NOT EXISTS perfiles (cliente TEXT, idx INTEGER, hash TEXT, texto TEXT,
                                             embedding BLOB, PRIMARY KEY (cliente, idx));
        CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
    """)
    modelo = conn.execute("SELECT v FROM meta WHERE k='modelo'").fetchone()
    # Sin registro de modelo pero con items = cerebro.db de antes de esta
    # tabla (el de Gemini, 256 dims): bug real 2026-09-27 ("Dimension
    # mismatch... Expected 256 dimensions but received 384").
    viejo_sin_meta = not modelo and conn.execute("SELECT count(*) FROM items").fetchone()[0] > 0
    if viejo_sin_meta or (modelo and modelo[0] != MODELO):
        # Vectores de otro modelo no son comparables: se rehace todo.
        print(f"[cerebro] modelo cambio ({modelo[0] if modelo else 'sin registro'} -> {MODELO}), rehago el indice")
        conn.executescript("DROP TABLE items; DROP TABLE vec_items; DROP TABLE perfiles; DROP TABLE meta;")
        conn.commit()
        conn.close()
        return conectar(path)
    conn.execute("INSERT OR IGNORE INTO meta VALUES ('modelo', ?)", (MODELO,))
    conn.commit()
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


_RE_ACTUALIZACION = re.compile(
    r"^\s*ACTUALIZACI[OÓ]N DE CONFORMIDAD.*?CONGRESO\s*\)\.?\s*", re.IGNORECASE | re.DOTALL)


def _limpiar_titulo_pl(titulo: str | None) -> str:
    """Saca el encabezado "ACTUALIZACION DE CONFORMIDAD CON LA SEGUNDA
    DISPOSICION COMPLEMENTARIA TRANSITORIA DEL REGLAMENTO DEL CONGRESO - (ANTES
    PL 00015/2021-CR - CONGRESO)" que tienen ~165 PLs re-presentados en el
    Congreso bicameral (37% del periodo, 2026-09-27): el modelo solo leia esa
    formula y no el tema, y esos PLs salian "afines" a cualquier cliente."""
    t = (titulo or "").strip()
    limpio = _RE_ACTUALIZACION.sub("", t).strip()
    return limpio or t


def corpus() -> list[dict]:
    """Todo lo que el cerebro conoce: {clave, tipo, pais, titulo, fecha, url,
    extra, texto}. `texto` es lo que se embebe."""
    items: list[dict] = []
    pe = _db("proyectos.db")
    if pe:
        c = sqlite3.connect(f"file:{pe}?mode=ro", uri=True)
        for r in c.execute("SELECT per_par_id, pley_num, proyecto_ley, titulo, sumilla, "
                           "fec_presentacion, tema, estado, url_portal FROM proyectos"):
            # proyecto_ley ("00004-2026-2031-CD") y no el numero: en el Congreso
            # bicameral el mismo numero existe en Diputados, Senado y Congreso.
            titulo = _limpiar_titulo_pl(r[3])
            items.append({"clave": f"pl_PE_{r[2]}", "tipo": "pl", "pais": "PE",
                          "titulo": f"PL {r[2]}: {titulo}", "fecha": (r[5] or "")[:10], "url": r[8],
                          "extra": json.dumps({"tema": r[6], "estado": r[7]}, ensure_ascii=False),
                          # sumilla primero: el modelo lee ~128 tokens y ahi esta el tema
                          "texto": f"{r[4] or ''}. {titulo}"})
        try:
            filas = c.execute("""SELECT n.id, n.titulo, n.resumen, n.url,
                                        COALESCE(n.fecha_pub, n.first_seen_at), f.pais, f.nombre
                                 FROM noticias n JOIN noticias_fuentes f ON f.id = n.fuente_id""").fetchall()
        except sqlite3.OperationalError:
            filas = []
        from noticias.temas import es_fuente_multipais, es_seccion_fuera_de_foco, pais_por_contenido
        for r in filas:
            # Mismo criterio que las paginas Noticias PE/EC: una fuente que
            # cubre varios paises (Mundo Agropecuario, DPL News...) se asigna
            # por CONTENIDO, y si no habla de Peru ni Ecuador queda afuera.
            # Bug real 2026-09-27: "Brasil ordena frenar la fumigacion aerea
            # con tres neonicotinoides" salia arriba para Syngenta como si
            # fuera de Ecuador (pais de la fuente).
            pais = pais_por_contenido(r[1], r[2], r[5]) if es_fuente_multipais(r[6]) else r[5]
            if not pais or es_seccion_fuera_de_foco(r[3]):
                continue
            items.append({"clave": f"noticia_{r[0]}", "tipo": "noticia", "pais": pais,
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
    todos = corpus()
    # Lo que ya no esta en el corpus (ej. noticia de otro pais filtrada) sale
    # del indice - si no, seguiria apareciendo en busquedas y afinidad.
    vigentes = {it["clave"] for it in todos}
    sobran = [(clave, rid) for clave, (rid, _) in ya.items() if clave not in vigentes]
    for _, rid in sobran:
        conn.execute("DELETE FROM vec_items WHERE rowid=?", (rid,))
        conn.execute("DELETE FROM items WHERE id=?", (rid,))
    if sobran:
        conn.commit()
        print(f"[cerebro] {len(sobran)} documentos fuera del corpus, borrados del indice")
    pendientes = [it for it in todos if ya.get(it["clave"], (None, None))[1] != _hash(it["texto"])]
    # Lo mas reciente primero (sesiones antes que nada): si algo corta la
    # corrida a la mitad, lo que queda pendiente es lo mas viejo.
    pendientes.sort(key=lambda it: (it["tipo"] == "sesion", it["fecha"] or ""), reverse=True)
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
    perfiles = sincronizar_perfiles(conn)
    total = conn.execute("SELECT count(*) FROM items").fetchone()[0]
    conn.close()
    return {"nuevos": hechos, "total": total, "perfiles": perfiles}


# ------------------------------------------------------------------ clientes

CLIENTES = ("bayer", "syngenta", "google", "incode")


def perfil_texto(slug: str) -> str:
    """Lo que le importa al cliente, en prosa, de su notas.md: secciones de
    temas/foco + "Perfil para prompts". No usa contacto, actores ni historial
    (nombres propios y fechas meten ruido en un vector de "de que trata").
    Incode no tiene "Temas de interes" sino "Foco principal"/"Temas
    secundarios" - por eso se busca por palabra en el titulo de la seccion."""
    path = REPO_ROOT / "clientes" / slug / "notas.md"
    if not path.is_file():
        return ""
    partes, actual = [], None
    for linea in path.read_text(encoding="utf-8").splitlines():
        if linea.startswith("## "):
            t = linea[3:].lower()
            actual = [] if (("tema" in t or "foco" in t or "perfil para prompts" in t)
                            and "pendiente" not in t) else None
            if actual is not None:
                partes.append(actual)
            continue
        if actual is not None:
            actual.append(linea)
    return "\n".join("\n".join(p) for p in partes).strip()


def fragmentos_perfil(texto: str, objetivo: int = 450) -> list[str]:
    """Parte el perfil en fragmentos de ~objetivo caracteres sin cortar
    parrafos. Los titulos cortos (### Crop, **Peru.**) se pegan al parrafo
    que sigue en vez de quedar como fragmento suelto."""
    parrafos = [p.strip() for p in texto.split("\n\n") if p.strip()]
    frags, actual = [], ""
    for p in parrafos:
        es_titulo = len(p) < 60  # "### Crop", "**Peru.**": abre fragmento nuevo
        if actual and (len(actual) + len(p) > objetivo or es_titulo) and len(actual) > 120:
            frags.append(actual)
            actual = p
        else:
            actual = f"{actual}\n\n{p}" if actual else p
    if actual:
        frags.append(actual)
    return frags


def sincronizar_perfiles(conn: sqlite3.Connection | None = None) -> int:
    """Re-embebe el perfil de un cliente solo si su texto cambio."""
    conn = conn or conectar()
    ya = {r[0]: r[1] for r in conn.execute("SELECT cliente, group_concat(hash) FROM perfiles "
                                           "WHERE idx = 0 GROUP BY cliente")}
    cambiados = 0
    for c in CLIENTES:
        t = perfil_texto(c)
        if not t or ya.get(c) == _hash(t):
            continue
        frags = fragmentos_perfil(t)
        conn.execute("DELETE FROM perfiles WHERE cliente=?", (c,))
        for i, (fr, v) in enumerate(zip(frags, embeber(frags))):
            # el hash del perfil entero va en idx=0: si cambia algo, se rehace todo
            conn.execute("INSERT INTO perfiles VALUES (?,?,?,?,?)",
                         (c, i, _hash(t) if i == 0 else "", fr, _blob(v)))
        conn.commit()
        cambiados += 1
    return cambiados


def afinidad(claves: list[str], cliente: str, conn: sqlite3.Connection | None = None) -> dict[str, float]:
    """{clave: similitud 0-1 con el perfil del cliente} para las claves que
    ya estan en el cerebro (las que todavia no, simplemente no aparecen)."""
    conn = conn or conectar()
    if not claves:
        return {}
    out: dict[str, float] = {}
    for i in range(0, len(claves), 900):  # tope de parametros de sqlite
        lote = claves[i:i + 900]
        filas = conn.execute(
            f"""SELECT i.clave, MAX(1 - vec_distance_cosine(v.embedding, p.embedding)) AS sim
                FROM items i JOIN vec_items v ON v.rowid = i.id
                JOIN perfiles p ON p.cliente = ?
                WHERE i.clave IN ({",".join("?" * len(lote))})
                GROUP BY i.clave""", [cliente, *lote]).fetchall()
        out.update({r[0]: round(r[1], 4) for r in filas})
    return out


# ------------------------------------------------------------------ niveles

# Calibrado 2026-09-27 contra PLs y noticias reales (perfil de cliente vs
# documento): >= 0.62 relevante de verdad (Bayer: contrabando agricola, agro;
# Incode: proteccion digital); ~0.55 ya mezcla ruido ("reeleccion encubierta
# de gobernadores"). ponytail: umbrales fijos a ojo, recalibrar con lo que
# Nicolas descarte en Noticias si hace falta.
AFINIDAD_ALTA = 0.62
AFINIDAD_MEDIA = 0.55
# Tema/sector (descripcion armada con las keywords de noticias/temas.py vs
# noticia): la escala es mas baja; >= 0.48 trae lo del sector que las
# keywords no agarran ("El Nino: prioridades de los gremios agrarios",
# "floracion de frutales" para Crop).
AFINIDAD_SECTOR = 0.48


def nivel_afinidad(sim: float | None) -> str:
    if sim is None or sim != sim:
        return ""
    return "Alta" if sim >= AFINIDAD_ALTA else "Media" if sim >= AFINIDAD_MEDIA else "Baja"


def descripcion_tema(tema: str) -> str:
    from noticias.temas import TEMAS
    return f"Noticias sobre {tema}: " + ", ".join(TEMAS.get(tema, [])[:60])


def afinidad_vector(claves: list[str], vector: list[float],
                    conn: sqlite3.Connection | None = None) -> dict[str, float]:
    """{clave: similitud} de cada clave contra un vector cualquiera."""
    conn = conn or conectar()
    out: dict[str, float] = {}
    for i in range(0, len(claves), 900):
        lote = claves[i:i + 900]
        filas = conn.execute(
            f"""SELECT i.clave, 1 - vec_distance_cosine(v.embedding, ?)
                FROM items i JOIN vec_items v ON v.rowid = i.id
                WHERE i.clave IN ({",".join("?" * len(lote))})""", [_blob(vector), *lote]).fetchall()
        out.update({r[0]: round(r[1], 4) for r in filas})
    return out


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
        assert r["nuevos"] == 3 and r["total"] == 3, r
        assert sincronizar()["nuevos"] == 0  # idempotente: nada cambio
        items[0]["texto"] = "agro plaguicidas SENASA"
        assert sincronizar()["nuevos"] == 1  # cambio el texto -> se re-embebe solo ese
        quitado = items.pop(1)
        assert sincronizar()["total"] == 2  # salio del corpus -> sale del indice
        items.insert(1, quitado)
        assert sincronizar()["nuevos"] == 1
        top = buscar("agro", k=3)
        assert {t["clave"] for t in top[:2]} == {"a", "c"} and top[0]["similitud"] > 0.99, top
        assert [t["clave"] for t in buscar("agro", k=3, pais="EC")] == ["c"]
        assert [t["clave"] for t in buscar("agro", k=3, tipo="noticia")][0] == "a"
        conn = conectar()
        conn.execute("DELETE FROM perfiles WHERE cliente='bayer'")
        conn.execute("INSERT INTO perfiles VALUES ('bayer',0,'x','agro',?)", (_blob(_fake(["agro"])[0]),))
        conn.execute("INSERT INTO perfiles VALUES ('bayer',1,'','futbol',?)", (_blob(_fake(["futbol"])[0]),))
        af = afinidad(["a", "b", "c", "no-existe"], "bayer", conn)
        # max entre fragmentos: "a" (agro) y "b" (futbol) matchean cada uno su fragmento
        assert af["a"] > 0.99 and af["b"] > 0.99 and "no-existe" not in af, af
        frs = fragmentos_perfil("### Crop\n\n" + "x" * 500 + "\n\n**Peru.**\n\n" + "y" * 500)
        assert len(frs) == 2 and frs[0].startswith("### Crop") and frs[1].startswith("**Peru.**"), frs
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
