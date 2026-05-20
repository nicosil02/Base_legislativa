"""Radar Legislativo - Peru - Agenda de Comisiones.

Vista de sesiones convocadas y realizadas de las comisiones del Congreso del Peru
con cruce automatico contra la base de proyectos de ley.

Fuente: API service-portal-publico-ext (visor-sesiones del Congreso).
DB: tablas sesion_* / sesiones en proyectos.db (compartida con el scraper PE).
"""
from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st


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


def _hora_to_minutes(hora: str | None) -> int:
    """Convierte hora del Congreso PE ("9:00AM", "2:30PM") a minutos desde
    medianoche para sortear correctamente. NULL/vacio -> -1 (van al final
    con sort DESC + NULLs first comportamiento de pandas via NaN).

    PE usa formato 12hr con AM/PM pegado sin espacio:
      "9:00AM"  -> 540   (9*60)
      "12:00AM" -> 0     (medianoche)
      "12:00PM" -> 720   (mediodia)
      "2:30PM"  -> 870   (14:30)
    """
    if not hora or not isinstance(hora, str):
        return -1
    s = hora.strip().upper()
    is_pm = s.endswith("PM")
    is_am = s.endswith("AM")
    if is_pm or is_am:
        s = s[:-2].strip()
    try:
        h_str, m_str = s.split(":")
        h = int(h_str)
        m = int(m_str)
    except (ValueError, AttributeError):
        return -1
    if is_am and h == 12:
        h = 0
    elif is_pm and h != 12:
        h += 12
    return h * 60 + m


# ====================== CSS (estetica Vali, identica a Peru) ======================
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
section[data-testid="stSidebar"] { background-color:var(--ink) !important; border-right:0 !important; }
section[data-testid="stSidebar"] *, section[data-testid="stSidebar"] a {
  color:#FFFFFF !important; font-family:'Inter',sans-serif !important;
}
/* Date input en sidebar: caja blanca con texto navy (override del * blanco
   de arriba). Mismo patron que pages/1_Peru.py para consistencia visual. */
section[data-testid="stSidebar"] [data-testid="stDateInput"] input {
  background-color:#FFFFFF !important;
  color:var(--ink) !important;
}
section[data-testid="stSidebar"] [data-testid="stDateInputField"],
section[data-testid="stSidebar"] [data-testid="stDateInput"] [role="presentation"],
section[data-testid="stSidebar"] [data-testid="stDateInput"] svg {
  color:var(--ink) !important;
  fill:var(--ink) !important;
}
.block-container { padding-top:2rem; padding-bottom:4rem; max-width:1400px; }

.country-eyebrow {
  font-size:11px; font-weight:800; letter-spacing:0.25em;
  text-transform:uppercase; color:var(--accent); margin-bottom:12px;
}
.country-title {
  font-size:clamp(2.5rem,5vw,3.75rem); font-weight:900;
  letter-spacing:-0.03em; line-height:0.95; color:var(--ink); margin:0 0 10px 0;
}
.country-title .accent { color:var(--accent); }
.country-title .period {
  font-weight:500; color:var(--ink-soft); font-size:0.7em; letter-spacing:-0.01em;
}
.country-subtitle {
  font-size:1.15rem; color:var(--ink-soft); line-height:1.6; margin-bottom:36px;
}
div[data-testid="stMetric"] {
  background-color:var(--bg); border:1px solid var(--line); border-radius:12px;
  padding:16px 18px; box-shadow:none; transition:border-color .2s;
}
div[data-testid="stMetric"]:hover { border-color:var(--ink-mute); }
div[data-testid="stMetricLabel"] {
  color:var(--ink-soft) !important; font-size:10px !important;
  text-transform:uppercase; letter-spacing:0.18em; font-weight:700 !important;
}
div[data-testid="stMetricValue"] {
  color:var(--ink) !important; font-weight:900 !important;
  font-size:2rem !important; letter-spacing:-0.02em;
}
h2,h3 { font-weight:800; color:var(--ink); letter-spacing:-0.01em; }
label[data-testid="stWidgetLabel"] p {
  font-size:10px !important; text-transform:uppercase; letter-spacing:0.18em;
  font-weight:700; color:var(--ink-soft); text-align:center;
}
div[data-testid="stDataFrame"] { border:1px solid var(--line); border-radius:12px; overflow:hidden; }
div[data-testid="stDataFrame"] thead th,
div[data-testid="stDataFrame"] [role="columnheader"] {
  background-color:var(--ink) !important; text-transform:uppercase;
  letter-spacing:0.06em; font-size:11px !important; font-weight:700 !important;
  color:#FFFFFF !important; border-bottom:2px solid var(--ink) !important;
}
div[data-testid="stDataFrame"] thead th *,
div[data-testid="stDataFrame"] [role="columnheader"] * { color:#FFFFFF !important; }
div[data-testid="stDataFrame"] tbody td { font-size:13px; line-height:1.4; border-bottom:1px solid var(--line-soft) !important; }
div[data-testid="stDataFrame"] [role="gridcell"] {
  white-space:pre-wrap !important; overflow-wrap:break-word !important;
  line-height:1.45 !important; padding-top:10px !important; padding-bottom:10px !important;
}
.footer-rule { width:32px; height:2px; background:var(--ink); margin:60px 0 14px 0; }
.footer-text {
  font-size:11px; font-weight:700; letter-spacing:0.18em;
  text-transform:uppercase; color:var(--ink-soft);
}
.session-card {
  background:var(--bg); border:1px solid var(--line); border-radius:14px;
  padding:24px 28px; margin-top:20px;
}
.session-card .eyebrow {
  font-size:11px; font-weight:800; letter-spacing:0.22em;
  text-transform:uppercase; color:var(--accent); margin-bottom:10px;
}
.session-card .title { font-size:1.4rem; font-weight:800; line-height:1.25; color:var(--ink); margin-bottom:6px; }
.session-card .meta { font-size:13px; color:var(--ink-soft); margin-bottom:14px; }
.pl-chip {
  display:inline-block; padding:3px 9px; border-radius:6px;
  background:#EBF2FA; color:#0A294D; font-size:11px; font-weight:700;
  font-family:'Inter',monospace; letter-spacing:0.02em; margin-right:6px;
}
footer { visibility:hidden; }
</style>""",
    unsafe_allow_html=True,
)


def get_conn() -> sqlite3.Connection:
    db = _find_db_path()
    if db is None:
        st.error("No encuentro `proyectos.db`. Inicializa con `python -m sesiones.cli init && python -m sesiones.cli update`.")
        st.stop()
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


@st.cache_data(ttl=60)
def has_sesiones_table() -> bool:
    conn = get_conn()
    r = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='sesiones'"
    ).fetchone()
    return r is not None


@st.cache_data(ttl=60)
def load_catalogs() -> dict:
    conn = get_conn()
    comisiones = [
        {"id": r[0], "nombre": r[1]}
        for r in conn.execute(
            "SELECT DISTINCT comision_id, nombre_comision FROM sesiones "
            "WHERE comision_id IS NOT NULL ORDER BY nombre_comision"
        )
    ]
    estados = sorted({
        r[0] for r in conn.execute(
            "SELECT DISTINCT estado FROM sesiones WHERE estado IS NOT NULL"
        )
    })
    fec_min, fec_max = conn.execute(
        "SELECT MIN(fecha), MAX(fecha) FROM sesiones"
    ).fetchone()
    return {"comisiones": comisiones, "estados": estados,
            "fec_min": fec_min, "fec_max": fec_max}


@st.cache_data(ttl=60)
def kpi_totals() -> dict[str, int]:
    conn = get_conn()
    today = dt.date.today().isoformat()
    r = conn.execute(
        f"""SELECT
              COUNT(*) AS total,
              SUM(CASE WHEN UPPER(estado)='CONVOCADA' AND fecha >= '{today}' THEN 1 ELSE 0 END) AS por_venir,
              SUM(CASE WHEN UPPER(estado) IN ('CELEBRADA','FINALIZADA') THEN 1 ELSE 0 END) AS realizadas,
              (SELECT COUNT(DISTINCT pley_num) FROM sesion_pl_referenciado) AS pls_distintos,
              (SELECT COUNT(*) FROM sesion_pl_referenciado) AS pls_referencias
            FROM sesiones"""
    ).fetchone()
    return {
        "Total sesiones": r["total"] or 0,
        "Próximas": r["por_venir"] or 0,
        "Realizadas": r["realizadas"] or 0,
        "PLs únicos referenciados": r["pls_distintos"] or 0,
        "Referencias totales": r["pls_referencias"] or 0,
    }


@st.cache_data(ttl=60)
def load_sesiones(fec_inicio: dt.date | None, fec_fin: dt.date | None) -> pd.DataFrame:
    conn = get_conn()
    sql = """
      SELECT s.id_sesion AS "ID",
             s.fecha AS "Fecha",
             s.hora_inicio AS "Hora",
             s.nombre_comision AS "Comisión",
             s.tipo_comision AS "Tipo",
             s.estado AS "Estado",
             s.nombre_sesion AS "Nombre",
             (SELECT COUNT(*) FROM sesion_pl_referenciado WHERE id_sesion=s.id_sesion) AS "_n_pls",
             (SELECT GROUP_CONCAT(
                       COALESCE(p.proyecto_ley, pr.proyecto_ley_raw, 'PL ' || pr.pley_num),
                       ', ')
                FROM sesion_pl_referenciado pr
                LEFT JOIN proyectos p ON p.pley_num = pr.pley_num AND p.per_par_id = pr.per_par_id
                WHERE pr.id_sesion = s.id_sesion
                ORDER BY pr.pley_num
              ) AS "PLs en agenda",
             s.link_teams AS "_link_teams",
             s.link_video AS "_link_video"
      FROM sesiones s
    """
    where, params = [], []
    if fec_inicio:
        where.append("s.fecha >= ?"); params.append(fec_inicio.isoformat())
    if fec_fin:
        where.append("s.fecha <= ?"); params.append(fec_fin.isoformat())
    if where:
        sql += " WHERE " + " AND ".join(where)
    # Orden basico por fecha (DESC); el sort por hora se hace en pandas
    # porque PE usa formato 12hr "9:00AM"/"2:00PM" que no es lexicografico-
    # sortable. Convertimos a minutos desde medianoche y ordenamos DESC.
    sql += " ORDER BY s.fecha DESC"
    df = pd.read_sql_query(sql, conn, params=params)
    if "Hora" in df.columns:
        df["_hora_min"] = df["Hora"].apply(_hora_to_minutes)
        df = df.sort_values(
            by=["Fecha", "_hora_min"],
            ascending=[False, False],
            kind="mergesort",  # stable
        ).drop(columns=["_hora_min"]).reset_index(drop=True)
    return df


# La columna "Nº PL" funciona como LinkColumn donde la celda contiene la URL
# completa al portal. Para que el TEXTO clickeable muestre el formato del PL
# (ej "14093/2025-CR") en vez del numero crudo, codificamos el label como
# query param ?pl=... antes del hash (el Angular del portal ignora el query
# string y lee el path real en el fragment #/expediente/...).
# display_text regex extrae el contenido del param ?pl=.
URL_TEMPLATE = (
    "https://wb2server.congreso.gob.pe/spley-portal/?pl={label}"
    "#/expediente/{per_par_id}/{pley_num}"
)


@st.cache_data(ttl=60)
def load_pls_de_sesion(id_sesion: int) -> pd.DataFrame:
    conn = get_conn()
    # Construimos la URL en SQL para que ya venga lista con el label embebido.
    sql = """
      SELECT pr.pley_num AS pley_num,
             'https://wb2server.congreso.gob.pe/spley-portal/?pl='
               || COALESCE(p.proyecto_ley, pr.proyecto_ley_raw, 'PL ' || pr.pley_num)
               || '#/expediente/' || COALESCE(pr.per_par_id, 2021) || '/' || pr.pley_num
             AS "Nº PL",
             COALESCE(p.tema, '—') AS "Tema",
             COALESCE(p.estado, '(no en DB)') AS "Estado",
             COALESCE(p.grupo_parlamentario, '—') AS "Bancada",
             COALESCE(p.titulo, pr.contexto, '(sin título)') AS "Título",
             pr.contexto AS "_Contexto",
             pr.proyecto_ley_raw AS "_Raw"
      FROM sesion_pl_referenciado pr
      LEFT JOIN proyectos p ON p.pley_num = pr.pley_num AND p.per_par_id = pr.per_par_id
      WHERE pr.id_sesion=?
      ORDER BY pr.pley_num
    """
    return pd.read_sql_query(sql, conn, params=(id_sesion,))


@st.cache_data(ttl=60)
def load_pls_por_comision(fec_inicio: dt.date | None, fec_fin: dt.date | None) -> pd.DataFrame:
    """Agrega PLs únicos referenciados por comisión en el rango de fechas.
    Cada fila es 1 PL en 1 comisión (un mismo PL puede aparecer en varias)."""
    conn = get_conn()
    sql = """
      SELECT s.nombre_comision AS "Comisión",
             pr.pley_num AS pley_num,
             'https://wb2server.congreso.gob.pe/spley-portal/?pl='
               || COALESCE(p.proyecto_ley, pr.proyecto_ley_raw, 'PL ' || pr.pley_num)
               || '#/expediente/' || COALESCE(pr.per_par_id, 2021) || '/' || pr.pley_num
             AS "Nº PL",
             COALESCE(p.tema, '—') AS "Tema",
             COALESCE(p.estado, '(no en DB)') AS "Estado del PL",
             COALESCE(p.titulo, '(sin título)') AS "Título",
             COUNT(DISTINCT s.id_sesion) AS "Sesiones",
             MIN(s.fecha) AS "Primera",
             MAX(s.fecha) AS "Última"
      FROM sesion_pl_referenciado pr
      JOIN sesiones s ON s.id_sesion = pr.id_sesion
      LEFT JOIN proyectos p ON p.pley_num = pr.pley_num AND p.per_par_id = pr.per_par_id
      WHERE 1=1
    """
    params: list = []
    if fec_inicio:
        sql += " AND s.fecha >= ?"; params.append(fec_inicio.isoformat())
    if fec_fin:
        sql += " AND s.fecha <= ?"; params.append(fec_fin.isoformat())
    sql += """ GROUP BY s.nombre_comision, pr.pley_num
              ORDER BY s.nombre_comision, "Sesiones" DESC, pr.pley_num """
    return pd.read_sql_query(sql, conn, params=params)


@st.cache_data(ttl=60)
def load_puntos_agenda(id_sesion: int) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT id_orden_dia, orden, descripcion_texto FROM sesion_agenda_punto "
        "WHERE id_sesion=? ORDER BY orden",
        (id_sesion,),
    ).fetchall()
    return [dict(r) for r in rows]


# ====================== UI ======================

st.markdown('<div class="country-eyebrow">Radar Legislativo · Agenda de comisiones</div>', unsafe_allow_html=True)
st.markdown(
    '<h1 class="country-title"><span class="accent">Perú</span> · Agenda de Comisiones '
    '<span class="period">(2025–2026)</span></h1>',
    unsafe_allow_html=True,
)
st.markdown(
    '<p class="country-subtitle">Sesiones convocadas y realizadas de las comisiones '
    'ordinarias, investigadoras, especiales, Subcomisión de Acusaciones Constitucionales '
    'y Comisión Permanente. Cada sesión cruza con la base de proyectos de ley para '
    'identificar automáticamente qué PLs están en agenda y enriquecerlos con tema, '
    'estado y bancada.</p>',
    unsafe_allow_html=True,
)

if not has_sesiones_table():
    st.warning(
        "Las tablas de sesiones todavía no existen en la DB. "
        "Inicializá corriendo:\n\n"
        "```\npython -m sesiones.cli init\npython -m sesiones.cli update\n```"
    )
    st.stop()

# ---------- KPIs ----------
totals = kpi_totals()
cols = st.columns(len(totals))
for col, (label, val) in zip(cols, totals.items()):
    col.metric(label, f"{val:,}")

st.markdown("")

cats = load_catalogs()

# ---------- Sidebar: rango fechas ----------
with st.sidebar:
    st.markdown("### Rango de fechas")
    today = dt.date.today()
    default_fin = today + dt.timedelta(days=30)
    fec_min_iso = cats["fec_min"] or "2025-08-01"
    fec_max_iso = cats["fec_max"] or default_fin.isoformat()
    fec_min = dt.date.fromisoformat(fec_min_iso)
    fec_max = max(dt.date.fromisoformat(fec_max_iso), default_fin)
    rango = st.date_input(
        "Sesión",
        value=(today - dt.timedelta(days=7), today + dt.timedelta(days=30)),
        min_value=fec_min,
        max_value=fec_max,
        format="YYYY-MM-DD",
    )
    if isinstance(rango, tuple) and len(rango) == 2:
        f_ini, f_fin = rango
    else:
        f_ini, f_fin = fec_min, fec_max

# ---------- Tabla principal ----------
df_full = load_sesiones(f_ini, f_fin)

TODOS = "Todas"

def _opciones(col: str) -> list[str]:
    if col not in df_full.columns:
        return [TODOS]
    return [TODOS] + sorted({str(v) for v in df_full[col].dropna().unique() if str(v).strip()})

fc = st.columns([1.4, 1, 1])
sel_comision = fc[0].selectbox("Comisión", _opciones("Comisión"))
sel_tipo = fc[1].selectbox("Tipo", _opciones("Tipo"))
con_pls = fc[2].selectbox("Con PLs en agenda", ["Todas", "Solo con PLs", "Sin PLs"])

df = df_full
if sel_comision != TODOS:
    df = df[df["Comisión"] == sel_comision]
if sel_tipo != TODOS:
    df = df[df["Tipo"] == sel_tipo]
if con_pls == "Solo con PLs":
    df = df[df["_n_pls"] > 0]
elif con_pls == "Sin PLs":
    df = df[df["_n_pls"] == 0]

st.markdown(f"##### {len(df):,} sesión(es) de {len(df_full):,} en el rango")

# Sin "Estado" — info redundante (las sesiones se filtran por fecha
# naturalmente y el estado raro vale como filtro). Columnas espejan EC.
COLS_VISIBLES = ["ID", "Fecha", "Hora", "Comisión", "PLs en agenda", "Nombre"]
df_view = df[[c for c in COLS_VISIBLES if c in df.columns]].copy()

tabla = st.dataframe(
    df_view,
    hide_index=True,
    use_container_width=True,
    height=620,
    row_height=140,
    on_select="rerun",
    selection_mode="single-row",
    column_config={
        "ID":       st.column_config.NumberColumn("ID", width="small", pinned=True,
            help="ID interno de la sesión. Click la fila para ver detalle con links a portal."),
        "Fecha":    st.column_config.TextColumn("Fecha", width="small"),
        "Hora":     st.column_config.TextColumn("Hora", width="small"),
        "Comisión": st.column_config.TextColumn("Comisión", width="medium"),
        "PLs en agenda": st.column_config.TextColumn(
            "PLs en agenda", width="large",
            help="Proyectos de ley detectados en el orden del día. Click la fila para ver títulos y links."),
        "Nombre":   st.column_config.TextColumn("Nombre de sesión", width="medium"),
    },
)

# ---------- Panel de detalle ----------
selected = []
try:
    selected = tabla.selection.rows or []
except AttributeError:
    pass

if selected and selected[0] < len(df_view):
    id_sesion = int(df_view.iloc[selected[0]]["ID"])
    sesion_row = df_full[df_full["ID"] == id_sesion].iloc[0]

    teams = sesion_row.get("_link_teams") or ""
    video = sesion_row.get("_link_video") or ""

    extras = []
    if teams:
        extras.append(f'<a href="{teams}" target="_blank" style="color:#0A294D;font-weight:700;text-decoration:underline">Teams</a>')
    if video:
        extras.append(f'<a href="{video}" target="_blank" style="color:#0A294D;font-weight:700;text-decoration:underline">Video</a>')
    extras_html = " · ".join(extras) if extras else ""

    st.markdown(
        f"""<div class="session-card">
        <div class="eyebrow">Sesión {id_sesion}</div>
        <div class="title">{sesion_row['Nombre']}</div>
        <div class="meta">{sesion_row['Comisión']} ({sesion_row['Tipo']}) ·
          {sesion_row['Fecha']} {sesion_row['Hora'] or ''} · <strong>{sesion_row['Estado']}</strong>
          {' · ' + extras_html if extras_html else ''}
        </div>
        </div>""",
        unsafe_allow_html=True,
    )

    # PLs referenciados (priorizar — esto es lo más valioso)
    df_pls = load_pls_de_sesion(id_sesion)
    if not df_pls.empty:
        st.markdown(f"##### Proyectos de Ley en agenda ({len(df_pls)})")
        df_pls_show = df_pls.drop(columns=["pley_num", "_Contexto", "_Raw"])
        st.dataframe(
            df_pls_show,
            hide_index=True,
            use_container_width=True,
            row_height=80,
            column_config={
                # Nº PL: el valor de la celda es la URL al portal; display_text
                # con regex extrae el formato "NNNNN/YYYY-XX" del query param
                # ?pl=... para mostrarlo como label clickeable.
                "Nº PL":   st.column_config.LinkColumn("Nº PL",
                    display_text=r"\?pl=([^#]+)",
                    width="small", pinned=True,
                    help="Click para abrir el expediente en el portal del Congreso."),
                "Tema":    st.column_config.TextColumn("Tema", width="small"),
                "Estado":  st.column_config.TextColumn("Estado", width="small"),
                "Bancada": st.column_config.TextColumn("Bancada", width="small"),
                "Título":  st.column_config.TextColumn("Título", width="large"),
            },
        )

    # Puntos de agenda (texto plano)
    puntos = load_puntos_agenda(id_sesion)
    if puntos:
        with st.expander(f"Orden del día completo ({len(puntos)} punto/s)", expanded=False):
            for p in puntos:
                txt = p["descripcion_texto"] or "(sin texto)"
                st.markdown(f"**Punto {p['orden']+1}** (id {p['id_orden_dia']})")
                st.text(txt[:3000] + ("..." if len(txt) > 3000 else ""))
                st.markdown("---")
else:
    st.markdown(
        '<div style="margin-top: 18px; font-size: 13px; color: #869FB2;">'
        '↑ Click sobre una fila para ver agenda + PLs cruzados de la sesión.'
        '</div>',
        unsafe_allow_html=True,
    )

# ---------- Vista por comisión ----------
st.markdown("---")
st.markdown("### Vista por comisión")
st.markdown(
    '<p style="font-size:13px;color:#869FB2;margin-bottom:14px;">'
    'PLs únicos referenciados en agendas, agrupados por comisión. '
    'Cuenta cuántas sesiones discutieron cada PL en el rango seleccionado.</p>',
    unsafe_allow_html=True,
)

df_por_com = load_pls_por_comision(f_ini, f_fin)
if df_por_com.empty:
    st.info("No hay PLs en agenda en el rango seleccionado.")
else:
    # Comisiones únicas con count de PLs
    resumen = (df_por_com.groupby("Comisión")
               .agg(pls_unicos=("pley_num", "nunique"),
                    sesiones=("Sesiones", "sum"))
               .sort_values("pls_unicos", ascending=False)
               .reset_index())
    # Comisiones donde elegir
    todas_comisiones = ["(todas)"] + resumen["Comisión"].tolist()
    sel_com_v = st.selectbox(
        "Comisión a inspeccionar",
        todas_comisiones,
        format_func=lambda x: (
            x if x == "(todas)"
            else f"{x} — {resumen.loc[resumen['Comisión']==x,'pls_unicos'].iloc[0]} PLs únicos"
        ),
    )
    if sel_com_v == "(todas)":
        df_show = df_por_com
    else:
        df_show = df_por_com[df_por_com["Comisión"] == sel_com_v]

    st.markdown(f"##### {len(df_show):,} PL(s) en agenda · {df_show['pley_num'].nunique():,} únicos")
    st.dataframe(
        df_show.drop(columns=["pley_num"]),
        hide_index=True,
        use_container_width=True,
        height=520,
        row_height=70,
        column_config={
            "Comisión":     st.column_config.TextColumn("Comisión", width="medium"),
            # Nº PL clickeable al portal (formato extraido del query param ?pl=)
            "Nº PL":        st.column_config.LinkColumn("Nº PL",
                display_text=r"\?pl=([^#]+)",
                width="small",
                help="Click para abrir el expediente en el portal del Congreso."),
            "Tema":         st.column_config.TextColumn("Tema", width="small"),
            "Estado del PL":st.column_config.TextColumn("Estado del PL", width="small"),
            "Título":       st.column_config.TextColumn("Título", width="large"),
            "Sesiones":     st.column_config.NumberColumn("Sesiones", width="small",
                help="Cantidad de sesiones de esta comisión donde el PL apareció en agenda."),
            "Primera":      st.column_config.TextColumn("1ra vez", width="small"),
            "Última":       st.column_config.TextColumn("Última", width="small"),
        },
    )

# ---------- Footer ----------
st.markdown('<div class="footer-rule"></div>', unsafe_allow_html=True)
st.markdown(
    '<div class="footer-text">Fuente · wb2server.congreso.gob.pe/service-portal-publico-ext · '
    'Radar Legislativo</div>',
    unsafe_allow_html=True,
)
