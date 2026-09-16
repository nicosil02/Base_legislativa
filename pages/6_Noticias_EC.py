"""Radar Legislativo - Ecuador - Noticias y temas de interes.

Agregador de noticias de medios, instituciones y gremios peruanos
organizadas por categoria (Coyuntura Politica, Institucion, Temas
Agrarios, Temas Salud, Temas Tech, KYC/AML).

Fuente: tablas noticias + noticias_fuentes en proyectos.db, alimentadas
por el modulo noticias/ y el workflow refrescar-pe.yml.
"""
from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st

from noticias.temas import clasificar, es_normativa, todos_los_temas
from noticias.fuentes import (
    INSTITUCIONES_AMPLIAS, TEMAS_CLIENTE, PERFIL_ESTRICTO, matchea_perfil,
    FUENTES_GENERALISTAS_FILTRAR_RUIDO,
)
from alerts.borradores_store import marcar_pendiente
from clientes.matrices import pls_trackeados_ec, coincide_con_noticia


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

CLIENTES_DIR = Path(__file__).resolve().parent.parent / "clientes"

# Una noticia con varios temas se renderiza una vez por cada grupo de tema
# (ver el loop de mas abajo) - el checkbox "combinar" solo debe existir UNA
# vez por noticia real (Streamlit no permite widgets con la misma key, y
# checkboxes independientes por grupo se pisan entre si: marcar la copia de
# "Salud" no marca la de "Coyuntura politica", y la copia sin marcar hace
# pop() del id que la otra copia acababa de agregar). Se trackea que nid ya
# tuvo su checkbox renderizado en esta corrida del script.
_combinar_rendered: set[int] = set()


PAIS = "EC"
PAIS_LABEL = "Ecuador"


def _s(v) -> str:
    """str() seguro: convierte NaN/None a string vacio."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    return str(v)


def _find_db_path() -> Path | None:
    here = Path(__file__).resolve().parent
    candidates = [here.parent / "proyectos.db", Path.cwd() / "proyectos.db"]
    cur = here
    for _ in range(5):
        candidates.append(cur / "proyectos.db")
        cur = cur.parent
    for p in candidates:
        if p.exists() and p.is_file() and p.stat().st_size > 0:
            return p.resolve()
    return None


# ====================== CSS (estetica Vali) ======================
st.markdown(
    """<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap');
:root {
  --ink:#0A294D; --ink-soft:#435D74; --ink-mute:#869FB2;
  --line:#CFD9E0; --line-soft:#E3E9ED;
  --accent:#0A294D; --accent-red:#BF1A1A;
  --bg:#FFFFFF; --bg-soft:#F4F6F8;
}
html, body, [class*="css"], .stApp {
  font-family:'Inter',-apple-system,BlinkMacSystemFont,sans-serif !important;
  color:var(--ink); background-color:var(--bg);
}
section[data-testid="stSidebar"] { background-color:var(--ink) !important; }
section[data-testid="stSidebar"] *, section[data-testid="stSidebar"] a {
  color:#FFFFFF !important; font-family:'Inter',sans-serif !important;
}
.block-container { padding-top:2rem; padding-bottom:4rem; max-width:1400px; }

.country-eyebrow {
  font-size:11px; font-weight:800; letter-spacing:0.25em;
  text-transform:uppercase; color:var(--accent); margin-bottom:12px;
}
.country-title {
  font-family: Georgia, 'Times New Roman', serif;
  font-size:clamp(2.5rem,5vw,3.75rem); font-weight:400;
  letter-spacing:-0.01em; line-height:0.98; color:var(--ink); margin:0 0 10px 0;
}
.country-title .accent { color:var(--accent); }
.country-subtitle {
  font-size:1.15rem; color:var(--ink-soft); line-height:1.6; margin-bottom:36px;
}
div[data-testid="stMetric"] {
  background-color:var(--bg); border:1px solid var(--line); border-radius:12px;
  padding:16px 18px; box-shadow:none;
}
div[data-testid="stMetricLabel"] {
  color:var(--ink-soft) !important; font-size:10px !important;
  text-transform:uppercase; letter-spacing:0.18em; font-weight:700 !important;
}
div[data-testid="stMetricValue"] {
  color:var(--ink) !important; font-weight:900 !important;
  font-size:1.6rem !important; letter-spacing:-0.02em;
}
h2,h3 { font-weight:800; color:var(--ink); letter-spacing:-0.01em; }
.categoria-eyebrow {
  font-size:11px; font-weight:800; letter-spacing:0.18em;
  text-transform:uppercase; color:var(--accent); margin: 30px 0 6px 0;
}
.noticia-card {
  border: 1px solid var(--line-soft); border-radius: 10px;
  padding: 14px 16px; margin: 8px 0;
  transition: border-color .15s, box-shadow .15s;
}
.noticia-card:hover { border-color: var(--accent); box-shadow: 0 2px 8px rgba(10,41,77,0.08); }
.noticia-fuente {
  font-size:11px; font-weight:700; color:var(--ink-mute);
  text-transform:uppercase; letter-spacing:0.06em;
}
.noticia-titulo {
  font-size:15px; font-weight:700; color:var(--ink); line-height:1.35;
  margin: 4px 0; text-decoration: none;
}
.noticia-titulo a { color:var(--ink); text-decoration: none; }
.noticia-titulo a:hover { color: var(--accent-red); text-decoration: underline; }
.noticia-meta {
  font-size:11px; color:var(--ink-mute);
}
.noticia-resumen {
  font-size:13px; color:var(--ink-soft); line-height:1.45; margin-top:4px;
}
.footer-rule { width:32px; height:2px; background:var(--ink); margin:60px 0 14px 0; }
.footer-text {
  font-size:11px; font-weight:700; letter-spacing:0.18em;
  text-transform:uppercase; color:var(--ink-soft);
}
footer { visibility:hidden; }
</style>""",
    unsafe_allow_html=True,
)


def get_conn() -> sqlite3.Connection:
    db = _find_db_path()
    if db is None:
        st.error("No encuentro `proyectos.db`. Inicializa con: "
                 "`python -m noticias.cli init && python -m noticias.cli seed && "
                 "python -m noticias.cli sync`")
        st.stop()
    conn = sqlite3.connect(f"file:{db}?mode=ro&immutable=1", uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _feedback_descartar(noticia_id: int) -> None:
    db = _find_db_path()
    if not db:
        return
    conn = sqlite3.connect(str(db), check_same_thread=False)
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS noticias_feedback (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              noticia_id INTEGER NOT NULL,
              action TEXT NOT NULL,
              tema_correcto TEXT,
              created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_feedback_noticia
              ON noticias_feedback(noticia_id);
        """)
        conn.execute(
            "INSERT INTO noticias_feedback (noticia_id, action, created_at) "
            "VALUES (?, 'descartar', datetime('now'))",
            (int(noticia_id),),
        )
        conn.commit()
    finally:
        conn.close()
    st.cache_data.clear()


# IMPORTANTE: pasamos `pais` como argumento a TODAS las funciones cacheadas
# (st.cache_data cachea por args; si pais quedara como variable global, las
# 2 paginas compartirian cache y veriamos las mismas noticias en PE y EC).


@st.cache_data(ttl=60)
def has_tables(pais: str) -> bool:
    conn = get_conn()
    try:
        n = conn.execute(
            "SELECT COUNT(*) FROM noticias_fuentes WHERE pais=?", (pais,)
        ).fetchone()[0]
        return n > 0
    except sqlite3.OperationalError:
        return False


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


@st.cache_data(ttl=300)
def load_clientes() -> list[str]:
    """Slugs de clientes/<slug>/ (carpeta con notas.md real) - "_plantillas"
    no es un cliente, se excluye."""
    if not CLIENTES_DIR.is_dir():
        return []
    return sorted(
        p.name for p in CLIENTES_DIR.iterdir()
        if p.is_dir() and not p.name.startswith("_")
    )


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
        AND NOT EXISTS (
          SELECT 1 FROM noticias_feedback fb
          WHERE fb.noticia_id = n.id AND fb.action = 'descartar'
        )
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
        import unicodedata as _ud
        def _norm_titulo(t: str) -> str:
            t = (t or "").lower()
            t = "".join(c for c in _ud.normalize("NFD", t)
                        if _ud.category(c) != "Mn")
            t = " ".join(t.split())
            return t[:80]
        df["_dedup_key"] = df["Título"].map(_norm_titulo)
        df = df.drop_duplicates(subset="_dedup_key", keep="first")
        df = df.drop(columns="_dedup_key")

        _CAT_A_TEMA = {
            "Temas Salud": "Salud",
            "Temas Agrarios": "Crop",
            "Temas Tech": "Tech / Digital",
            "Temas KYC/AML": "KYC / AML / Financiero",
        }
        def _temas_de_noticia(row):
            temas = clasificar(row["Título"], row["Resumen"])
            tema_fuente = _CAT_A_TEMA.get(row.get("Categoría fuente"))
            if tema_fuente and tema_fuente not in temas:
                temas = [tema_fuente] + temas
            return temas
        df["Temas"] = df.apply(_temas_de_noticia, axis=1)
        df["EsNormativa"] = df.apply(
            # tags=="normas" viene del endpoint de normas de gob.pe (señal
            # autoritativa); el keyword es fallback para RSS/HTML.
            lambda row: row.get("Tags") == "normas"
            or es_normativa(row["Título"], row["Resumen"]), axis=1
        )
        df["PL_relacionado"] = df.apply(
            lambda row: _pl_relacionado(row["Título"], row["Resumen"]), axis=1
        )
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


# ====================== UI ======================

st.markdown('<div class="country-eyebrow">Radar Legislativo · Noticias</div>',
            unsafe_allow_html=True)
st.markdown(
    f'<h1 class="country-title"><span class="accent">{PAIS_LABEL}</span> · Noticias y temas de interés</h1>',
    unsafe_allow_html=True,
)
st.markdown(
    '<p class="country-subtitle">Mapeo de medios, instituciones, ministerios, '
    'agencias regulatorias y gremios sectoriales del Ecuador. Cobertura de '
    'Coyuntura Política, Instituciones, Temas Agrarios, Salud, Tech y KYC/AML.</p>',
    unsafe_allow_html=True,
)

if not has_tables(PAIS):
    st.warning(
        "Las tablas de noticias todavía no existen en la DB. "
        "Inicializá corriendo:\n\n"
        "```\npython -m noticias.cli init\n"
        "python -m noticias.cli seed\n"
        "python -m noticias.cli sync --pais EC\n```"
    )
    st.stop()

# KPIs
kpis = load_kpis(PAIS)
cols = st.columns(len(kpis))
for col, (label, val) in zip(cols, kpis.items()):
    col.metric(label, f"{val:,}")

st.markdown("")

# Filtros
categorias_fuente = load_categorias_fuente(PAIS)
fuentes = load_fuentes(PAIS)
clientes = load_clientes()
temas = todos_los_temas()

fc1 = st.columns([1.1, 1.4, 1.4])
TODAS = "Todas"
TODOS = "Todos"
sel_ventana = fc1[0].selectbox("Ventana", list(VENTANAS.keys()), index=0)
sel_tema = fc1[1].selectbox("Tema", [TODAS] + temas,
    help="Clasificación por contenido (título + resumen). Una noticia puede tener varios temas.")
sel_cat = fc1[2].selectbox("Categoría de fuente", [TODAS] + categorias_fuente,
    help="Categoría del medio que publica (no del contenido)")

fc2 = st.columns([1.2, 1.2, 2.1, 1.0])
sel_fuente = fc2[0].selectbox("Fuente", [TODAS] + fuentes)
sel_cliente = fc2[1].selectbox("Cliente", [TODOS] + clientes,
    help="Fuentes relevantes para ese cliente (más las de interés general)")
busqueda = fc2[2].text_input("Buscar en título o resumen",
    placeholder="ej. AFP, IA, agricultura")
solo_norma = fc2[3].checkbox("📋 Solo normativa",
    help="Decretos, resoluciones, leyes, reglamentos publicados")

df = load_noticias(
    pais=PAIS,
    ventana_sql=VENTANAS[sel_ventana],
    categoria_fuente=sel_cat if sel_cat != TODAS else None,
    fuente=sel_fuente if sel_fuente != TODAS else None,
    cliente=sel_cliente if sel_cliente != TODOS else None,
    busqueda=busqueda.strip() if busqueda.strip() else None,
    limit=300,
)

# Filtros post-clasificación (en pandas)
if sel_tema != TODAS and not df.empty:
    df = df[df["Temas"].apply(lambda lst: sel_tema in (lst or []))]
if solo_norma and not df.empty:
    df = df[df["EsNormativa"] == True]  # noqa: E712

_extras = []
if sel_tema != TODAS:
    _extras.append(f"tema: **{sel_tema}**")
if sel_cliente != TODOS:
    _extras.append(f"cliente: **{sel_cliente}**")
if solo_norma:
    _extras.append("**📋 normativa**")
st.markdown(f"##### {len(df):,} noticia(s) · {sel_ventana.lower()}"
    + (" · " + " · ".join(_extras) if _extras else ""))


def _chips(temas_list: list[str], es_norma: bool) -> str:
    chips_html = []
    if es_norma:
        chips_html.append(
            '<span style="display:inline-block;'
            'background:#FFE6E6;color:var(--accent-red);'
            'font-size:10px;font-weight:800;letter-spacing:.04em;'
            'padding:2px 8px;border-radius:999px;'
            'margin-right:6px;margin-top:6px;">📋 Normativa</span>'
        )
    for t in temas_list or []:
        chips_html.append(
            f'<span style="display:inline-block;'
            'background:#EEF2F6;color:var(--ink);'
            'font-size:10px;font-weight:700;letter-spacing:.04em;'
            'padding:2px 8px;border-radius:999px;'
            f'margin-right:6px;margin-top:6px;">{t}</span>'
        )
    if not chips_html:
        return ""
    return f'<div style="margin-top:6px;">{"".join(chips_html)}</div>'


def _render_card(n, key_suffix: str = "") -> None:
    fecha = _s(n["Fecha"])[:10]
    titulo = _s(n["Título"]).strip()
    resumen = _s(n["Resumen"]).strip()
    if len(resumen) > 240:
        resumen = resumen[:240] + "…"
    temas_list = n["Temas"] if isinstance(n["Temas"], list) else []
    es_norma = bool(n.get("EsNormativa") if isinstance(n, dict) else n["EsNormativa"])
    nid = int(n["ID"]) if "ID" in n and n["ID"] is not None else None
    pl_relacionado = n.get("PL_relacionado") if isinstance(n, dict) else n["PL_relacionado"]
    pl_html = ""
    # pandas puede convertir el None de _pl_relacionado() en NaN (float) al
    # agrupar/deduplicar filas por tema - a diferencia de None, NaN es
    # truthy en Python, asi que "if pl_relacionado:" sola no alcanza y
    # nan[:90] tira TypeError (float no es subscriptable). Confirmado en
    # vivo 2026-09-14 con una noticia real (Luisa Gonzalez).
    if isinstance(pl_relacionado, str) and pl_relacionado:
        pl_html = (
            '<div style="margin-top:6px;font-size:11px;color:#8a5a00;'
            'background:#FFF4DE;padding:4px 8px;border-radius:6px;display:inline-block;">'
            f'🔗 Posible relacionado a PL: {pl_relacionado[:90]}</div>'
        )
    st.markdown(
        f'<div class="noticia-card">'
        f'<div class="noticia-fuente">{n["Fuente"]} · {fecha}</div>'
        f'<div class="noticia-titulo">'
        f'<a href="{n["Enlace"]}" target="_blank" rel="noopener">{titulo}</a>'
        f'</div>'
        + (f'<div class="noticia-resumen">{resumen}</div>' if resumen else '')
        + _chips(temas_list, es_norma)
        + pl_html
        + '</div>',
        unsafe_allow_html=True,
    )
    if nid is not None:
        sfx = f"_{nid}_{key_suffix}" if key_suffix else f"_{nid}"
        full_id = f"noticia_{PAIS}_{nid}"
        resumen_completo = _s(n["Resumen"]).strip()
        cols = st.columns([5, 2, 2, 2])
        with cols[1].popover("📌 Marcar", help="Marcar para que se redacte una alerta de esto"):
            sel = st.multiselect("¿Para qué cliente(s)?", clientes,
                             placeholder="Elige uno o más clientes", key=f"marcar_cli{sfx}")
            if st.button("Marcar", key=f"marcar_btn{sfx}", disabled=not sel):
                marcar_pendiente(
                    clientes=sel, item_id=full_id, item_tipo="noticia",
                    pais=PAIS, item_titulo=titulo, item_url=n["Enlace"],
                    item_resumen=resumen_completo or None,
                    creado_por=st.user.get("email"),
                )
                st.success(f"Marcado para: {', '.join(sel)}. El agente lo redacta en la próxima hora.")
        if cols[2].button("✕ Descartar", key=f"desc{sfx}",
                          help="No aparecerá más y sirve como feedback"):
            _feedback_descartar(nid)
            st.rerun()
        # Combinar varias noticias relacionadas en UNA sola alerta (con mas
        # perspectiva, citando solo la fuente principal al final) - ver el
        # panel "Combinar en una sola alerta" mas abajo en la pagina. Solo se
        # renderiza UNA vez por noticia real, aunque el item aparezca en
        # varios grupos de tema (ver _combinar_rendered arriba).
        if "combinar_items" not in st.session_state:
            st.session_state["combinar_items"] = {}
        combinar_items = st.session_state["combinar_items"]
        if nid not in _combinar_rendered:
            _combinar_rendered.add(nid)
            marcado = cols[3].checkbox(
                "➕ Combinar", key=f"combinar_chk_{nid}", value=full_id in combinar_items,
                help="Sumar a un grupo para combinar varias noticias en una sola alerta",
            )
            if marcado:
                combinar_items[full_id] = {
                    "item_titulo": titulo, "item_url": n["Enlace"],
                    "item_resumen": resumen_completo or None, "fuente": n["Fuente"],
                }
            else:
                combinar_items.pop(full_id, None)


if df.empty:
    st.info("Sin noticias con esos filtros. Prueba ampliar la **Ventana**, "
            "cambiar el **Tema** a *Todas*, o limpiar la búsqueda.")
else:
    if sel_tema != TODAS or sel_cat != TODAS:
        # Filtro específico: lista plana
        for _, n in df.head(150).iterrows():
            _render_card(n)
    else:
        # Vista por defecto: agrupar por TEMA detectado en el contenido.
        # Una noticia con varios temas aparece en cada grupo.
        from collections import defaultdict
        grupos: dict[str, list] = defaultdict(list)
        sin_tema: list = []
        for _, n in df.iterrows():
            tlist = n["Temas"] if isinstance(n["Temas"], list) else []
            if tlist:
                for t in tlist:
                    grupos[t].append(n)
            else:
                sin_tema.append(n)
        # Orden: igual que en TEMAS (declarado), luego "Sin tema"
        import re as _re_sfx
        def _slug(s: str) -> str:
            return _re_sfx.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
        for tema in temas:
            if tema in grupos:
                st.markdown(f'<div class="categoria-eyebrow">{tema} '
                    f'<span style="color:var(--ink-mute);font-weight:500;">'
                    f'· {len(grupos[tema])}</span></div>',
                    unsafe_allow_html=True)
                sfx = _slug(tema)
                for n in grupos[tema][:30]:
                    _render_card(n, key_suffix=sfx)
        if sin_tema:
            st.markdown(f'<div class="categoria-eyebrow">Otros '
                f'<span style="color:var(--ink-mute);font-weight:500;">'
                f'· {len(sin_tema)}</span></div>',
                unsafe_allow_html=True)
            for n in sin_tema[:20]:
                _render_card(n, key_suffix="sin-tema")


# ---------- Combinar en una sola alerta ----------
_combinar_items = st.session_state.get("combinar_items", {})
if _combinar_items:
    st.markdown("---")
    st.markdown(f"##### 🔗 Combinar en una sola alerta ({len(_combinar_items)} seleccionadas)")
    st.caption(
        "Para cuando varias noticias relacionadas dan mas perspectiva de un mismo hecho, "
        "pero la alerta final cita solo una fuente (asi lo hacen ustedes)."
    )
    _ids = list(_combinar_items.keys())
    _opciones = {f"{v['item_titulo'][:70]} — {v['fuente']}": k for k, v in _combinar_items.items()}
    _principal_label = st.radio(
        "¿Cuál es la fuente principal (la que se cita al final de la alerta)?",
        list(_opciones.keys()), key="combinar_principal",
    )
    _principal_id = _opciones[_principal_label]
    _sel_cli = st.multiselect("¿Para qué cliente(s)?", clientes,
                             placeholder="Elige uno o más clientes", key="combinar_clientes")
    if st.button("Combinar en una alerta", disabled=not _sel_cli, key="combinar_confirmar"):
        _principal = _combinar_items[_principal_id]
        _adicionales = [
            {"item_titulo": v["item_titulo"], "item_url": v["item_url"]}
            for k, v in _combinar_items.items() if k != _principal_id
        ]
        marcar_pendiente(
            clientes=_sel_cli, item_id=_principal_id, item_tipo="noticia",
            pais=PAIS, item_titulo=_principal["item_titulo"], item_url=_principal["item_url"],
            item_resumen=_principal["item_resumen"], fuentes_adicionales=_adicionales or None,
            creado_por=st.user.get("email"),
        )
        st.session_state["combinar_items"] = {}
        for _k in list(st.session_state.keys()):
            if _k.startswith("combinar_chk"):
                del st.session_state[_k]
        st.success(f"Combinadas {len(_ids)} noticias en una alerta para: {', '.join(_sel_cli)}.")
        st.rerun()


# ---------- Footer ----------
st.markdown('<div class="footer-rule"></div>', unsafe_allow_html=True)
st.markdown(
    '<p style="font-size:12px;color:var(--ink-soft);line-height:1.55;max-width:760px;">'
    'Sincronizado automáticamente cada hora desde RSS feeds y portales públicos. '
    'Las fuentes sin feed (HTML scraping) se actualizan con heurística genérica '
    'que puede tener cobertura menor.</p>',
    unsafe_allow_html=True,
)
st.markdown(
    '<div class="footer-text">Radar Legislativo · Vali Consultores</div>',
    unsafe_allow_html=True,
)
