"""Radar Legislativo - Ecuador - Agenda parlamentaria.

Vista de sesiones convocadas/realizadas de las comisiones de la Asamblea
Nacional, con cruce automatico contra la base de proyectos de ley EC.

Fuente: feed ICS de Zimbra (correo.asambleanacional.gob.ec) sincronizado
1+ veces al dia por GitHub Actions.
DB: tablas sesiones_ec / sesion_ec_pl_referenciado en proyectos_ec.db.

Diseno espejo de pages/3_Agenda_PE.py para mantener consistencia visual.
"""
from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st


def _find_db_path() -> Path | None:
    here = Path(__file__).resolve().parent
    candidates = [here.parent / "proyectos_ec.db", Path.cwd() / "proyectos_ec.db"]
    cur = here
    for _ in range(5):
        candidates.append(cur / "proyectos_ec.db")
        cur = cur.parent
    for p in candidates:
        if p.exists() and p.is_file() and p.stat().st_size > 0:
            return p.resolve()
    return None


def _hora_to_minutes(hora: str | None) -> int:
    """Convierte hora a minutos desde medianoche para sortear.
    EC usa 24hr ("9:00", "14:30"); aceptamos AM/PM por si acaso."""
    if not hora or not isinstance(hora, str):
        return -1
    s = hora.strip().upper()
    is_pm = s.endswith("PM")
    is_am = s.endswith("AM")
    if is_pm or is_am:
        s = s[:-2].strip()
    try:
        h_str, m_str = s.split(":")
        h, m = int(h_str), int(m_str)
    except (ValueError, AttributeError):
        return -1
    if is_am and h == 12:
        h = 0
    elif is_pm and h != 12:
        h += 12
    return h * 60 + m


# ====================== CSS (mismo del Agenda PE para consistencia) ======================
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
        st.error("No encuentro `proyectos_ec.db`. Inicializa con el workflow `enriquecer-ec.yml`.")
        st.stop()
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _upsert_live_sesiones_ec(events_new) -> int:
    """Inserta sesiones EC nuevas a la DB usando el mismo pipeline del
    sync regular (upsert_events + rematch). Asi quedan con metadata y
    matching de PLs igual que las del cron."""
    db = _find_db_path()
    if db is None or not events_new:
        return 0
    try:
        from agenda_ec.sync import upsert_events, rematch_all
        conn = sqlite3.connect(str(db), check_same_thread=False)
        try:
            nuevos, _act = upsert_events(conn, events_new)
            if nuevos > 0:
                rematch_all(conn)
            return nuevos
        finally:
            conn.close()
    except Exception as e:
        print(f"[live-upsert-agenda-ec] skip: {e}")
        return 0


@st.cache_data(ttl=300)
def fetch_live_agenda_ec() -> dict:
    """Consulta el ICS publico de Zimbra (Asamblea Nacional) en VIVO.
    Auto-upsert a la DB para que aparezcan en la tabla principal.
    """
    try:
        from agenda_ec.sync import download_ics
        from agenda_ec.ics_parser import parse_events
        text = download_ics(days_back=30, days_fwd=60, timeout=30)
        events = list(parse_events(text))
    except Exception as e:
        return {"total_api": 0, "total_db": 0, "inserted": 0, "error": str(e)}

    conn = get_conn()
    try:
        db_uids = {r[0] for r in conn.execute("SELECT uid FROM sesiones_ec")}
    finally:
        conn.close()

    api_events = [e for e in events if e.uid and e.dtstart]
    new_events = [e for e in api_events if e.uid not in db_uids]
    inserted = _upsert_live_sesiones_ec(new_events)
    return {
        "total_api": len(api_events),
        "total_db": len(db_uids),
        "inserted": inserted,
        "error": None,
    }


@st.cache_data(ttl=60)
def has_sesiones_table() -> bool:
    conn = get_conn()
    r = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='sesiones_ec'"
    ).fetchone()
    return r is not None


@st.cache_data(ttl=60)
def kpi_totals() -> dict[str, int]:
    conn = get_conn()
    today = dt.date.today().isoformat()
    r = conn.execute(
        f"""SELECT
              COUNT(*) AS total,
              SUM(CASE WHEN fecha >= '{today}' THEN 1 ELSE 0 END) AS por_venir,
              SUM(CASE WHEN fecha < '{today}' THEN 1 ELSE 0 END) AS realizadas,
              (SELECT COUNT(DISTINCT n_tramite)
                 FROM sesion_ec_pl_referenciado
                WHERE n_tramite IS NOT NULL) AS pls_distintos,
              (SELECT COUNT(*) FROM sesion_ec_pl_referenciado) AS pls_referencias
            FROM sesiones_ec"""
    ).fetchone()
    return {
        "Total sesiones": r["total"] or 0,
        "Próximas": r["por_venir"] or 0,
        "Realizadas": r["realizadas"] or 0,
        "PLs únicos referenciados": r["pls_distintos"] or 0,
        "Referencias totales": r["pls_referencias"] or 0,
    }


@st.cache_data(ttl=60)
def load_catalogs() -> dict:
    conn = get_conn()
    comisiones = sorted(
        {r[0] for r in conn.execute(
            "SELECT DISTINCT nombre_comision FROM sesiones_ec "
            "WHERE nombre_comision IS NOT NULL AND nombre_comision != ''"
        ) if r[0]}
    )
    modalidades = sorted(
        {r[0] for r in conn.execute(
            "SELECT DISTINCT modalidad FROM sesiones_ec "
            "WHERE modalidad IS NOT NULL AND modalidad != ''"
        ) if r[0]}
    )
    fec_min, fec_max = conn.execute(
        "SELECT MIN(fecha), MAX(fecha) FROM sesiones_ec"
    ).fetchone()
    return {"comisiones": comisiones, "modalidades": modalidades,
            "fec_min": fec_min, "fec_max": fec_max}


@st.cache_data(ttl=60)
def load_sesiones(fec_inicio: dt.date | None, fec_fin: dt.date | None) -> pd.DataFrame:
    conn = get_conn()
    # "Nombre de sesión": SUMMARY con la cola "modalidad X" removida en SQL.
    # Asi se ve igual de limpio que el de PE ("DÉCIMA TERCERA SESIÓN ORDINARIA
    # DE LA COMISIÓN AGRARIA") y no mete "modalidad virtual" en el title.
    sql = """
      SELECT s.uid AS "UID",
             s.fecha AS "Fecha",
             s.hora_inicio AS "Hora",
             COALESCE(s.nombre_comision, '—') AS "Comisión",
             COALESCE(s.status, '—') AS "Estado",
             (SELECT COUNT(*) FROM sesion_ec_pl_referenciado
                WHERE uid=s.uid AND n_tramite IS NOT NULL) AS "_n_pls",
             (SELECT GROUP_CONCAT(COALESCE(p.n_tramite, m.n_tramite), ', ')
                FROM sesion_ec_pl_referenciado m
                LEFT JOIN proyectos p ON p.n_tramite = m.n_tramite
                WHERE m.uid = s.uid AND m.n_tramite IS NOT NULL
                ORDER BY m.score DESC) AS "PLs en agenda",
             -- Limpieza del SUMMARY: cortar en ", modalidad" / " modalidad"
             TRIM(
               CASE
                 WHEN INSTR(LOWER(s.summary), ', modalidad') > 0
                   THEN SUBSTR(s.summary, 1, INSTR(LOWER(s.summary), ', modalidad') - 1)
                 WHEN INSTR(LOWER(s.summary), ' modalidad') > 0
                   THEN SUBSTR(s.summary, 1, INSTR(LOWER(s.summary), ' modalidad') - 1)
                 ELSE s.summary
               END
             ) AS "Nombre de sesión"
      FROM sesiones_ec s
    """
    where, params = [], []
    if fec_inicio:
        where.append("s.fecha >= ?"); params.append(fec_inicio.isoformat())
    if fec_fin:
        where.append("s.fecha <= ?"); params.append(fec_fin.isoformat())
    if where:
        sql += " WHERE " + " AND ".join(where)
    # Sort por fecha en SQL, por hora en pandas (helper _hora_to_minutes
    # convierte cualquier formato — 24hr o 12hr — a numero sortable).
    # Dentro del dia: HORA DESC (la mas tarde primero, mas temprano abajo).
    sql += " ORDER BY s.fecha DESC"
    df = pd.read_sql_query(sql, conn, params=params)
    if "Hora" in df.columns:
        df["_hora_min"] = df["Hora"].apply(_hora_to_minutes)
        df = df.sort_values(
            by=["Fecha", "_hora_min"],
            ascending=[False, False],
            kind="mergesort",
        ).drop(columns=["_hora_min"]).reset_index(drop=True)
    return df


@st.cache_data(ttl=60)
def load_pls_de_sesion(uid: str) -> pd.DataFrame:
    """Devuelve los PLs identificados en una sesion. La columna "Nº tramite"
    es URL al PDF directo (fileservice publico, sin auth) o al portal home
    como fallback. Append '#<n_tramite>' al final para que el LinkColumn
    pueda extraer el numero como display_text via regex.
    """
    conn = get_conn()
    sql = """
      SELECT
        COALESCE(
          (SELECT url FROM documentos
             WHERE n_tramite = m.n_tramite
               AND UPPER(COALESCE(fase, '')) LIKE '%PROYECTO%PRESENTADO%'
             ORDER BY orden ASC LIMIT 1),
          (SELECT url FROM documentos
             WHERE n_tramite = m.n_tramite
             ORDER BY orden ASC LIMIT 1),
          'https://proyectosdeley.asambleanacional.gob.ec/report?n=' || m.n_tramite
        ) || '#' || m.n_tramite AS "Nº trámite",
        COALESCE(p.titulo, '(no en DB)') AS "Título",
        COALESCE(p.estado, '—') AS "Estado",
        COALESCE(p.comision_asignada, '—') AS "Comisión asignada",
        COALESCE(p.tema, '—') AS "Tema",
        m.score AS "_score"
      FROM sesion_ec_pl_referenciado m
      LEFT JOIN proyectos p ON p.n_tramite = m.n_tramite
      WHERE m.uid = ? AND m.n_tramite IS NOT NULL
      ORDER BY m.score DESC
    """
    return pd.read_sql_query(sql, conn, params=(uid,))


@st.cache_data(ttl=60)
def load_descripcion(uid: str) -> tuple[str, str, str, str]:
    """Devuelve (descripcion, location, fecha, hora_inicio) para mostrar
    el detalle completo de la sesion seleccionada."""
    conn = get_conn()
    r = conn.execute(
        "SELECT descripcion, location, fecha, hora_inicio FROM sesiones_ec WHERE uid = ?",
        (uid,),
    ).fetchone()
    if r is None:
        return ("", "", "", "")
    return (r[0] or "", r[1] or "", r[2] or "", r[3] or "")


# ====================== UI ======================

st.markdown('<div class="country-eyebrow">Radar Legislativo · Agenda parlamentaria</div>', unsafe_allow_html=True)
st.markdown(
    '<h1 class="country-title"><span class="accent">Ecuador</span> · Agenda parlamentaria '
    '<span class="period">(2025–2029)</span></h1>',
    unsafe_allow_html=True,
)
st.markdown(
    '<p class="country-subtitle">Sesiones convocadas y realizadas de las comisiones '
    'especializadas y el Pleno de la Asamblea Nacional. Cada sesión cruza '
    'con la base de proyectos de ley para identificar automáticamente qué PLs se '
    'debaten (matching por título contra la descripción del orden del día).</p>',
    unsafe_allow_html=True,
)

if not has_sesiones_table():
    st.warning(
        "Las tablas de agenda EC todavía no existen en la DB. "
        "Inicializa corriendo:\n\n"
        "```\npython -m agenda_ec.cli --db proyectos_ec.db init\n"
        "python -m agenda_ec.cli --db proyectos_ec.db update\n```"
    )
    st.stop()

# ---------- Live sync (tiempo real automatico) ----------
# Lee feed Zimbra, auto-upsert sesiones nuevas a la DB → aparecen en la
# tabla principal sin clic.
with st.spinner("Sincronizando agenda en vivo con la Asamblea Nacional..."):
    try:
        _live = fetch_live_agenda_ec()
    except Exception as _e:
        _live = {"error": str(_e), "inserted": 0, "total_api": 0, "total_db": 0}

if _live.get("inserted", 0) > 0:
    st.cache_data.clear()
    st.toast(
        f"⚡ {_live['inserted']} sesión{'es' if _live['inserted'] != 1 else ''} "
        f"nueva{'s' if _live['inserted'] != 1 else ''} sincronizada{'s' if _live['inserted'] != 1 else ''} "
        f"en vivo desde la Asamblea",
        icon="✓",
    )

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
    fec_min_iso = cats["fec_min"] or "2025-05-01"
    fec_max_iso = cats["fec_max"] or default_fin.isoformat()
    fec_min = dt.date.fromisoformat(fec_min_iso)
    fec_max = max(dt.date.fromisoformat(fec_max_iso), default_fin)
    rango = st.date_input(
        "Sesión",
        value=(today - dt.timedelta(days=14), today + dt.timedelta(days=30)),
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

fc = st.columns([1.6, 1])
sel_comision = fc[0].selectbox("Comisión", _opciones("Comisión"))
con_pls = fc[1].selectbox("Con PLs en agenda", ["Todas", "Solo con PLs", "Sin PLs"])

df = df_full
if sel_comision != TODOS:
    df = df[df["Comisión"] == sel_comision]
if con_pls == "Solo con PLs":
    df = df[df["_n_pls"] > 0]
elif con_pls == "Sin PLs":
    df = df[df["_n_pls"] == 0]

st.markdown(f"##### {len(df):,} sesión(es) de {len(df_full):,} en el rango")

# Columnas: Fecha, Hora, Comision, PLs en agenda, Nombre de sesion.
# (Sin Estado — solo confunde, todas las sesiones del feed son CONFIRMED)
COLS_VISIBLES = ["Fecha", "Hora", "Comisión", "PLs en agenda", "Nombre de sesión"]
df_view = df[[c for c in COLS_VISIBLES if c in df.columns]].copy()

# Reset index para que el index numerico (0..N) sea el row id que devuelve
# selection.rows — sin esto la seleccion mapea a el index original del df_full
df_view = df_view.reset_index(drop=True)
df_with_uid = df.reset_index(drop=True)  # paralelo, contiene UID para lookup

tabla = st.dataframe(
    df_view,
    hide_index=True,
    use_container_width=True,
    height=620,
    on_select="rerun",
    selection_mode="single-row",
)

# ---------- Detalle de la sesion seleccionada ----------
sel_rows = (tabla.selection or {}).get("rows", [])
if sel_rows:
    idx = sel_rows[0]
    if 0 <= idx < len(df_with_uid):
        uid = df_with_uid.iloc[idx]["UID"]
        descripcion, location, fecha_sel, hora_sel = load_descripcion(uid)
        comision_sel = df_with_uid.iloc[idx].get("Comisión") or "—"
        titulo_sel = df_with_uid.iloc[idx].get("Nombre de sesión") or "—"

        st.markdown(
            f"""
            <div class="session-card">
              <div class="eyebrow">Detalle de la sesión</div>
              <div class="title">{titulo_sel}</div>
              <div class="meta">📅 {fecha_sel} · ⏰ {hora_sel or "—"} · 📍 {location or "—"}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        if descripcion.strip():
            with st.expander("Orden del día / descripción completa", expanded=True):
                st.write(descripcion)

        df_pls = load_pls_de_sesion(uid)
        if not df_pls.empty:
            st.markdown(f"##### PLs identificados ({len(df_pls)})")
            st.dataframe(
                df_pls.drop(columns=["_score"], errors="ignore"),
                hide_index=True,
                use_container_width=True,
                column_config={
                    "Nº trámite": st.column_config.LinkColumn(
                        "Nº trámite",
                        # Extrae el n_tramite del fragment '#XXX' al final
                        # de la URL. Soporta numeros (480824) y alfanumericos
                        # (AN-GBJL-2024-0092-M).
                        display_text=r"#([A-Z0-9\-]+)$",
                        help="Abre el PDF del proyecto directamente (o el portal si "
                             "aun no enriquecimos sus documentos)",
                    ),
                },
            )
            st.caption(
                "💡 Click en el Nº trámite abre el PDF del proyecto directamente. "
                "Si todavía no tenemos sus documentos enriquecidos, abre el "
                "portal Ppless v2 (pegá el número en el filtro)."
            )
        else:
            st.info("No se identificaron PLs específicos en esta sesión "
                    "(la descripción puede referir a temas sin proyecto de ley registrado).")

# ---------- Footer ----------
st.markdown('<div class="footer-rule"></div>', unsafe_allow_html=True)
st.markdown(
    '<div class="footer-text">Radar Legislativo · Vali Consultores · '
    'Fuente: Asamblea Nacional del Ecuador (feed Zimbra)</div>',
    unsafe_allow_html=True,
)
