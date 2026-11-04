"""Radar Legislativo - Noticias y temas de interes (Peru y Ecuador).

Las paginas pages/5_Noticias_PE.py y 6_Noticias_EC.py solo llaman a
render(pais). Fuente: tablas noticias + noticias_fuentes en proyectos.db,
alimentadas por noticias/ y refrescar-pe.yml. Ecuador suma el cruce con los
PL de las matrices de clientes.
"""
from __future__ import annotations

import sqlite3

import pandas as pd
import streamlit as st

from noticias.temas import (
    clasificar, es_fuente_multipais, es_normativa, es_normativa_tag,
    es_seccion_fuera_de_foco, pais_por_contenido,
)
from noticias.fuentes import (
    INSTITUCIONES_AMPLIAS, TEMAS_CLIENTE, PERFIL_ESTRICTO, matchea_perfil,
    FUENTES_GENERALISTAS_FILTRAR_RUIDO,
)
from clientes.matrices import pls_trackeados_ec, coincide_con_noticia
from noticias.feedback_store import list_descartadas
from core.db import db_path
from core.text import norm


@st.cache_data(ttl=60)
def _pls_trackeados_cache() -> list[dict]:
    return pls_trackeados_ec()


def _pl_relacionado(titulo: str | None, resumen: str | None) -> str | None:
    """Si la noticia parece hablar de un PL que ya trackeamos (matriz Bayer
    Crop/Syngenta o Incode), devuelve su titulo corto - señal temprana antes
    de que el portal EC (que sincroniza cada 4-6h) lo refleje. Ver
    clientes/matrices.py::coincide_con_noticia - deterministico, no TF-IDF."""
    texto = f"{titulo or ''} {resumen or ''}"
    for pl in _pls_trackeados_cache():
        if coincide_con_noticia(pl.get("titulo_matriz"), texto, noticia_titulo=titulo):
            return pl["titulo_matriz"]
    return None


@st.cache_data(ttl=300)
def _seguimiento_pl_ec(dias: int = 90) -> pd.DataFrame:
    """Una fila por PL trackeado (matriz Bayer/Syngenta/Incode) con la
    noticia mas reciente que le matcheo en los ultimos `dias` - vista
    persistente del mismo matching que ya dispara el WhatsApp
    (noticias/digest.py::_matches_pl_ec), para no depender de pescar el
    mensaje. Pedido de Nicolas 2026-09-19: "vincularla tambien a noticias
    para poder tenerla actualizada en tiempo real" - sin tocar el Google
    Sheet, solo lectura."""
    trackeados = _pls_trackeados_cache()
    if not trackeados:
        return pd.DataFrame()
    df_noticias = load_noticias("EC", ventana_sql=f"date('now', '-{dias} days')", limit=1000)
    filas = []
    for pl in trackeados:
        matches = [
            row for _, row in df_noticias.iterrows()
            if coincide_con_noticia(pl.get("titulo_matriz"), f"{row['Título']} {row['Resumen'] or ''}",
                                    noticia_titulo=row["Título"])
        ]
        # load_noticias ya viene ORDER BY fecha DESC - la primera es la mas reciente.
        ultima = matches[0] if matches else None
        filas.append({
            "Cliente": "/".join(pl.get("clientes") or []) or "—",
            "PL de interés": pl["titulo_matriz"],
            "Última noticia": ultima["Título"] if ultima is not None else "Sin noticias recientes",
            "Fecha": ultima["Fecha"] if ultima is not None else "",
            "Enlace": ultima["Enlace"] if ultima is not None else "",
            "N° noticias": len(matches),
        })
    return pd.DataFrame(filas)


def _s(v) -> str:
    """str() seguro: convierte NaN/None a string vacio."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    return str(v)


def get_conn() -> sqlite3.Connection:
    db = db_path()
    if not db.exists():
        st.error("No encuentro `proyectos.db`. Inicializa con: "
                 "`python -m noticias.cli init && python -m noticias.cli seed && "
                 "python -m noticias.cli sync`")
        st.stop()
    conn = sqlite3.connect(f"file:{db}?mode=ro&immutable=1", uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


# IMPORTANTE: pasamos `pais` como argumento a TODAS las funciones cacheadas
# (st.cache_data cachea por args; si pais quedara como variable global, las
# 2 paginas compartirian cache y veriamos las mismas noticias en PE y EC).


@st.cache_data(ttl=60)
def load_categorias_fuente(pais: str) -> list[str]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT DISTINCT categoria FROM noticias_fuentes WHERE pais=? "
        "ORDER BY categoria", (pais,),
    ).fetchall()
    return [r[0] for r in rows]


@st.cache_data(ttl=60)
def load_fuentes(pais: str) -> list[str]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT DISTINCT nombre FROM noticias_fuentes WHERE pais=? AND activa=1 "
        "ORDER BY nombre", (pais,),
    ).fetchall()
    return [r[0] for r in rows]


@st.cache_data(ttl=60)
def load_kpis(pais: str) -> dict:
    """KPIs estrictos sobre fecha_pub (no first_seen_at, que es solo cuando
    nuestro scraper la vio por primera vez — una noticia vieja recien
    scrapeada NO es noticia de hoy)."""
    conn = get_conn()
    r = conn.execute(
        """SELECT
             COUNT(DISTINCT f.id) AS n_fuentes,
             SUM(CASE WHEN date(n.fecha_pub) = date('now')
                     THEN 1 ELSE 0 END) AS hoy,
             SUM(CASE WHEN date(n.fecha_pub) >= date('now', '-1 days')
                     THEN 1 ELSE 0 END) AS ultimas_24h,
             SUM(CASE WHEN date(n.fecha_pub) >= date('now', '-3 days')
                     THEN 1 ELSE 0 END) AS ultimos_3d
           FROM noticias_fuentes f
           LEFT JOIN noticias n ON n.fuente_id = f.id
           WHERE f.pais=? AND f.activa=1""", (pais,),
    ).fetchone()
    return {
        "Fuentes activas": r["n_fuentes"] or 0,
        "Hoy": r["hoy"] or 0,
        "Últimas 24h": r["ultimas_24h"] or 0,
        "Últimos 3 días": r["ultimos_3d"] or 0,
    }


VENTANAS = {
    "Hoy": "date('now')",
    "Últimas 24 horas": "date('now', '-1 days')",
    "Últimos 3 días": "date('now', '-3 days')",
    "Últimos 7 días": "date('now', '-7 days')",
}


@st.cache_data(ttl=60)
def load_noticias(pais: str,
                   ventana_sql: str,
                   categoria_fuente: str | None = None,
                   fuente: str | None = None,
                   cliente: str | None = None,
                   busqueda: str | None = None,
                   limit: int = 300) -> pd.DataFrame:
    """Carga noticias y clasifica cada una por tema (keywords).
    Filtro estricto: fecha_pub debe existir y caer en la ventana."""
    conn = get_conn()
    sql = f"""
      SELECT n.id AS "ID",
             n.url AS "Enlace",
             n.titulo AS "Título",
             n.resumen AS "Resumen",
             COALESCE(n.fecha_pub, n.first_seen_at) AS "Fecha",
             f.nombre AS "Fuente",
             f.categoria AS "Categoría fuente",
             n.tags AS "Tags"
      FROM noticias n
      JOIN noticias_fuentes f ON f.id = n.fuente_id
      WHERE f.pais = ? AND f.activa = 1
        AND date(COALESCE(n.fecha_pub, n.first_seen_at)) >= {ventana_sql}
    """
    params: list = [pais]
    if categoria_fuente:
        sql += " AND f.categoria = ?"; params.append(categoria_fuente)
    if fuente:
        sql += " AND f.nombre = ?"; params.append(fuente)
    if cliente:
        # "todos" (backbone legislativo/politico general) cuenta para
        # cualquier cliente seleccionado.
        sql += " AND (f.clientes LIKE ? OR f.clientes LIKE ?)"
        params.extend([f"%{cliente}%", "%todos%"])
    if busqueda:
        sql += " AND (LOWER(n.titulo) LIKE ? OR LOWER(COALESCE(n.resumen,'')) LIKE ?)"
        q = f"%{busqueda.lower()}%"
        params.extend([q, q])
    sql += " ORDER BY COALESCE(n.fecha_pub, n.first_seen_at) DESC LIMIT ?"
    params.append(limit)
    df = pd.read_sql_query(sql, conn, params=params)
    if not df.empty:
        # Fuentes multi-pais (DPL, Bloomberg, busquedas de Google News):
        # se reclasifica por contenido (noticias/temas.py::es_fuente_multipais).
        def _pais_real(row):
            if not es_fuente_multipais(row["Fuente"]):
                return pais
            return pais_por_contenido(row["Título"], row["Resumen"], pais)
        df = df[df.apply(_pais_real, axis=1) == pais]
        # Secciones internacional/deportes de medios nacionales (ver temas.py).
        df = df[~df["Enlace"].map(es_seccion_fuera_de_foco)]
    if not df.empty:
        descartadas = list_descartadas()
        if descartadas:
            df = df[~df["ID"].isin(descartadas)]
    if not df.empty:
        # Mismo titulo en distintos portales: queda la mas reciente.
        df = df[~df["Título"].map(lambda t: norm(t)[:80]).duplicated()]

        # Tema por fuente: portales sectoriales garantizan el tema aunque el
        # titulo no tenga keywords ("SERUMS" -> Salud); clasificar() suma
        # los temas transversales por contenido.
        _CAT_A_TEMA = {
            "Temas Salud": "Salud",
            "Temas Agrarios": "Crop",
            "Temas Tech": "Tech / Digital",
            "Temas KYC/AML": "KYC / AML / Financiero",
        }
        def _temas_de_noticia(row):
            temas = clasificar(row["Título"], row["Resumen"], row.get("Enlace"))
            tema_fuente = _CAT_A_TEMA.get(row.get("Categoría fuente"))
            if tema_fuente and tema_fuente not in temas:
                temas = [tema_fuente] + temas
            return temas
        df["Temas"] = df.apply(_temas_de_noticia, axis=1)
        df["EsNormativa"] = df.apply(
            # tags=="normas" viene del endpoint de normas de gob.pe (señal
            # autoritativa); el keyword es fallback para RSS/HTML.
            lambda row: es_normativa_tag(row.get("Tags"))
            or es_normativa(row["Título"], row["Resumen"]), axis=1
        )
        df["PL_relacionado"] = df.apply(
            lambda row: _pl_relacionado(row["Título"], row["Resumen"]), axis=1
        ) if pais == "EC" else None
        # Fuentes "generalistas" (ver fuentes.py): su feed de Coyuntura
        # Politica en realidad trae el sitio entero (deportes, espectaculos)
        # por un feed roto/mal etiquetado - se filtra SIEMPRE, no solo con
        # un cliente seleccionado (un partido de futbol no es Coyuntura
        # Politica ni siquiera viendo "Todos").
        es_generalista = (
            df["Fuente"].isin(FUENTES_GENERALISTAS_FILTRAR_RUIDO)
            & (df["Categoría fuente"] == "Coyuntura Politica")
        )
        tiene_tema_real = df["Temas"].map(lambda ts: len(ts) > 0)
        df = df[~es_generalista | tiene_tema_real]
        if cliente:
            # Instituciones "amplias" (MEF, etc. - ver fuentes.py) solo
            # cuentan para este cliente si el contenido matchea su tema
            # real, no solo por estar tageada la institucion entera.
            temas_ok = set(TEMAS_CLIENTE.get(cliente, []))
            es_amplia = df["Fuente"].isin(INSTITUCIONES_AMPLIAS)
            matchea_tema = df["Temas"].map(lambda ts: bool(temas_ok.intersection(ts)))
            df = df[~es_amplia | matchea_tema]
            # Perfil estricto: ni el tema generico alcanza (ver fuentes.py) -
            # exige match contra las keywords reales del bluebook del cliente.
            estricto = PERFIL_ESTRICTO.get(cliente, set())
            if estricto:
                es_estricta = df["Fuente"].isin(estricto) | df["Categoría fuente"].isin(estricto)
                ok_perfil = df.apply(
                    lambda r: matchea_perfil(cliente, r["Título"], r["Resumen"]), axis=1
                )
                df = df[~es_estricta | ok_perfil]
    else:
        df["Temas"] = []
        df["EsNormativa"] = False
        df["PL_relacionado"] = None
    return df
