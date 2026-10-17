"""Radar Legislativo — Perú · Congreso de la República (bicameral).

Vista de proyectos de ley. Cubre el período 2026-2031 (vigente, Congreso
bicameral: Senado + Cámara de Diputados) y el período 2021-2026 (histórico,
Congreso unicameral). Lee proyectos.db en read-only.
Diseño inspirado en datadaf.com: tipografía Inter, headings en peso 900,
acentos azules, mucho whitespace.
"""
from __future__ import annotations

import datetime as dt

import pandas as pd
import streamlit as st

from scraper.sync import FECHA_INICIO_BICAMERAL
from scraper.categorias import CATEGORIA_CLIENTES_PL
from alerts import armar, historial
from ui_kit import inject_theme, render_evolucion_mensual
from consultas.peru import (
    load_catalogs,
    kpi_totals,
    evolucion_mensual,
    documentos_hoy,
    sugerencias_pendientes,
    load_proyectos,
    fetch_live_pe,
    _sync_status,
    maybe_fire_background_sync,
)
from consultas.peru import COMISIONES_ESPECIALES_LABEL
from consultas import matriz_pls





# st.set_page_config NO se llama acá porque ya lo hace app.py (entry point
# del st.navigation). Llamarlo dos veces tira StreamlitAPIException y rompe
# el render de la página.

# El logo Vali se setea desde app.py (entrada de navegación). No hace falta
# repetir st.logo() en cada página.

# ====================== CSS estilo datadaf ======================
inject_theme()
st.markdown(
    """<style>
    /* Cards internas del sidebar (date input, sync card) mantienen fondo blanco */
    section[data-testid="stSidebar"] [data-testid="stDateInput"] input,
    section[data-testid="stSidebar"] .sync-card {
      background-color: #FFFFFF !important;
    }
    section[data-testid="stSidebar"] [data-testid="stDateInput"] input,
    section[data-testid="stSidebar"] .sync-card,
    section[data-testid="stSidebar"] .sync-card * {
      color: var(--ink) !important;
    }
    section[data-testid="stSidebar"] .sync-card .label {
      color: var(--ink-mute) !important;
    }

    /* Botones del sidebar (ej "Buscar PLs nuevos en vivo"): fondo blanco,
       texto navy con peso. Selectores multiples porque Streamlit cambia
       el DOM entre versiones (button[kind], data-testid, baseweb). */
    section[data-testid="stSidebar"] button,
    section[data-testid="stSidebar"] [data-testid="stBaseButton-secondary"],
    section[data-testid="stSidebar"] [data-testid="stBaseButton-primary"],
    section[data-testid="stSidebar"] [data-testid="stButton"] button,
    section[data-testid="stSidebar"] .stButton button {
      background-color: #FFFFFF !important;
      color: var(--ink) !important;
      border: 1px solid var(--line) !important;
      font-weight: 700 !important;
      font-family: 'Inter', sans-serif !important;
    }
    section[data-testid="stSidebar"] button p,
    section[data-testid="stSidebar"] button span,
    section[data-testid="stSidebar"] button div,
    section[data-testid="stSidebar"] [data-testid="stButton"] *,
    section[data-testid="stSidebar"] .stButton * {
      color: var(--ink) !important;
    }
    section[data-testid="stSidebar"] button:hover,
    section[data-testid="stSidebar"] [data-testid="stButton"] button:hover {
      background-color: var(--bg-soft) !important;
      border-color: var(--accent) !important;
    }
    /* Excepciones: NO aplicar este estilo al boton del header (collapse
       del sidebar) que tiene fondo navy y texto blanco. */
    section[data-testid="stSidebar"] [data-testid="stSidebarHeader"] button,
    section[data-testid="stSidebar"] [data-testid="stSidebarHeader"] button * {
      background-color: transparent !important;
      color: #FFFFFF !important;
      border: 0 !important;
    }

    /* === Logo Vali: tamaño cómodo, centrado al tope === */
    [data-testid="stSidebarHeader"] {
      padding: 24px 16px 20px 16px !important;
      display: flex !important;
      justify-content: center !important;
      align-items: center !important;
      min-height: 220px !important;
      background-color: var(--ink) !important;
    }
    [data-testid="stLogo"] {
      margin: 0 auto !important;
      display: block !important;
    }
    [data-testid="stLogo"] img {
      max-height: 200px !important;
      height: 200px !important;
      width: auto !important;
      max-width: 200px !important;
      margin: 0 auto !important;
      display: block !important;
    }

    /* Reduce padding superior */
    .block-container {
      padding-top: 2rem;
      padding-bottom: 4rem;
      max-width: 1400px;
    }

    /* === Hero del país === */
    .country-eyebrow {
      font-size: 11px;
      font-weight: 800;
      letter-spacing: 0.25em;
      text-transform: uppercase;
      color: var(--accent);
      margin-bottom: 12px;
    }
    .country-title {
      font-family: Georgia, 'Times New Roman', serif;
      font-size: clamp(2.5rem, 5vw, 3.75rem);
      font-weight: 400;
      letter-spacing: -0.01em;
      line-height: 0.98;
      color: var(--ink);
      margin: 0 0 10px 0;
    }
    .country-title .accent { color: var(--accent); }
    .country-title .period {
      font-weight: 500;
      color: var(--ink-soft);
      font-size: 0.7em;
      letter-spacing: -0.01em;
    }
    .country-subtitle {
      font-size: 1.15rem;
      color: var(--ink-soft);
      /* full-width, alineado al ancho del contenedor / tabla */
      line-height: 1.6;
      margin-bottom: 36px;
    }

    /* === KPIs === */
    div[data-testid="stMetric"] {
      background-color: var(--bg);
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 16px 18px;
      box-shadow: none;
      transition: border-color .2s;
    }
    div[data-testid="stMetric"]:hover { border-color: var(--ink-mute); }
    div[data-testid="stMetricLabel"] {
      color: var(--ink-soft) !important;
      font-size: 10px !important;
      text-transform: uppercase;
      letter-spacing: 0.18em;
      font-weight: 700 !important;
    }
    div[data-testid="stMetricValue"] {
      color: var(--ink) !important;
      font-weight: 900 !important;
      font-size: 2rem !important;
      letter-spacing: -0.02em;
    }

    /* === Section titles === */
    h2, h3 { font-weight: 800; color: var(--ink); letter-spacing: -0.01em; }

    /* === Filtros: labels centrados, uppercase chiquito === */
    label[data-testid="stWidgetLabel"] p {
      font-size: 10px !important;
      text-transform: uppercase;
      letter-spacing: 0.18em;
      font-weight: 700;
      color: var(--ink-soft);
      text-align: center;
    }

    /* === Tabla === */
    div[data-testid="stDataFrame"] {
      border: 1px solid var(--line);
      border-radius: 12px;
      overflow: hidden;
    }
    /* Header de tabla: antes bloque navy solido + blanco - mas liviano
       ahora (pedido de Nicolas 2026-09-22, inspirado en como se ve la
       tabla de Quals: fondo claro, texto en gris/navy, sin el bloque de
       color pesado) - mismo espiritu, sin adoptar su paleta rojo/negro. */
    div[data-testid="stDataFrame"] thead th,
    div[data-testid="stDataFrame"] [role="columnheader"] {
      background-color: var(--bg-soft) !important;
      text-transform: none;
      letter-spacing: 0.01em;
      font-size: 12.5px !important;
      font-weight: 700 !important;
      color: var(--ink-soft) !important;
      border-bottom: 1px solid var(--line) !important;
    }
    div[data-testid="stDataFrame"] thead th *,
    div[data-testid="stDataFrame"] [role="columnheader"] * {
      color: var(--ink-soft) !important;
    }
    div[data-testid="stDataFrame"] tbody td {
      font-size: 13px;
      line-height: 1.4;
      border-bottom: 1px solid var(--line-soft) !important;
    }

    /* === Sync card === */
    .sync-card {
      background: var(--bg);
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 14px;
      font-size: 12.5px;
      color: var(--ink-soft);
    }
    .sync-card .label {
      color: var(--ink-mute);
      text-transform: uppercase;
      font-size: 10px;
      letter-spacing: 0.18em;
      font-weight: 700;
      margin-bottom: 4px;
    }
    .sync-card .value { color: var(--ink); font-weight: 600; }

    /* .detail-card y afines: centralizados en ui_kit.py (usados por
       Ecuador para el panel "Documentos del proyecto") - Perú no tiene
       panel de detalle por PL, así que no hacía falta duplicarlos acá. */

    /* Footer minimalista */
    .footer-rule {
      width: 32px; height: 2px; background: var(--ink);
      margin: 60px 0 14px 0;
    }
    .footer-text {
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0.18em;
      text-transform: uppercase;
      color: var(--ink-soft);
    }

    /* Esconde el footer 'Made with Streamlit' */
    footer { visibility: hidden; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ============ DB helpers ============



def _fmt_ago(mins: float | None) -> str:
    if mins is None:
        return "—"
    if mins < 1:
        return "hace segundos"
    if mins < 60:
        return f"hace {int(mins)} min"
    h = mins / 60
    if h < 24:
        return f"hace {int(h)} h"
    return f"hace {int(h / 24)} d"


# ====================== UI ======================

st.markdown('<div class="country-eyebrow">Radar Legislativo</div>', unsafe_allow_html=True)
st.markdown(
    '<h1 class="country-title"><span class="accent">Perú</span> · Congreso de la República <span class="period">(2026–2031, bicameral)</span></h1>',
    unsafe_allow_html=True,
)
st.markdown(
    '<p class="country-subtitle">Plataforma para seguir, filtrar y analizar los '
    'proyectos de ley presentados ante el Congreso de la República del Perú — '
    'período vigente 2026–2031 (Congreso bicameral: Senado + Cámara de Diputados).</p>',
    unsafe_allow_html=True,
)

# ---------- Live sync automatico ----------
# Al cargar la pagina consulta la API del Congreso. Si hay PLs nuevos
# que no estan en la DB, los inserta directamente para que aparezcan
# integrados en la tabla principal (sin banner separado, sin clic).
# Cache 5 min compartido entre todos los users → primera carga ~30s
# (spinner), siguientes son instant.
with st.spinner("Sincronizando con el Congreso en tiempo real..."):
    try:
        _live = fetch_live_pe()
    except Exception as _e:
        _live = {"error": str(_e), "nuevos_count": 0, "inserted": 0,
                 "total_api": 0, "total_db": 0}

# Limpiar el cache de Streamlit para que load_proyectos relea desde la
# DB y los nuevos PLs aparezcan en la tabla. Solo si insertamos algo.
if _live.get("inserted", 0) > 0:
    st.cache_data.clear()
    st.toast(
        f"⚡ {_live['inserted']} PL{'s' if _live['inserted'] != 1 else ''} "
        f"nuevo{'s' if _live['inserted'] != 1 else ''} sincronizado{'s' if _live['inserted'] != 1 else ''} "
        f"en vivo desde la API",
        icon="✅",
    )

# ---------- KPIs ----------
totals = kpi_totals()
_pls_hoy, _noticias_hoy = documentos_hoy()
cols = st.columns(len(totals) + 2)
for col, (label, val) in zip(cols, totals.items()):
    col.metric(label, f"{val:,}")
cols[-2].metric("PLs nuevos hoy", f"{_pls_hoy:,}")
cols[-1].metric("Noticias hoy", f"{_noticias_hoy:,}")

st.markdown("")

# ---------- Evolucion mensual ----------
_evol = evolucion_mensual()
if not _evol.empty:
    st.markdown("##### Evolución mensual")
    render_evolucion_mensual(_evol)

st.markdown("")

# ---------- Sugerencias de reclasificacion (clasificador ML) ----------
_sugerencias = sugerencias_pendientes()
if _sugerencias:
    with st.expander(f"🏷️ Sugerencias de reclasificación pendientes ({len(_sugerencias)})"):
        st.caption(
            "El clasificador ML (se reentrena cada semana) detecta PLs en "
            "\"Otros\" que probablemente son de otro tema, con 70-85% de "
            "confianza (arriba de eso ya se aplica solo). Revisá y decidí — "
            "se aplica en la próxima sincronización automática, no al instante."
        )
        from clasificador.decisiones_store import registrar_decision

        for s in _sugerencias:
            with st.container(border=True):
                c1, c2, c3 = st.columns([7, 1, 1])
                with c1:
                    st.markdown(
                        f"**PL {s['pley_num']}** · {s['tema_anterior']} → "
                        f"**{s['tema_sugerido']}** ({s['confidence']:.0%} confianza)  \n"
                        f"{s['titulo']}"
                    )
                with c2:
                    if st.button("✅ Aceptar", key=f"acc_sug_{s['id']}", use_container_width=True):
                        registrar_decision(sugerencia_id=s["id"], decision="aceptar")
                        st.cache_data.clear()
                        st.rerun()
                with c3:
                    if st.button("❌ Rechazar", key=f"rec_sug_{s['id']}", use_container_width=True):
                        registrar_decision(sugerencia_id=s["id"], decision="rechazar")
                        st.cache_data.clear()
                        st.rerun()

cats = load_catalogs()

# ---------- Sidebar: rango de fechas + sync ----------
with st.sidebar:
    st.markdown("### Rango de fechas")
    fec_min_iso = cats["fec_min"] or FECHA_INICIO_BICAMERAL
    fec_max_iso = cats["fec_max"] or dt.date.today().isoformat()
    fec_min = dt.date.fromisoformat(fec_min_iso)
    fec_max = dt.date.fromisoformat(fec_max_iso)
    rango = st.date_input(
        "Presentación",
        value=(fec_min, fec_max),
        min_value=fec_min,
        max_value=fec_max,
        format="YYYY-MM-DD",
    )
    if isinstance(rango, tuple) and len(rango) == 2:
        f_ini, f_fin = rango
    else:
        f_ini, f_fin = fec_min, fec_max

    st.markdown("---")
    # Auto-sync silencioso al cargar la página: si el último terminó hace
    # > SYNC_MIN_MINUTES y no hay otro corriendo, dispara `scraper update` en
    # segundo plano. No bloquea — la página renderiza con los datos actuales.
    sync_state = maybe_fire_background_sync()
    status_info = _sync_status()
    if sync_state == "started" or status_info["running"]:
        st.markdown(
            '<div class="sync-card"><div class="label">Estado</div>'
            '<div class="value">🔄 Buscando nuevos proyectos…</div>'
            '<div style="font-size:11px;color:#9CA3AF;margin-top:4px">'
            'Recarga la página en 1–2 min para ver los cambios</div></div>',
            unsafe_allow_html=True,
        )
    else:
        last = status_info["last"]
        mins = status_info["mins_ago"]
        if last:
            ago = _fmt_ago(mins)
            st.markdown(
                f"""<div class="sync-card">
                <div class="label">Actualizado</div>
                <div class="value">{ago}</div>
                <div class="label" style="margin-top:10px">Último run</div>
                <div>Nuevos: <span class="value">{last['proyectos_nuevos']}</span> · Actualizados: <span class="value">{last['proyectos_actualizados']}</span> · Errores: <span class="value">{last['errores']}</span></div>
                </div>""",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                '<div class="sync-card"><div class="label">Estado</div>'
                '<div class="value">Sin syncs previos</div></div>',
                unsafe_allow_html=True,
            )

    st.markdown("---")
    # Botón de live check: consulta la API del Congreso directamente y
    # compara con la DB. Útil para confirmar que no se perdio ningun PL
    # entre crones. Cache 2 min en fetch_live_pe → un solo API call aunque
    # multiples users hagan click cerca en el tiempo.
    live_clicked = st.button(
        "Buscar PLs nuevos en vivo",
        help="Consulta la API del Congreso en tiempo real y muestra los PLs "
             "que aún no están en nuestra base. Tarda ~30 segundos.",
        use_container_width=True,
    )

# ---------- Live check (fuera del sidebar) ----------
if live_clicked:
    with st.spinner("Consultando API del Congreso (~30 seg)…"):
        live = fetch_live_pe()
    if live["error"]:
        st.error(f"Error consultando API del Congreso: {live['error']}")
    elif live["nuevos"]:
        st.success(
            f"**{len(live['nuevos'])} PLs nuevos** detectados en la API que "
            f"aún no están en nuestra DB. El próximo cron los va a sincronizar, "
            f"pero ya los puedes ver aquí:"
        )
        df_nuevos = pd.DataFrame(live["nuevos"])
        st.dataframe(df_nuevos, hide_index=True, use_container_width=True)
        st.caption(
            f"API: {live['total_api']} PLs · DB local: {live['total_db']} PLs · "
            f"diferencia: {len(live['nuevos'])} pendientes de sincronizar."
        )
    else:
        st.info(
            f"✅ Sincronización al día. API y DB tienen los mismos "
            f"**{live['total_api']:,} PLs**."
        )

# ---------- Tabla con barra de filtros ----------
df_full = load_proyectos(f_ini, f_fin)

TODOS = "Todos"
TODAS = "Todas"


def _opciones(col: str, label_todos: str = TODOS) -> list[str]:
    if col not in df_full.columns:
        return [label_todos]
    vals = sorted({str(v) for v in df_full[col].dropna().unique() if str(v).strip()})
    return [label_todos] + vals


# tipos de comisión (scraper/comisiones_ordinarias.py) que corresponden a
# cada opción del filtro "Cámara" — "Congreso" incluye las 24 Ordinarias
# legacy (los PLs 'C' viejos siguen usándolas) y la Bicameral de Presupuesto.
_TIPOS_POR_CAMARA = {
    TODAS: ("Ordinaria", "Senado", "Diputados", "Bicameral"),
    "Congreso": ("Ordinaria", "Bicameral"),
    "Diputados": ("Diputados",),
    "Senado": ("Senado",),
}


def _opciones_comision(camara: str = TODAS) -> list[str]:
    """Lista de comisiones disponibles para filtrar — del CATÁLOGO completo
    (no solo lo que ya tiene un PL asignado), para poder elegir de antemano
    una comisión de Diputados/Senado aunque todavía no haya PLs derivados a
    ella (pedido explícito de Nicolas, 2026-09-11). Si `camara` no es
    "Todas", se acota a las comisiones propias de esa cámara — Senado y
    Diputados tienen comisiones con el MISMO nombre (ej. "Justicia y
    Derechos Humanos"), así que sin esto el dropdown quedaba con nombres
    duplicados e indistinguibles. Ver scraper/comisiones_ordinarias.py.
    Siempre se ofrece también "Comisiones Especiales" (bucket de todo lo que
    no es comisión ordinaria/de cámara/bicameral)."""
    tipos = _TIPOS_POR_CAMARA.get(camara, _TIPOS_POR_CAMARA[TODAS])
    nombres = sorted({
        c["nombre"] for c in cats.get("comisiones_catalogo", [])
        if c["tipo"] in tipos
    })
    return [TODAS] + nombres + [COMISIONES_ESPECIALES_LABEL]


def _opciones_autor() -> list[str]:
    """Lista de autores únicos extraídos del campo `autores_raw` (separados por '; ')."""
    if "Autor(es)" not in df_full.columns:
        return [TODOS]
    todos: set[str] = set()
    for s in df_full["Autor(es)"].dropna():
        for nombre in str(s).split(";"):
            n = nombre.strip()
            if n:
                todos.add(n)
    return [TODOS] + sorted(todos)


# Fila principal: lo que se usa a diario (auditoria de UX 2026-09-13 - 8-9
# dropdowns en una sola fila se sentia saturado, y "Cliente" quedaba pegado
# aparte al final en vez de ser un filtro de primera clase). El resto
# (Camara, Comision, Bancada, Proponente, Autor) es para investigacion
# puntual, no el habito diario - se mueve a un expander colapsado.
clientes = historial.clientes("PE")
TODOS_CLIENTES = "Todos"

fc = st.columns([0.9, 1.3, 1, 1])
pl_input = fc[0].text_input("PL", placeholder="ej. 14515")
sel_cliente = fc[1].selectbox(
    "Cliente", [TODOS_CLIENTES] + clientes,
    help="PLs cuyo Tema coincide con el interes real de ese cliente "
         "(scraper/categorias.py::CATEGORIA_CLIENTES_PL)",
)
sel_tema = fc[2].selectbox("Tema", _opciones("Tema"))
sel_estado = fc[3].selectbox("Estado", _opciones("Estado"))

with st.expander("🔍 Más filtros (Cámara, Comisión, Bancada, Proponente, Autor)"):
    fc2 = st.columns([0.9, 1.2, 1, 0.9, 1])
    sel_camara = fc2[0].selectbox("Cámara", _opciones("Cámara", TODAS))
    # El dropdown de Comisión se acota a la cámara elegida arriba (Senado y
    # Diputados tienen comisiones con el mismo nombre — sin esto eran
    # indistinguibles). Elegir una Comisión primero y cambiar de Cámara
    # después resetea la selección a "Todas" si ya no aplica (comportamiento
    # normal de Streamlit al cambiar las opciones de un selectbox).
    sel_comision = fc2[1].selectbox("Comisión", _opciones_comision(sel_camara))
    sel_partido = fc2[2].selectbox("Bancada", _opciones("Partido"))
    sel_proponente = fc2[3].selectbox("Proponente", _opciones("Proponente"))
    sel_autor = fc2[4].selectbox("Autor", _opciones_autor())

busqueda = st.text_input(
    "Buscar libre en título",
    placeholder="🔍  buscar texto en el título — ej. biometría, ciberseguridad, vacuna",
    label_visibility="collapsed",
)

# Aplicar filtros
df = df_full
if pl_input.strip():
    df = df[df["PL"].astype(str).str.contains(pl_input.strip(), case=False, na=False)]
if sel_camara != TODAS:
    df = df[df["Cámara"] == sel_camara]
if sel_tema != TODOS:
    df = df[df["Tema"] == sel_tema]
if sel_cliente != TODOS_CLIENTES:
    temas_cliente = CATEGORIA_CLIENTES_PL.get(sel_cliente, [])
    matriz_cliente = matriz_pls("PE").get(sel_cliente, set())
    # Union categoria-clasificador OR matriz puntual: el clasificador solo ve
    # el tema literal del PL y se pierde casos reales (confirmado 2026-09-13:
    # los 4 PLs de la matriz Bayer Crop cayeron en "Consumo masivo"/
    # "Tributos", no "Agricultura" - son leyes tributarias que afectan al
    # agro, no leyes agrarias en si).
    # + cerebro (2026-09-27): PLs con afinidad ALTA por significado con el
    # perfil del cliente aunque su Tema no este en la tabla fija (el
    # clasificador ve solo el tema literal). Se ordena por esa afinidad.
    from cerebro.embeddings import AFINIDAD_ALTA, nivel_afinidad
    from cerebro.ui import afinidad_claves
    _af_pl = afinidad_claves(tuple(f"pl_PE_{p}" for p in df["PL"]), sel_cliente)
    _afin = df["PL"].map(lambda p: _af_pl.get(f"pl_PE_{p}"))
    df = df[df["Tema"].isin(temas_cliente) | df["PL"].isin(matriz_cliente)
            | (_afin.fillna(0) >= AFINIDAD_ALTA)]
    if _af_pl:
        df = df.assign(_afin=_afin, Relevancia=_afin.map(nivel_afinidad))                .sort_values("_afin", ascending=False, na_position="last")
if sel_estado != TODOS:
    df = df[df["Estado"] == sel_estado]
if sel_comision != TODAS:
    df = df[df["_comisiones_all"].apply(lambda lst: isinstance(lst, list) and sel_comision in lst)]
if sel_partido != TODOS:
    df = df[df["Partido"] == sel_partido]
if sel_proponente != TODOS:
    df = df[df["Proponente"] == sel_proponente]
if sel_autor != TODOS:
    df = df[df["Autor(es)"].astype(str).str.contains(sel_autor, case=False, na=False, regex=False)]
if busqueda.strip():
    q = busqueda.strip().lower()
    df = df[df["Título"].astype(str).str.lower().str.contains(q, na=False)]

st.markdown(f"##### {len(df):,} proyecto(s) de {len(df_full):,} en el rango")
if sel_cliente != TODOS_CLIENTES and matriz_cliente:
    _n_matriz = df["PL"].isin(matriz_cliente).sum()
    if _n_matriz:
        st.caption(f"📋 {_n_matriz} de estos PLs están en tu matriz puntual de seguimiento.")

# Construcción del df de la tabla:
# - La columna "PL" pasa a ser la URL del portal (LinkColumn) — el regex
#   `display_text` extrae el pleyNum como label clickeable.
# - "Partido" se renombra a "Bancada" para coincidir con la terminología pedida.
# - Orden: PL · Título · Presentado · Estado · Autor · Bancada · Comisión · Tema.
df_view = df.copy()
df_view["PL"] = df_view["Portal"]  # ahora "PL" contiene la URL para LinkColumn
# Mostramos solo el autor principal en la columna (primer nombre antes del ";").
# El filtro de Autor sigue buscando en todos los firmantes (full string).
df_view["Autor(es)"] = (
    df_view["Autor(es)"].astype(str).str.split(";").str[0].str.strip().replace("nan", "")
)
df_view = df_view.rename(columns={"Partido": "Bancada", "Autor(es)": "Autor"})
COLS_VISIBLES = ["PL", "Cámara", "Título", "Presentado", "Estado", "Autor", "Bancada", "Comisión", "Tema"]
if "Relevancia" in df_view.columns:  # solo con un cliente elegido (cerebro)
    COLS_VISIBLES = ["PL", "Relevancia"] + COLS_VISIBLES[1:]
df_view = df_view[[c for c in COLS_VISIBLES if c in df_view.columns]]

# CSS para que el título envuelva (multi-línea) en vez de truncar con "..." -
# pero con techo de 3 líneas (line-clamp): antes envolvia sin limite con
# row_height fijo en 170px para TODAS las filas (la mayoria con Autor/
# Bancada/Comision vacios), desperdiciando scroll en la tabla mas densa y
# revisada a diario - hallazgo real de critique 2026-09-22. El titulo
# completo sigue a un click via el link de PL (portal del Congreso).
st.markdown(
    """<style>
    div[data-testid="stDataFrame"] [role="gridcell"] {
        white-space: normal !important;
        overflow-wrap: break-word !important;
        line-height: 1.45 !important;
        padding-top: 10px !important;
        padding-bottom: 10px !important;
    }
    div[data-testid="stDataFrame"] [role="gridcell"] > div {
        display: -webkit-box !important;
        -webkit-line-clamp: 3;
        -webkit-box-orient: vertical;
        overflow: hidden !important;
        text-overflow: ellipsis;
        white-space: normal !important;
    }
    </style>""",
    unsafe_allow_html=True,
)

tabla_pls = st.dataframe(
    df_view,
    hide_index=True,
    use_container_width=True,
    height=720,
    row_height=100,  # techo de ~3 lineas de titulo (antes 170px fijo p/ toda fila)
    column_config={
        "PL":           st.column_config.LinkColumn(
            "PL",
            # Incluye el período (ej. "2026/4"), no solo el número: dos PLs
            # de distintos períodos pueden compartir pley_num (cada período
            # reinicia la numeración desde 1) y mostrar solo el número los
            # hacía indistinguibles en la tabla.
            display_text=r"expediente/(\d+/\d+)",
            width="small",
            pinned=True,
            help="Click para abrir el expediente en el portal del Congreso. "
                 "Formato: período/número — ver columna Cámara para distinguir "
                 "PLs con el mismo número en cámaras distintas.",
        ),
        "Cámara":       st.column_config.TextColumn(
            "Cámara",
            width="small",
            help="Congreso (Ejecutivo/Comisión Permanente), Diputados o Senado. "
                 "Cada cámara numera sus PLs desde 1 — distingue PLs con el mismo número.",
        ),
        # Título: medium en vez de large → la tabla entera entra sin scroll
        # horizontal. El texto largo envuelve verticalmente (row_height=140).
        "Título":       st.column_config.TextColumn("Título", width="medium"),
        "Presentado":   st.column_config.TextColumn("Presentado", width="small"),
        "Estado":       st.column_config.TextColumn("Estado", width="small"),
        "Autor":        st.column_config.TextColumn("Autor", width="small"),
        "Bancada":      st.column_config.TextColumn("Bancada", width="small"),
        "Comisión":     st.column_config.TextColumn(
            "Comisión",
            width="medium",
            help="Comisión principal. El filtro busca en TODAS las comisiones del PL.",
        ),
        "Tema":         st.column_config.TextColumn("Tema", width="small"),
    },
    on_select="rerun",
    selection_mode="single-row",
)

# ---------- Armar alerta de un PL ----------
# Lleva el PL elegido al chat de Alertas (alerts/armar.py), igual que Noticias.
#
# Auditoria de UX 2026-09-13: este panel estaba totalmente desacoplado de la
# tabla de arriba - un dropdown aparte que obligaba a re-buscar por texto el
# mismo PL que ya estabas mirando. Ahora si clickeaste una fila en la tabla
# (selection_mode="single-row" arriba), esa fila queda pre-elegida aca -
# la busqueda por texto se deja de fallback solo para cuando no clickeaste.
_fila_seleccionada = None
try:
    _sel_rows = tabla_pls.selection.rows
    if _sel_rows and _sel_rows[0] < len(df):
        _fila_seleccionada = df.iloc[_sel_rows[0]]
except AttributeError:
    pass

if clientes and not df.empty:
    st.markdown("##### ✍️ Armar alerta de un PL")
    opciones_pl = {
        f"{row['PL']} · {row['Título'][:70]}": idx
        for idx, row in df.iterrows()
    }
    _opciones_labels = list(opciones_pl.keys())
    if _fila_seleccionada is not None:
        st.caption(
            f"PL seleccionado en la tabla: **{_fila_seleccionada['PL']}** · "
            f"{_fila_seleccionada['Título'][:80]}"
        )
        _label_preseleccionado = f"{_fila_seleccionada['PL']} · {_fila_seleccionada['Título'][:70]}"
        # El selectbox ya tiene key="marcar_pl_sel" seteado en session_state
        # desde el primer render - pasar `index=` en los reruns siguientes NO
        # tiene efecto (Streamlit lo ignora una vez que el widget ya existe).
        # Por eso, si el click en la tabla cambio, forzamos el valor a mano
        # ANTES de crear el widget.
        if (
            st.session_state.get("_ultimo_pl_click") != _fila_seleccionada["PL"]
            and _label_preseleccionado in _opciones_labels
        ):
            st.session_state["marcar_pl_sel"] = _label_preseleccionado
            st.session_state["_ultimo_pl_click"] = _fila_seleccionada["PL"]
    else:
        st.caption("Click en una fila de la tabla para elegirla acá, o buscala manualmente:")
    mc = st.columns([3, 2, 1])
    sel_pl_label = mc[0].selectbox("¿Qué PL?", _opciones_labels, key="marcar_pl_sel")
    sel_pl_cliente = mc[1].selectbox("¿Para qué cliente?", clientes, index=None,
                                     placeholder="Elige el cliente", key="marcar_pl_cli")
    if mc[2].button("✍️ Armar alerta", key="marcar_pl_btn", disabled=not sel_pl_cliente, type="primary"):
        row = df.loc[opciones_pl[sel_pl_label]]
        armar.ir_al_chat([armar.item(f"PL {row['PL']}: {row['Título']}", row["Portal"],
                                     f"Estado: {row.get('Estado')}", "PE", tipo="pl")], sel_pl_cliente)


# ---------- Footer ----------
st.markdown('<div class="footer-rule"></div>', unsafe_allow_html=True)
st.markdown(
    '<div class="footer-text">Fuente · api.congreso.gob.pe/spley-portal-service · '
    'Radar Legislativo</div>',
    unsafe_allow_html=True,
)
