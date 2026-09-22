"""Radar Legislativo — Ecuador · Asamblea Nacional.

Vista de proyectos de ley del período 2025-2029. Lee proyectos_ec.db en
read-only. Misma estética Vali Consultores que la página Perú.

Fuente: CSV export del portal Ppless v2
(`https://proyectosdeley.asambleanacional.gob.ec/report`). Refrescar la
data implica: descargar CSV → `python -m scraper_ec.cli importar-csv <archivo>`.
"""
from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st

from scraper.categorias import CATEGORIA_CLIENTES_PL
from alerts.borradores_store import marcar_pendiente
from ui_kit import inject_theme
from clientes.matrices import matriz_bayer_crop, matriz_incode_ec
from noticias.avances_ec import noticias_tramite_recientes

CLIENTES_DIR = Path(__file__).resolve().parent.parent / "clientes"


@st.cache_data(ttl=60)
def _matriz_pls_ec() -> dict[str, set[str]]:
    """Que clientes tienen una matriz puntual de PLs para EC (mas alla del
    filtro por categoria) - ver clientes/matrices.py. Confirmado por Nicolas
    2026-09-13: Bayer Crop funciona 100% (Syngenta comparte el mismo angulo
    Crop). Incode Ecuador es real, pero el estado que trae la matriz puede
    estar desactualizado (no se usa como fuente de verdad, solo el numero
    de PL para saber que esta en seguimiento)."""
    bayer_ec = {f["pl_numero"] for f in matriz_bayer_crop("EC")}
    incode_ec = {f["pl_numero"] for f in matriz_incode_ec()}
    return {"bayer": bayer_ec, "syngenta": bayer_ec, "incode": incode_ec}


def load_clientes() -> list[str]:
    if not CLIENTES_DIR.is_dir():
        return []
    return sorted(
        p.name for p in CLIENTES_DIR.iterdir()
        if p.is_dir() and not p.name.startswith("_")
    )


def _find_db_path() -> Path | None:
    """Busca proyectos_ec.db en varias ubicaciones razonables."""
    here = Path(__file__).resolve().parent
    candidates = [
        here.parent / "proyectos_ec.db",   # <repo>/proyectos_ec.db
        Path.cwd() / "proyectos_ec.db",
    ]
    cur = here
    for _ in range(5):
        candidates.append(cur / "proyectos_ec.db")
        cur = cur.parent
    for p in candidates:
        if p.exists() and p.is_file() and p.stat().st_size > 0:
            return p.resolve()
    return None


def _find_db_noticias_path() -> Path | None:
    """proyectos.db (noticias vive ahi, no en proyectos_ec.db) - mismo patron
    de busqueda que pages/6_Noticias_EC.py."""
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


@st.cache_data(ttl=300)
def _noticias_tramite_recientes() -> list[dict]:
    db_path = _find_db_noticias_path()
    if not db_path:
        return []
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return noticias_tramite_recientes(conn, dias=10)
    finally:
        conn.close()


@st.cache_data(ttl=300)
def documentos_hoy() -> tuple[int, int]:
    """(PLs hoy, noticias hoy) - gap real vs Dapper identificado 2026-09-20
    (ver memoria dapper-gap-analysis): ellos muestran un contador de
    "documentos publicados hoy" en el dashboard. Dato barato, ya lo
    tenemos - solo faltaba mostrarlo.

    Antes se sumaban en un solo numero ("Nuevos hoy") al lado de metricas
    puras de PL - hallazgo real de critique 2026-09-22, ver pages/1_Peru.py
    para el detalle. Separado en 2 tiles, mismo fix que Peru."""
    conn = get_conn()
    pls_hoy = conn.execute(
        "SELECT COUNT(*) FROM proyectos WHERE date(first_seen_at)=date('now')"
    ).fetchone()[0]
    noticias_hoy = 0
    db_noticias = _find_db_noticias_path()
    if db_noticias:
        nconn = sqlite3.connect(f"file:{db_noticias}?mode=ro", uri=True)
        try:
            noticias_hoy = nconn.execute(
                "SELECT COUNT(*) FROM noticias n JOIN noticias_fuentes f ON f.id=n.fuente_id "
                "WHERE f.pais='EC' AND date(n.first_seen_at)=date('now')"
            ).fetchone()[0]
        except sqlite3.OperationalError:
            pass
        finally:
            nconn.close()
    return pls_hoy, noticias_hoy


# st.set_page_config NO se llama acá: ya lo hace app.py (entry de st.navigation).
# Llamarlo dos veces tira StreamlitAPIException y rompe la página.


# ====================== CSS (estética Vali, idéntica a Perú) ======================
inject_theme()
st.markdown(
    """<style>
section[data-testid="stSidebar"] [data-testid="stDateInput"] input,
section[data-testid="stSidebar"] .sync-card {
  background-color: #FFFFFF !important;
  color: var(--ink) !important;
}
section[data-testid="stSidebar"] .sync-card * {
  color: var(--ink) !important;
}
section[data-testid="stSidebar"] .sync-card .label {
  color: var(--ink-mute) !important;
}

.block-container {
  padding-top: 2rem;
  padding-bottom: 4rem;
  max-width: 1400px;
}

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
  line-height: 1.6;
  margin-bottom: 36px;
}

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

h2, h3 { font-weight: 800; color: var(--ink); letter-spacing: -0.01em; }

label[data-testid="stWidgetLabel"] p {
  font-size: 10px !important;
  text-transform: uppercase;
  letter-spacing: 0.18em;
  font-weight: 700;
  color: var(--ink-soft);
  text-align: center;
}

div[data-testid="stDataFrame"] {
  border: 1px solid var(--line);
  border-radius: 12px;
  overflow: hidden;
}
div[data-testid="stDataFrame"] thead th,
div[data-testid="stDataFrame"] [role="columnheader"] {
  background-color: var(--ink) !important;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  font-size: 11px !important;
  font-weight: 700 !important;
  color: #FFFFFF !important;
  border-bottom: 2px solid var(--ink) !important;
}
div[data-testid="stDataFrame"] thead th *,
div[data-testid="stDataFrame"] [role="columnheader"] * {
  color: #FFFFFF !important;
}
div[data-testid="stDataFrame"] tbody td {
  font-size: 13px;
  line-height: 1.4;
  border-bottom: 1px solid var(--line-soft) !important;
}

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
footer { visibility: hidden; }
</style>""",
    unsafe_allow_html=True,
)


# ============ DB helpers ============

def get_conn() -> sqlite3.Connection:
    db = _find_db_path()
    if db is None:
        st.error(
            "No encontré `proyectos_ec.db`. Inicializá la DB con:\n\n"
            "```\npython -m scraper_ec.cli init\n"
            "python -m scraper_ec.cli importar-csv data/ppless_listado_2025-2029_snapshot.csv\n```"
        )
        st.stop()
    conn = sqlite3.connect(f"file:{db}?mode=ro&immutable=1", uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


@st.cache_data(ttl=60)
def load_catalogs() -> dict:
    conn = get_conn()
    temas = sorted(r[0] for r in conn.execute(
        "SELECT DISTINCT tema FROM proyectos WHERE tema IS NOT NULL"))
    estados = sorted(r[0] for r in conn.execute(
        "SELECT DISTINCT estado FROM proyectos WHERE estado IS NOT NULL"))
    tipos = sorted(r[0] for r in conn.execute(
        "SELECT DISTINCT tipo_proponente FROM proyectos WHERE tipo_proponente IS NOT NULL"))
    comisiones = sorted(r[0] for r in conn.execute(
        "SELECT DISTINCT comision_asignada FROM proyectos "
        "WHERE comision_asignada IS NOT NULL AND comision_asignada NOT IN ('No Asignado', 'No se Asigna Comisión por calificación Negada')"))
    fec_min, fec_max = conn.execute(
        "SELECT MIN(date(fec_presentacion)), MAX(date(fec_presentacion)) FROM proyectos"
    ).fetchone()
    return {
        "temas": temas, "estados": estados,
        "tipos_proponente": tipos, "comisiones": comisiones,
        "fec_min": fec_min, "fec_max": fec_max,
    }


@st.cache_data(ttl=60)
def kpi_totals() -> dict[str, int]:
    conn = get_conn()
    r = conn.execute(
        """SELECT
             COUNT(*) AS total,
             SUM(CASE WHEN UPPER(estado) = 'PROYECTO PRESENTADO' THEN 1 ELSE 0 END) AS presentados,
             SUM(CASE WHEN UPPER(estado) LIKE '%CALIFICACI%CONSEJO%' THEN 1 ELSE 0 END) AS en_cal,
             SUM(CASE WHEN UPPER(estado) LIKE '%AVOCO%' OR UPPER(estado) LIKE '%INFORME NO VINCULANTE%' THEN 1 ELSE 0 END) AS en_comision,
             SUM(CASE WHEN UPPER(estado) LIKE '%PRIMER DEBATE%' OR UPPER(estado) LIKE '%SEGUNDO DEBATE%' OR UPPER(estado) LIKE '%REMISI%EJECUTIVO%' THEN 1 ELSE 0 END) AS en_debate,
             SUM(CASE WHEN UPPER(estado) = 'REGISTRO OFICIAL' THEN 1 ELSE 0 END) AS publicados
           FROM proyectos"""
    ).fetchone()
    return {
        "Total": r["total"] or 0,
        "Presentados": r["presentados"] or 0,
        "En CAL": r["en_cal"] or 0,
        "En comisión": r["en_comision"] or 0,
        "En debate": r["en_debate"] or 0,
        "Publicados": r["publicados"] or 0,
    }


@st.cache_data(ttl=60)
def last_sync() -> dict | None:
    """Devuelve info de la ultima actualizacion.

    Prioridad: heartbeat del workflow (corre cada 4h aunque no haya
    cambios) → fallback a sync_runs (escrito solo si hubo cambios).
    El segundo puede ser de hace varios dias si los datos no cambiaron.
    """
    conn = get_conn()
    # 1) Heartbeat del workflow (mas fresco, refleja "el workflow corrio")
    try:
        r = conn.execute(
            "SELECT last_run, last_status FROM system_heartbeats "
            "WHERE source = 'ec_proyectos'"
        ).fetchone()
        if r:
            return {"finished_at": r[0], "started_at": r[0],
                    "status": r[1], "source": "heartbeat"}
    except Exception:
        pass
    # 2) Fallback a sync_runs (solo si hubo cambios)
    r = conn.execute(
        "SELECT started_at, finished_at, proyectos_vistos, proyectos_nuevos, "
        "       proyectos_actualizados, errores, csv_source "
        "FROM sync_runs WHERE finished_at IS NOT NULL ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return dict(r) if r else None


# URL pública del portal Ppless v2 — fallback cuando el proyecto seleccionado
# no tiene documentos enriquecidos todavía en `documentos`. Ahí el usuario
# puede abrir el portal y descargar manualmente.
PPLESS_URL = "https://proyectosdeley.asambleanacional.gob.ec/report"


@st.cache_data(ttl=60)
def load_proyectos(fec_inicio: dt.date | None, fec_fin: dt.date | None) -> pd.DataFrame:
    conn = get_conn()
    # LEFT JOIN con documentos: traemos la URL del PDF principal (el de menor
    # orden) y el conteo total de documentos. Si el proyecto no tiene docs en
    # la tabla (porque enriquecer-documentos no se corrió), pdf_url queda NULL.
    # Chequeo defensivo: si la tabla unificacion_pl no existe todavia (DB
    # vieja sin la migracion), devolvemos NULL en lugar de joinear. Evita
    # OperationalError "no such table: unificacion_pl".
    has_unif = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='unificacion_pl'"
    ).fetchone() is not None
    unif_col = (
        """(SELECT GROUP_CONCAT(up2.n_tramite, ', ')
              FROM unificacion_pl up1
              JOIN unificacion_pl up2 ON up2.grupo_id = up1.grupo_id
                                     AND up2.n_tramite != up1.n_tramite
              WHERE up1.n_tramite = p.n_tramite)"""
        if has_unif else "NULL"
    )
    # Chequeo defensivo para columna es_unificado (puede no existir aun)
    cols_proy = [r[1] for r in conn.execute("PRAGMA table_info(proyectos)")]
    has_es_unif = "es_unificado" in cols_proy
    sql = f"""
      SELECT p.n_tramite AS "_n_tramite_label",
             -- URL clickeable directa al PDF (o portal home si no hay docs).
             -- Append '#<n_tramite>' al final para que el LinkColumn pueda
             -- extraer el numero como display_text via regex.
             COALESCE(
               (SELECT url FROM documentos
                  WHERE n_tramite = p.n_tramite
                    AND UPPER(COALESCE(fase, '')) LIKE '%PROYECTO%PRESENTADO%'
                  ORDER BY orden ASC LIMIT 1),
               (SELECT url FROM documentos
                  WHERE n_tramite = p.n_tramite
                  ORDER BY orden ASC LIMIT 1),
               'https://proyectosdeley.asambleanacional.gob.ec/report?n=' || p.n_tramite
             ) || '#' || p.n_tramite AS "N. Trámite",
             {unif_col} AS "Unificado con",
             -- Flag del portal: TRUE si el checkbox "Unificado" esta marcado
             -- (scrapeado con scrapear-unificados via Playwright)
             {"COALESCE(p.es_unificado, 0)" if has_es_unif else "0"} AS "_es_unificado_portal",
             p.titulo AS "Título",
             date(p.fec_presentacion) AS "Presentado",
             date(p.last_changed_at) AS "Último cambio",
             p.estado AS "Estado",
             COALESCE(NULLIF(p.tipo_proponente, ''), '—') AS "Tipo proponente",
             COALESCE(NULLIF(p.proponentes_raw, ''), '—') AS "Proponentes",
             COALESCE(NULLIF(p.comision_asignada, ''), 'No Asignado') AS "Comisión",
             COALESCE(NULLIF(p.tema, ''), 'Otros') AS "Tema",
             (SELECT url FROM documentos
                WHERE n_tramite = p.n_tramite
                ORDER BY orden ASC LIMIT 1) AS "PDF",
             (SELECT COUNT(*) FROM documentos
                WHERE n_tramite = p.n_tramite) AS "_n_docs"
      FROM proyectos p
    """
    where, params = [], []
    if fec_inicio:
        where.append('date(p.fec_presentacion) >= ?'); params.append(fec_inicio.isoformat())
    if fec_fin:
        where.append('date(p.fec_presentacion) <= ?'); params.append(fec_fin.isoformat())
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY date(p.fec_presentacion) DESC, p.n_tramite DESC"
    return pd.read_sql_query(sql, conn, params=params)


def _fmt_ago(iso_ts: str | None) -> str:
    if not iso_ts:
        return "—"
    try:
        ts = dt.datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        delta = dt.datetime.now(dt.timezone.utc) - ts
        mins = delta.total_seconds() / 60
    except Exception:
        return iso_ts
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
    '<h1 class="country-title"><span class="accent">Ecuador</span> · Asamblea Nacional '
    '<span class="period">(2025–2029)</span></h1>',
    unsafe_allow_html=True,
)
st.markdown(
    '<p class="country-subtitle">Plataforma para seguir, filtrar y analizar todos los '
    'proyectos de ley presentados ante la Asamblea Nacional del Ecuador durante el '
    'período legislativo 2025–2029.</p>',
    unsafe_allow_html=True,
)

# ---------- Banner: no hay live para EC proyectos ----------
# El portal Ppless v2 es un Angular SPA que requiere Playwright para el
# CSV download. Playwright no funciona en Streamlit Cloud (sin Chromium).
# Por eso EC proyectos solo se actualiza via cron (cada 4-6h) en CI.
st.markdown(
    '<div style="background:#FFF8EB;border:1px solid #F59E0B;border-radius:8px;'
    'padding:8px 14px;margin-bottom:18px;font-size:13px;color:#78350F;">'
    'ℹ️ Sincronizado automáticamente <strong>cada 4-6 horas</strong> via workflow. '
    'No hay modo live para Ecuador porque el portal Ppless v2 requiere Playwright '
    '(Chromium headless), que no corre en Streamlit Cloud.</div>',
    unsafe_allow_html=True,
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

# ---------- Señal temprana: noticias de trámite de la Asamblea ----------
# En Ecuador los cambios de estado suelen salir primero en noticias de la
# Asamblea que en el portal oficial (Nicolas, 2026-09-17). No es un vinculo
# automatico a un PL especifico (ver noticias/avances_ec.py: se probo y no
# fue confiable) - es una lista corta para cruzar a mano con los PLs de
# interes de cada cliente.
_candidatas = _noticias_tramite_recientes()
if _candidatas:
    with st.expander(
        f"📰 {len(_candidatas)} noticia(s) reciente(s) de la Asamblea que podrían "
        "ser un avance de trámite (revisar a mano)"
    ):
        st.caption(
            "Suelen salir antes de que el portal oficial actualice el estado del PL. "
            "No están enlazadas a un PL específico — cruzalas con tus proyectos de interés."
        )
        for c in _candidatas:
            fecha = (c["fecha_pub"] or "")[:10]
            with st.container(border=True):
                st.markdown(f"**{fecha}** — [{c['titulo']}]({c['url']})")

cats = load_catalogs()

# ---------- Sidebar: rango de fechas + estado de import ----------
with st.sidebar:
    st.markdown("### Rango de fechas")
    fec_min_iso = cats["fec_min"] or "2025-05-14"
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
    last = last_sync()
    if last:
        src = (last.get("csv_source") or "").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        # last puede venir de heartbeat (sin counts) o de sync_runs (con counts).
        # Usamos .get() con default 0 para no crashear si los counts no estan.
        nuevos = last.get("proyectos_nuevos")
        actualizados = last.get("proyectos_actualizados")
        errores = last.get("errores")
        # Si viene de heartbeat (source=heartbeat) mostramos un layout mas simple
        # con solo el timestamp + status.
        if last.get("source") == "heartbeat" or nuevos is None:
            status = last.get("status", "ok")
            st.markdown(
                f"""<div class="sync-card">
                <div class="label">Última corrida del workflow</div>
                <div class="value">{_fmt_ago(last['finished_at'])}</div>
                <div class="label" style="margin-top:10px">Estado</div>
                <div style="font-size:13px">{status}</div>
                </div>""",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f"""<div class="sync-card">
                <div class="label">Última importación</div>
                <div class="value">{_fmt_ago(last['finished_at'])}</div>
                <div class="label" style="margin-top:10px">Fuente</div>
                <div style="font-size:11px">{src or '—'}</div>
                <div class="label" style="margin-top:10px">Último run</div>
                <div>Nuevos: <span class="value">{nuevos}</span> · Actualizados: <span class="value">{actualizados}</span> · Errores: <span class="value">{errores or 0}</span></div>
                </div>""",
                unsafe_allow_html=True,
            )
    else:
        st.markdown(
            '<div class="sync-card"><div class="label">Estado</div>'
            '<div class="value">Sin imports previos</div></div>',
            unsafe_allow_html=True,
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


def _opciones_proponente() -> list[str]:
    """Lista de proponentes únicos extraídos del campo Proponentes."""
    if "Proponentes" not in df_full.columns:
        return [TODOS]
    todos: set[str] = set()
    for s in df_full["Proponentes"].dropna():
        for chunk in str(s).split("/"):
            nombre = chunk.split("(")[0].strip()
            if nombre and nombre != "—":
                todos.add(nombre)
    return [TODOS] + sorted(todos)


# Fila principal: lo que se usa a diario (auditoria de UX 2026-09-13 -
# "Cliente" quedaba pegado aparte al final en vez de ser un filtro de
# primera clase). El resto (Comisión, Tipo proponente, Proponente) es para
# investigación puntual - se mueve a un expander colapsado.
clientes = load_clientes()
TODOS_CLIENTES = "Todos"

fc = st.columns([0.9, 1.3, 1, 1])
tramite_input = fc[0].text_input("N. Trámite", placeholder="ej. 480824")
sel_cliente = fc[1].selectbox(
    "Cliente", [TODOS_CLIENTES] + clientes,
    help="PLs cuyo Tema coincide con el interes real de ese cliente "
         "(scraper/categorias.py::CATEGORIA_CLIENTES_PL)",
)
sel_tema = fc[2].selectbox("Tema", _opciones("Tema"))
sel_estado = fc[3].selectbox("Estado", _opciones("Estado"))

with st.expander("🔍 Más filtros (Comisión, Tipo proponente, Proponente)"):
    fc2 = st.columns([1.2, 1.1, 1.1])
    sel_comision = fc2[0].selectbox("Comisión", _opciones("Comisión", label_todos=TODAS))
    sel_tipo = fc2[1].selectbox("Tipo proponente", _opciones("Tipo proponente"))
    sel_prop = fc2[2].selectbox("Proponente", _opciones_proponente())

busqueda = st.text_input(
    "Buscar libre en título",
    placeholder="🔍  buscar texto en el título — ej. inteligencia artificial, blockchain, COIP",
    label_visibility="collapsed",
)

# Aplicar filtros
df = df_full
if tramite_input.strip():
    # Filtrar por el numero (en col _n_tramite_label), no por la URL
    df = df[df["_n_tramite_label"].astype(str).str.contains(
        tramite_input.strip(), case=False, na=False
    )]
if sel_tema != TODOS:
    df = df[df["Tema"] == sel_tema]
if sel_cliente != TODOS_CLIENTES:
    temas_cliente = CATEGORIA_CLIENTES_PL.get(sel_cliente, [])
    matriz_cliente = _matriz_pls_ec().get(sel_cliente, set())
    # Union categoria-clasificador OR matriz puntual - ver misma nota en
    # pages/1_Peru.py (el clasificador se pierde casos reales que la matriz
    # de Nicolas si tiene identificados).
    df = df[df["Tema"].isin(temas_cliente) | df["_n_tramite_label"].astype(str).isin(matriz_cliente)]
if sel_estado != TODOS:
    df = df[df["Estado"] == sel_estado]
if sel_comision != TODAS:
    df = df[df["Comisión"] == sel_comision]
if sel_tipo != TODOS:
    df = df[df["Tipo proponente"] == sel_tipo]
if sel_prop != TODOS:
    df = df[df["Proponentes"].astype(str).str.contains(sel_prop, case=False, na=False, regex=False)]
if busqueda.strip():
    q = busqueda.strip().lower()
    df = df[df["Título"].astype(str).str.lower().str.contains(q, na=False)]

# Filtro adicional: solo PLs unificados (marcados en el portal O en grupo manual)
solo_unif = st.checkbox(
    "Solo PLs unificados",
    value=False,
    help="Filtra los proyectos marcados como unificados en el portal de la Asamblea "
         "(checkbox 'Unificado' en Ppless) o en un grupo manual de unificacion. "
         "Para scrapear el flag: `python -m scraper_ec.cli scrapear-unificados`. "
         "Para crear grupos: `python -m scraper_ec.cli marcar-unificacion`.",
)
if solo_unif:
    df = df[
        (df["_es_unificado_portal"].fillna(0).astype(int) == 1)
        | (df["Unificado con"].notna() & (df["Unificado con"] != ""))
    ]

st.markdown(f"##### {len(df):,} proyecto(s) de {len(df_full):,} en el rango")
if sel_cliente != TODOS_CLIENTES and matriz_cliente:
    _n_matriz = df["_n_tramite_label"].astype(str).isin(matriz_cliente).sum()
    if _n_matriz:
        st.caption(f"📋 {_n_matriz} de estos PLs están en tu matriz puntual de seguimiento.")

# Columnas visibles en la tabla principal
df_view = df.copy()
# Truncar Proponentes al primer firmante para la columna; el filtro respeta el full string.
df_view["Proponente principal"] = (
    df_view["Proponentes"].astype(str).str.split("/").str[0].str.strip()
)
# N. Trámite ahora es LinkColumn: la celda contiene la URL al PDF directo
# del proyecto (cuando ya esta enriquecido) o al portal Ppless v2 home
# como fallback. La columna _n_tramite_label trae el numero para mostrar
# como display_text.
COLS_VISIBLES = ["N. Trámite", "_n_tramite_label", "Título", "Presentado",
                 "Estado", "Tipo proponente", "Proponente principal",
                 "Comisión", "Tema", "Unificado con"]
df_view = df_view[[c for c in COLS_VISIBLES if c in df_view.columns]]

# CSS para wrap en celdas, con techo de 3 lineas - mismo fix que
# pages/1_Peru.py (critique 2026-09-22): row_height fijo desperdiciaba
# scroll en filas con celdas vacias. Texto completo a un click en el
# link de N. Tramite.
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

tabla = st.dataframe(
    df_view,
    hide_index=True,
    use_container_width=True,
    height=720,
    row_height=100,
    on_select="rerun",
    selection_mode="single-row",
    column_config={
        "N. Trámite":          st.column_config.LinkColumn(
            "N. Trámite",
            width="small",
            pinned=True,
            # Extrae el n_tramite del fragment '#XXX' al final de la URL.
            # Soporta numeros (480824) y alfanumericos (AN-GBJL-2024-0092-M).
            display_text=r"#([A-Z0-9\-]+)$",
            help="Click abre el PDF del proyecto directamente (o el portal "
                 "Ppless v2 si todavía no enriquecimos sus documentos).",
        ),
        "_n_tramite_label":    None,  # ocultar la col helper del display
        "Título":              st.column_config.TextColumn("Título", width="medium"),
        "Presentado":          st.column_config.TextColumn("Presentado", width="small"),
        "Estado":              st.column_config.TextColumn("Estado", width="small"),
        "Tipo proponente":     st.column_config.TextColumn("Tipo", width="small"),
        "Proponente principal": st.column_config.TextColumn("Proponente", width="small"),
        "Comisión":            st.column_config.TextColumn("Comisión", width="medium"),
        "Tema":                st.column_config.TextColumn("Tema", width="small"),
        "Unificado con":       st.column_config.TextColumn(
            "Unificado con", width="small",
            help="Otros PLs del mismo grupo de unificacion. Vacio si el PL "
                 "no esta unificado con ningun otro.",
        ),
    },
)

# Cuando el usuario clickea una fila, st.dataframe devuelve los índices
# seleccionados en .selection.rows. Se reusa tanto para preseleccionar el
# "Marcar PL para alerta" de abajo como para el panel de documentos.
selected_rows = []
try:
    selected_rows = tabla.selection.rows or []
except AttributeError:
    pass
_fila_seleccionada = None
if selected_rows and selected_rows[0] < len(df):
    _fila_seleccionada = df.iloc[selected_rows[0]]

# ---------- Marcar PL para alerta ----------
# Mismo mecanismo que Noticias PE/EC (alerts/borradores_store.marcar_pendiente)
# pero para PLs - deja marcar un PL nuevo o que avanzo (ver columna "Presentado"/
# "Estado") para que el agente programado redacte una alerta. item_tipo="pl".
# Auditoria de UX 2026-09-13: este panel estaba desacoplado de la tabla -
# ahora clickear una fila (selection_mode="single-row" arriba) la preselecciona.
if clientes and not df.empty:
    st.markdown("##### 📌 Marcar PL para alerta")
    opciones_pl = {
        f"{row['_n_tramite_label']} · {row['Título'][:70]}": idx
        for idx, row in df.iterrows()
    }
    _opciones_labels = list(opciones_pl.keys())
    if _fila_seleccionada is not None:
        st.caption(
            f"PL seleccionado en la tabla: **{_fila_seleccionada['_n_tramite_label']}** · "
            f"{_fila_seleccionada['Título'][:80]}"
        )
        _label_preseleccionado = (
            f"{_fila_seleccionada['_n_tramite_label']} · {_fila_seleccionada['Título'][:70]}"
        )
        # Pasar index= a un selectbox con key ya inicializado en session_state
        # no tiene efecto en los reruns siguientes - hay que setear el valor
        # a mano, y solo cuando el click en la tabla cambio.
        if (
            st.session_state.get("_ultimo_pl_click_ec") != _fila_seleccionada["_n_tramite_label"]
            and _label_preseleccionado in _opciones_labels
        ):
            st.session_state["marcar_pl_sel"] = _label_preseleccionado
            st.session_state["_ultimo_pl_click_ec"] = _fila_seleccionada["_n_tramite_label"]
    else:
        st.caption("Click en una fila de la tabla para elegirla acá, o buscala manualmente:")
    mc = st.columns([3, 2, 1])
    sel_pl_label = mc[0].selectbox("¿Qué PL?", _opciones_labels, key="marcar_pl_sel")
    sel_pl_clientes = mc[1].multiselect("¿Para qué cliente(s)?", clientes,
                                         placeholder="Elige uno o más clientes", key="marcar_pl_cli")
    if mc[2].button("Marcar", key="marcar_pl_btn", disabled=not sel_pl_clientes):
        row = df.loc[opciones_pl[sel_pl_label]]
        item_id = f"pl_EC_{row['_n_tramite_label']}"
        marcar_pendiente(
            clientes=sel_pl_clientes, item_id=item_id, item_tipo="pl",
            pais="EC", item_titulo=f"{row['_n_tramite_label']}: {row['Título']}",
            item_url=str(row["N. Trámite"]).split("#")[0], item_resumen=row.get("Estado"),
            creado_por=st.user.get("email"),
        )
        st.success(f"Marcado para: {', '.join(sel_pl_clientes)}. El agente lo redacta en la próxima hora.")

# ---------- Panel de documentos del proyecto seleccionado ----------
if selected_rows:
    row_idx = selected_rows[0]
    if row_idx < len(df_view):
        # Usar el numero crudo (col helper), no la URL
        sel_tramite = df_view.iloc[row_idx]["_n_tramite_label"]
        sel_titulo = df_view.iloc[row_idx]["Título"]

        # Query docs from DB
        conn = get_conn()
        docs = conn.execute(
            "SELECT fase, descripcion, url, orden FROM documentos "
            "WHERE n_tramite = ? ORDER BY orden ASC",
            (str(sel_tramite),),
        ).fetchall()

        # Info de unificacion (defensivo: si tabla no existe, unif=None)
        has_unif_tbl = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='unificacion_pl'"
        ).fetchone() is not None
        if has_unif_tbl:
            unif = conn.execute(
                """SELECT g.id, g.nombre, g.descripcion, g.n_tramite_principal,
                          GROUP_CONCAT(up2.n_tramite, ',') AS miembros
                   FROM unificacion_pl up
                   JOIN unificacion_grupos g ON g.id = up.grupo_id
                   JOIN unificacion_pl up2 ON up2.grupo_id = up.grupo_id
                   WHERE up.n_tramite = ?
                   GROUP BY g.id""",
                (str(sel_tramite),),
            ).fetchone()
        else:
            unif = None

        # Flag del portal (independiente del grupo manual)
        es_unif_portal = False
        try:
            r = conn.execute(
                "SELECT COALESCE(es_unificado, 0) FROM proyectos WHERE n_tramite = ?",
                (str(sel_tramite),),
            ).fetchone()
            es_unif_portal = bool(r and r[0])
        except sqlite3.OperationalError:
            pass

        # Badge de unificacion (HTML compacto)
        badges = []
        if unif:
            miembros = [m for m in (unif["miembros"] or "").split(",") if m]
            n_otros = len([m for m in miembros if m != str(sel_tramite)])
            es_principal = unif["n_tramite_principal"] == str(sel_tramite)
            label = "PRINCIPAL" if es_principal else "ACUMULADO"
            color_bg = "#0A294D" if es_principal else "#F59E0B"
            badges.append(
                f'<span style="display:inline-block; padding:4px 10px; border-radius:6px; '
                f'background:{color_bg}; color:#FFF; font-size:11px; font-weight:700; '
                f'letter-spacing:0.08em; margin-right:8px;">'
                f'⛓️ GRUPO UNIFICADO ({n_otros + 1} PLs) · {label}'
                f'</span>'
            )
        if es_unif_portal:
            badges.append(
                '<span style="display:inline-block; padding:4px 10px; border-radius:6px; '
                'background:#10B981; color:#FFF; font-size:11px; font-weight:700; '
                'letter-spacing:0.08em; margin-right:8px;">'
                '✓ MARCADO UNIFICADO EN PORTAL'
                '</span>'
            )
        unif_badge = (
            f'<div style="margin-bottom:10px;">{"".join(badges)}</div>'
            if badges else ""
        )

        st.markdown(
            f"""<div class="detail-card">
            <div class="detail-eyebrow">Documentos del proyecto</div>
            <div class="detail-title">N. Trámite {sel_tramite}</div>
            <div style="font-size:0.95rem;color:var(--ink-soft);line-height:1.4;margin-bottom:12px;">
              {sel_titulo}
            </div>
            {unif_badge}
            </div>""",
            unsafe_allow_html=True,
        )

        # Detalle del grupo de unificacion (si aplica)
        if unif:
            nombre = unif["nombre"] or "(sin nombre)"
            miembros_list = [m for m in (unif["miembros"] or "").split(",") if m]
            with st.expander(
                f"⛓️ Grupo de unificación: {nombre} ({len(miembros_list)} PLs)",
                expanded=False,
            ):
                if unif["descripcion"]:
                    st.markdown(f"*{unif['descripcion']}*")
                miembros_data = conn.execute(
                    f"""SELECT n_tramite, titulo, estado
                        FROM proyectos
                        WHERE n_tramite IN ({','.join('?'*len(miembros_list))})""",
                    miembros_list,
                ).fetchall()
                import pandas as _pd
                df_miembros = _pd.DataFrame(
                    [
                        {
                            "Es principal": "★" if m["n_tramite"] == unif["n_tramite_principal"] else "",
                            "N. Trámite": m["n_tramite"],
                            "Título": (m["titulo"] or "")[:160],
                            "Estado": m["estado"] or "—",
                        }
                        for m in miembros_data
                    ]
                )
                st.dataframe(df_miembros, hide_index=True, use_container_width=True)

        if not docs:
            st.info(
                "Este proyecto todavía no tiene documentos enriquecidos en la "
                "base. Ejecuta: `python -m scraper_ec.cli enriquecer-documentos "
                f"--limit 5 --force` para procesarlo (incluyendo {sel_tramite}). "
                "Mientras tanto puedes abrir el portal oficial:\n\n"
                f"[Abrir portal Ppless v2 →]({PPLESS_URL})"
            )
        else:
            # Una tabla de docs con link directo al PDF público
            docs_df = pd.DataFrame([dict(d) for d in docs])
            docs_df = docs_df.rename(columns={
                "fase": "Fase",
                "descripcion": "Archivo",
                "url": "Descargar",
            })[["Fase", "Archivo", "Descargar"]]
            st.dataframe(
                docs_df,
                hide_index=True,
                use_container_width=True,
                column_config={
                    "Fase":      st.column_config.TextColumn("Fase", width="medium"),
                    "Archivo":   st.column_config.TextColumn("Archivo", width="large"),
                    "Descargar": st.column_config.LinkColumn(
                        "Descargar",
                        display_text="📄 PDF",
                        width="small",
                    ),
                },
            )
else:
    st.markdown(
        '<div style="margin-top: 18px; font-size: 13px; color: var(--ink-mute);">'
        '↑ Click sobre una fila para ver los documentos del proyecto.'
        '</div>',
        unsafe_allow_html=True,
    )

# Footer
st.markdown('<div class="footer-rule"></div>', unsafe_allow_html=True)
st.markdown(
    '<div class="footer-text">Fuente · proyectosdeley.asambleanacional.gob.ec (Ppless v2) · '
    'Radar Legislativo</div>',
    unsafe_allow_html=True,
)
