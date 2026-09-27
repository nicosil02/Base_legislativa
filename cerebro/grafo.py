"""Grafo de conocimiento del negocio con LightRAG (HKUDS/LightRAG): extrae
entidades (PLs, legisladores, ministros, comisiones, entidades, empresas,
clientes, temas) y sus relaciones de lo que ya junta la plataforma, para
responder preguntas que cruzan fuentes ("que paso esta semana con lo que le
importa a Bayer en Ecuador?", "quien empuja la ley X y en que comision
esta?"). cerebro/embeddings.py busca documentos parecidos; esto conecta los
hechos entre documentos.

Corpus acotado a proposito (el tier gratuito de Gemini limita llamadas):
perfil de cada cliente (notas.md), resumenes de sesiones del Congreso y la
Asamblea, PLs de los ultimos DIAS_PL dias (PE y EC) agrupados por dia, y
solo las noticias con alta afinidad con algun cliente (cerebro.embeddings).
Cada documento tiene un id estable: LightRAG no re-procesa lo ya hecho, asi
que cada corrida solo agrega lo nuevo (y reintenta lo que fallo).

Donde vive: data/grafo/ (archivos JSON/GraphML de LightRAG, sin servidor),
publicado como grafo.tar.gz en el release "cerebro" - igual que cerebro.db.

Uso:
    python -m cerebro.grafo construir [max_docs]
    python -m cerebro.grafo preguntar "que le preocupa hoy a Bayer en Peru?"
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sqlite3
import sys
import tarfile
import time
import urllib.request
from datetime import date, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GRAFO_DIR = REPO_ROOT / "data" / "grafo"
RELEASE_URL = "https://github.com/nicosil02/Base_legislativa/releases/download/cerebro/grafo.tar.gz"

LLM = "gemini-3.6-flash"  # mismo modelo que el resto del proyecto
DIAS_PL = 60
DIAS_NOTICIAS = 30
AFINIDAD_NOTICIA = 0.62  # ponytail: a ojo sobre la prueba de Bayer (0.68-0.72 lo relevante, <0.55 lo ajeno); calibrar
MAX_DOCS_POR_CORRIDA = 40  # techo de llamadas al LLM por corrida (tier gratuito)

TIPOS_ENTIDAD = [
    "proyecto_de_ley", "norma", "legislador", "funcionario", "comision",
    "entidad_publica", "empresa", "gremio", "cliente", "tema_regulatorio", "producto",
]


def _clave_gemini() -> str:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        try:
            import streamlit as st
            key = st.secrets.get("GEMINI_API_KEY")
        except Exception:
            key = None
    if not key:
        raise RuntimeError("Falta GEMINI_API_KEY")
    return key


async def _rag():
    import numpy as np
    from lightrag import LightRAG
    from lightrag.llm.gemini import gemini_model_complete
    from lightrag.utils import wrap_embedding_func_with_attrs

    key = _clave_gemini()

    async def llm(prompt, system_prompt=None, history_messages=[], **kwargs):
        return await gemini_model_complete(prompt, system_prompt=system_prompt,
                                           history_messages=history_messages, api_key=key,
                                           model_name=LLM, **kwargs)

    # Embeddings LOCALES (mismo modelo que cerebro/embeddings.py): el grafo
    # embebe miles de entidades y relaciones, y el tier gratuito de Gemini
    # corta en 1000 textos/dia. Gemini queda solo para extraer entidades y
    # redactar respuestas.
    from cerebro.embeddings import DIM, MODELO, embeber

    @wrap_embedding_func_with_attrs(embedding_dim=DIM, max_token_size=128, model_name=MODELO)
    async def emb(texts: list[str]) -> np.ndarray:
        return np.array(await asyncio.to_thread(embeber, texts), dtype=np.float32)

    GRAFO_DIR.mkdir(parents=True, exist_ok=True)
    rag = LightRAG(
        working_dir=str(GRAFO_DIR), llm_model_func=llm, llm_model_name=LLM, embedding_func=emb,
        llm_model_max_async=2,  # despacio: tier gratuito
        addon_params={"language": "Spanish", "entity_types": TIPOS_ENTIDAD},
    )
    await rag.initialize_storages()
    return rag


# ------------------------------------------------------------------ documentos

def _db(nombre: str) -> Path | None:
    for p in (REPO_ROOT / nombre, Path.cwd() / nombre):
        if p.exists() and p.stat().st_size > 0:
            return p
    return None


def documentos() -> list[tuple[str, str]]:
    """[(doc_id, texto)] con ids estables. Solo dias YA cerrados para PLs y
    noticias (un dia en curso cambiaria de contenido con el mismo id)."""
    hoy = date.today().isoformat()
    docs: list[tuple[str, str]] = []

    from cerebro.embeddings import CLIENTES, perfil_texto
    for c in CLIENTES:
        t = perfil_texto(c)
        if t:
            # el hash en el id: si Nicolas cambia el notas.md, entra como doc nuevo
            h = hashlib.sha1(t.encode("utf-8")).hexdigest()[:8]
            docs.append((f"cliente_{c}_{h}", f"Cliente de Vali Consultores: {c.upper()}.\n"
                                              f"Lo que le importa y le preocupa:\n{t}"))

    rpath = REPO_ROOT / "data" / "transcripciones_resumenes.json"
    resumenes = {r["video_id"]: r for r in json.loads(rpath.read_text(encoding="utf-8"))} if rpath.exists() else {}
    pe = _db("proyectos.db")
    if pe:
        c = sqlite3.connect(f"file:{pe}?mode=ro", uri=True)
        for vid, tipo, titulo, fecha in c.execute(
                "SELECT video_id, tipo, titulo, fecha FROM sesiones_transcripciones"):
            r = resumenes.get(vid)
            if not r or "en curso" in r["resumen"]:
                continue  # sin resumen todavia, o sesion que sigue creciendo
            pais = "Ecuador (Asamblea Nacional)" if tipo.endswith("(EC)") else "Perú (Congreso)"
            ideas = "\n".join(f"- {i}" for i in r.get("ideas_clave", []))
            docs.append((f"sesion_{vid}", f"Sesión legislativa, {pais}. {tipo}. {titulo}. Fecha: {fecha}.\n"
                                          f"Resumen: {r['resumen']}\nIdeas clave:\n{ideas}"))

        desde = (date.today() - timedelta(days=DIAS_PL)).isoformat()
        por_dia: dict[str, list[str]] = {}
        for num, titulo, sumilla, fec, tema, estado, grupo in c.execute(
                """SELECT proyecto_ley, titulo, sumilla, substr(fec_presentacion,1,10), tema, estado,
                          grupo_parlamentario FROM proyectos WHERE substr(fec_presentacion,1,10) >= ?""",
                (desde,)):
            if fec and fec < hoy:
                por_dia.setdefault(fec, []).append(
                    f"- PL {num} ({tema or 's/tema'}, {estado or 's/estado'}, {grupo or 's/bancada'}): "
                    f"{titulo}. {sumilla or ''}")
        for fec, pls in por_dia.items():
            docs.append((f"pls_PE_{fec}", f"Proyectos de ley presentados en el Congreso del Perú el {fec}:\n"
                                         + "\n".join(pls)))

        noticias = _noticias_afines(c, hoy)
        c.close()
        for (pais, fec), items in noticias.items():
            docs.append((f"noticias_{pais}_{fec}", f"Noticias relevantes para clientes, {pais}, {fec}:\n"
                                                  + "\n".join(items)))

    ec = _db("proyectos_ec.db")
    if ec:
        c = sqlite3.connect(f"file:{ec}?mode=ro", uri=True)
        desde = (date.today() - timedelta(days=DIAS_PL)).isoformat()
        por_dia = {}
        for num, titulo, estado, comision, fec, tema in c.execute(
                """SELECT n_tramite, titulo, estado, comision_asignada,
                          substr(COALESCE(fec_presentacion, fec_documento),1,10), tema
                   FROM proyectos WHERE substr(COALESCE(fec_presentacion, fec_documento),1,10) >= ?""",
                (desde,)):
            if fec and fec < hoy:
                por_dia.setdefault(fec, []).append(
                    f"- PL {num} ({tema or 's/tema'}, {estado or 's/estado'}, comisión: {comision or '-'}): {titulo}")
        c.close()
        for fec, pls in por_dia.items():
            docs.append((f"pls_EC_{fec}", f"Proyectos de ley en la Asamblea Nacional del Ecuador, {fec}:\n"
                                         + "\n".join(pls)))
    return docs


def _noticias_afines(conn: sqlite3.Connection, hoy: str) -> dict[tuple[str, str], list[str]]:
    """Noticias de dias cerrados de la ventana con afinidad >= AFINIDAD_NOTICIA
    con algun cliente, agrupadas por (pais, dia). {} si no hay cerebro."""
    try:
        from cerebro.embeddings import CLIENTES, afinidad, conectar
        cer = conectar()
    except Exception:
        return {}
    desde = (date.today() - timedelta(days=DIAS_NOTICIAS)).isoformat()
    filas = conn.execute(
        """SELECT n.id, n.titulo, n.resumen, f.pais, f.nombre,
                  substr(COALESCE(n.fecha_pub, n.first_seen_at),1,10) AS dia
           FROM noticias n JOIN noticias_fuentes f ON f.id = n.fuente_id
           WHERE dia >= ? AND dia < ?""", (desde, hoy)).fetchall()
    claves = [f"noticia_{r[0]}" for r in filas]
    mejor: dict[str, tuple[float, str]] = {}
    for cli in CLIENTES:
        for k, v in afinidad(claves, cli, cer).items():
            if v >= AFINIDAD_NOTICIA and v > mejor.get(k, (0, ""))[0]:
                mejor[k] = (v, cli)
    out: dict[tuple[str, str], list[str]] = {}
    for nid, titulo, resumen, pais, fuente, dia in filas:
        m = mejor.get(f"noticia_{nid}")
        if m:
            out.setdefault((pais or "PE", dia), []).append(
                f"- [{fuente}] {titulo}. {(resumen or '')[:400]} (relevante para {m[1]})")
    return out


# ------------------------------------------------------------------ construir / preguntar

async def _construir(max_docs: int) -> dict:
    rag = await _rag()
    try:
        from lightrag.base import DocStatus

        docs = documentos()
        # Solo los PROCESSED cuentan como hechos: los FAILED (ej. corte por el
        # limite diario de Gemini) se vuelven a mandar en la proxima corrida.
        ya = set((await rag.doc_status.get_docs_by_statuses([DocStatus.PROCESSED])).keys())
        # Lo mas nuevo primero, igual que cerebro/embeddings.py.
        nuevos = sorted([d for d in docs if d[0] not in ya], key=lambda d: d[0].split("_")[-1], reverse=True)
        nuevos = [d for d in nuevos if d[0].startswith("cliente_")] + \
                 [d for d in nuevos if not d[0].startswith("cliente_")]
        lote = nuevos[:max_docs]
        if lote:
            await rag.ainsert([t for _, t in lote], ids=[i for i, _ in lote])
        return {"documentos": len(docs), "ya_en_grafo": len(ya), "insertados": len(lote),
                "pendientes": len(nuevos) - len(lote)}
    finally:
        await rag.finalize_storages()


def construir(max_docs: int = MAX_DOCS_POR_CORRIDA) -> dict:
    return asyncio.run(_construir(max_docs))


async def _preguntar(pregunta: str, modo: str) -> str:
    from lightrag import QueryParam
    rag = await _rag()
    try:
        return await rag.aquery(pregunta, param=QueryParam(
            mode=modo,
            user_prompt=("Respondé en español, como analista de asuntos públicos de Vali Consultores. "
                         "Citá los PL, sesiones y noticias concretos en que te basás. Si el grafo no "
                         "tiene la información, decilo en vez de suponer."),
        ))
    finally:
        await rag.finalize_storages()


def preguntar(pregunta: str, modo: str = "mix") -> str:
    return asyncio.run(_preguntar(pregunta, modo))


def empaquetar(destino: Path | None = None) -> Path:
    destino = destino or REPO_ROOT / "data" / "grafo.tar.gz"
    with tarfile.open(destino, "w:gz") as tar:
        tar.add(GRAFO_DIR, arcname="grafo")
    return destino


def descargar_si_falta(max_edad_seg: int = 3 * 3600) -> bool:
    """Para la app: baja y descomprime grafo.tar.gz del release si no hay
    copia local reciente. False si no se pudo."""
    marca = GRAFO_DIR / ".descargado"
    if marca.exists() and time.time() - marca.stat().st_mtime < max_edad_seg:
        return True
    try:
        tmp = REPO_ROOT / "data" / "grafo.tar.gz"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(RELEASE_URL, timeout=120) as r, open(tmp, "wb") as f:
            f.write(r.read())
        with tarfile.open(tmp) as tar:
            tar.extractall(REPO_ROOT / "data", filter="data")
        marca.touch()
        return True
    except Exception as e:
        print(f"[grafo] no pude bajar {RELEASE_URL}: {e}")
        return (GRAFO_DIR / "graph_chunk_entity_relation.graphml").exists()


# ------------------------------------------------------------------ self-check

def _demo():
    """Sin red ni LLM: ids estables y solo dias cerrados."""
    docs = documentos()
    ids = [i for i, _ in docs]
    assert len(ids) == len(set(ids)), "ids duplicados"
    hoy = date.today().isoformat()
    assert not any(i.endswith(hoy) for i in ids), "no debe incluir el dia en curso"
    assert any(i.startswith("cliente_bayer_") for i in ids)
    assert documentos() == docs, "debe ser determinista (mismos ids y textos)"
    tipos = {}
    for i, t in docs:
        k = i.split("_")[0]
        tipos[k] = tipos.get(k, 0) + 1
    print(f"OK cerebro.grafo: {len(docs)} documentos con ids estables {tipos}, "
          f"{sum(len(t) for _, t in docs):,} caracteres")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "demo"
    if cmd == "construir":
        print(construir(int(sys.argv[2]) if len(sys.argv) > 2 else MAX_DOCS_POR_CORRIDA))
    elif cmd == "preguntar":
        print(preguntar(" ".join(sys.argv[2:])))
    elif cmd == "empaquetar":
        print(empaquetar())
    else:
        _demo()
