"""Radar Legislativo — Home / landing.

Esta página se carga como `home.py` desde app.py vía st.navigation.
Muestra el grid de países disponibles. Cada card es un <a> clickeable
que navega a la página del país.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import streamlit as st

from scraper.sync import PER_PAR_ID_ACTUAL

from alerts.borradores_store import list_borradores
from ui_kit import inject_theme

# ====================== CSS (estilo Vali) ======================
inject_theme()
st.markdown(
    """<style>
/* === Logo Vali: 200px centrado === */
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

.block-container { padding-top: 5vh; padding-bottom: 4rem; max-width: 1100px; }

.home-eyebrow {
  font-size: 12px; font-weight: 800; letter-spacing: 0.28em;
  text-transform: uppercase; color: var(--accent); margin-bottom: 14px;
}
.home-title {
  font-family: Georgia, 'Times New Roman', serif;
  font-size: clamp(3rem, 8vw, 5.5rem);
  font-weight: 400; letter-spacing: -0.01em; line-height: 0.98;
  color: var(--ink); margin: 0 0 24px 0;
}
.home-title .accent { color: var(--accent); }
.home-sub {
  font-size: 1.15rem; line-height: 1.6; color: var(--ink-soft);
  max-width: 720px; margin-bottom: 48px;
}

.section-label {
  font-size: 11px; font-weight: 800; letter-spacing: 0.22em;
  text-transform: uppercase; color: var(--ink-mute); margin-bottom: 14px;
}
/* Titulo grande de cada herramienta (ej "Radar Legislativo", "Agenda
   parlamentaria"). Mas pesado que un h3 para dar jerarquia visual clara
   debajo del headline "Vali Intelligence". */
.tool-title {
  font-size: 1.75rem; font-weight: 800; letter-spacing: -0.02em;
  color: var(--ink); margin: 0 0 6px 0; line-height: 1.1;
}
.tool-sub {
  font-size: 14px; color: var(--ink-soft); line-height: 1.55;
  margin-bottom: 22px; max-width: 720px;
}
.tool-block { margin-top: 36px; }

/* Country card — single clickable element.
   Hallazgo real 2026-09-22: esta card es lo primero que ve cualquiera
   que abre la app (es el Inicio) y era la UNICA card de toda la app sin
   entrada animada — Agenda/Noticias/Alertas ya tienen cardEnterList,
   acá faltaba justo donde mas se nota. */
@keyframes countryCardEnter {
  from { opacity: 0; transform: translateY(10px); }
  to   { opacity: 1; transform: translateY(0); }
}
a.country-card, div.country-card {
  display: block;
  border: 1px solid var(--line);
  border-radius: 16px;
  padding: 28px 32px;
  text-decoration: none !important;
  color: var(--ink) !important;
  transition: border-color .2s, transform .2s, box-shadow .2s;
  background: var(--bg);
  animation: countryCardEnter 420ms cubic-bezier(.16,1,.3,1) both;
}
[data-testid="stColumn"]:nth-child(2) .country-card { animation-delay: 70ms; }
[data-testid="stColumn"]:nth-child(3) .country-card { animation-delay: 140ms; }
a.country-card:hover {
  border-color: var(--accent);
  transform: translateY(-3px);
  box-shadow: 0 8px 24px rgba(10,41,77,0.08);
}
.country-card .country-header {
  display: flex; align-items: center; gap: 14px; margin-bottom: 8px;
}
.country-card .flag {
  /* Antes emoji de bandera - Windows lo renderiza como texto plano "PE"/
     "EC" sin color (par de indicador regional sin cobertura de fuente),
     y desaparecia del todo en el icono del sidebar - hallazgo real de
     critique 2026-09-22. Se adopta el fallback como chip deliberado en
     vez de depender de la fuente del SO. */
  display: inline-flex; align-items: center; justify-content: center;
  width: 40px; height: 40px; border-radius: 8px;
  background: var(--ink); color: #FFFFFF;
  font-size: 13px; font-weight: 800; letter-spacing: 0.02em; line-height: 1;
}
.country-card .name {
  font-size: 1.75rem; font-weight: 800;
  letter-spacing: -0.02em; color: var(--ink); line-height: 1;
}
.country-card .institution {
  font-size: 14px;
  color: var(--ink-soft);
  font-weight: 500;
  margin-bottom: 22px;
}
.country-card .stats {
  display: flex; gap: 36px; margin-bottom: 18px;
}
.country-card .stat-num {
  font-size: 1.6rem; font-weight: 900; color: var(--ink);
  letter-spacing: -0.02em; line-height: 1;
}
.country-card .stat-label {
  font-size: 10px; font-weight: 700; letter-spacing: 0.18em;
  text-transform: uppercase; color: var(--ink-mute); margin-top: 4px;
}
.country-card .cta {
  font-size: 11px; font-weight: 800; letter-spacing: 0.2em;
  text-transform: uppercase; color: var(--accent);
}
.country-card.soon {
  opacity: 0.6;
}
.country-card.soon .cta { color: var(--ink-mute); }
.country-card.soon .stat-num { color: var(--ink-mute); }

/* ─── Status dashboard de frescura ─────────────────────────────────────
   Pequeno grid de badges abajo del home mostrando "hace X min/hr"
   para cada fuente. Verde = fresco, amarillo = stale, gris = unknown. */
.freshness-grid {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 12px; margin-top: 14px; margin-bottom: 32px;
}
.freshness-card {
  border: 1px solid var(--line); border-radius: 10px;
  padding: 12px 14px; background: var(--bg);
  display: flex; flex-direction: column; gap: 4px;
}
.freshness-card .label {
  font-size: 10px; font-weight: 700; letter-spacing: 0.16em;
  text-transform: uppercase; color: var(--ink-mute);
}
.freshness-card .value {
  font-size: 14px; font-weight: 700; color: var(--ink);
}
.freshness-card .dot {
  display: inline-block; width: 8px; height: 8px; border-radius: 50%;
  margin-right: 6px; vertical-align: middle;
}
.freshness-card .dot.fresh   { background: #10B981; }
.freshness-card .dot.stale   { background: #F59E0B; }
.freshness-card .dot.cold    { background: #EF4444; }
.freshness-card .dot.unknown { background: #CFD9E0; }

.footer-rule {
  width: 32px; height: 2px; background: var(--ink);
  margin: 80px 0 14px 0;
}
.footer-text {
  font-size: 11px; font-weight: 700; letter-spacing: 0.18em;
  text-transform: uppercase; color: var(--ink-soft);
}
footer { visibility: hidden; }
</style>""",
    unsafe_allow_html=True,
)


# ====================== Helpers ======================
def _find_db_file(filename: str) -> Path | None:
    """Busca un archivo SQLite en varias ubicaciones razonables (repo root,
    CWD, ancestros). Funciona para `proyectos.db` y `proyectos_ec.db`."""
    here = Path(__file__).resolve().parent
    candidates = [here / filename, Path.cwd() / filename]
    cur = here
    for _ in range(5):
        candidates.append(cur / filename)
        cur = cur.parent
    for p in candidates:
        if p.exists() and p.is_file() and p.stat().st_size > 0:
            return p.resolve()
    return None


def _find_db_path() -> Path | None:
    return _find_db_file("proyectos.db")


# ====================== Freshness helpers ======================
def _human_delta(iso_str: str | None) -> tuple[str, str]:
    """Convierte un timestamp ISO en ('hace X min/hr/días', estado).

    Estado: 'fresh' (<6h), 'stale' (<24h), 'cold' (>24h), 'unknown'.
    Las fuentes corren 4x/dia con cron, asi que < 6 hr es saludable.
    """
    import datetime as _dt
    if not iso_str:
        return ("—", "unknown")
    try:
        # Normalizar: aceptar "YYYY-MM-DD HH:MM:SS" y formato ISO con Z
        s = iso_str.replace("Z", "+00:00").replace(" ", "T")
        ts = _dt.datetime.fromisoformat(s)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=_dt.timezone.utc)
        now = _dt.datetime.now(_dt.timezone.utc)
        delta = now - ts
        secs = int(delta.total_seconds())
        if secs < 60:
            txt = "hace <1 min"
        elif secs < 3600:
            txt = f"hace {secs // 60} min"
        elif secs < 86400:
            txt = f"hace {secs // 3600} h"
        else:
            txt = f"hace {secs // 86400} d"
        if secs < 6 * 3600:
            estado = "fresh"
        elif secs < 24 * 3600:
            estado = "stale"
        else:
            estado = "cold"
        return (txt, estado)
    except (ValueError, TypeError):
        return ("—", "unknown")


@st.cache_data(ttl=60)
def get_freshness() -> dict:
    """Devuelve el ultimo timestamp de actualizacion de cada fuente.

    Estrategia (en orden de prioridad):
      1. Tabla `system_heartbeats` (escrita por cada workflow exitoso,
         independiente de si hubo cambios en los datos).
      2. Fallback: tablas sync_runs (PE proyectos, sesiones; EC proyectos),
         que se escriben solo cuando hay cambios reales.
      3. Fallback final: MAX(captured_at) de la tabla de datos.
    """
    out = {"pe_proyectos": None, "pe_sesiones": None,
           "ec_proyectos": None, "ec_agenda": None,
           "alertas_diarias": None}

    # 1) Heartbeats (preferido)
    db_pe = _find_db_path()
    if db_pe:
        try:
            from sistema.heartbeat import get_all
            for src, (ts, _status) in get_all(str(db_pe)).items():
                if src in out:
                    out[src] = ts
        except Exception:
            pass

    db_ec = _find_db_file("proyectos_ec.db")
    if db_ec:
        try:
            from sistema.heartbeat import get_all
            for src, (ts, _status) in get_all(str(db_ec)).items():
                if src in out:
                    out[src] = ts
        except Exception:
            pass

    # 2) Fallback a sync_runs / max(captured_at) si heartbeats no existe todavia
    if db_pe and (out["pe_proyectos"] is None or out["pe_sesiones"] is None):
        try:
            conn = sqlite3.connect(f"file:{db_pe}?mode=ro&immutable=1", uri=True)
            try:
                if out["pe_proyectos"] is None:
                    try:
                        r = conn.execute(
                            "SELECT finished_at FROM sync_runs "
                            "WHERE finished_at IS NOT NULL ORDER BY id DESC LIMIT 1"
                        ).fetchone()
                        out["pe_proyectos"] = r[0] if r else None
                    except sqlite3.OperationalError:
                        pass
                if out["pe_sesiones"] is None:
                    try:
                        r = conn.execute(
                            "SELECT finished_at FROM sesiones_sync_runs "
                            "WHERE finished_at IS NOT NULL ORDER BY id DESC LIMIT 1"
                        ).fetchone()
                        out["pe_sesiones"] = r[0] if r else None
                    except sqlite3.OperationalError:
                        pass
            finally:
                conn.close()
        except Exception:
            pass

    if db_ec and (out["ec_proyectos"] is None or out["ec_agenda"] is None):
        try:
            conn = sqlite3.connect(f"file:{db_ec}?mode=ro&immutable=1", uri=True)
            try:
                if out["ec_proyectos"] is None:
                    try:
                        r = conn.execute(
                            "SELECT finished_at FROM sync_runs "
                            "WHERE finished_at IS NOT NULL ORDER BY id DESC LIMIT 1"
                        ).fetchone()
                        out["ec_proyectos"] = r[0] if r else None
                    except sqlite3.OperationalError:
                        pass
                if out["ec_agenda"] is None:
                    try:
                        r = conn.execute(
                            "SELECT MAX(captured_at) FROM sesiones_ec"
                        ).fetchone()
                        out["ec_agenda"] = r[0] if r and r[0] else None
                    except sqlite3.OperationalError:
                        pass
            finally:
                conn.close()
        except Exception:
            pass

    return out


@st.cache_data(ttl=60)
def stats_peru() -> dict:
    """Solo el quinquenio VIGENTE (per_par_id actual) - bug real 2026-09-16:
    esto contaba TODOS los proyectos, incluyendo el periodo historico
    2021-2026 (Congreso unicameral, ya desconectado del resto de la
    pagina por pedido explicito de Nicolas), asi que el numero no
    coincidia con lo que se ve en Perú."""
    db = _find_db_path()
    if db is None:
        return {"total": None, "leyes": None}
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro&immutable=1", uri=True)
        try:
            total = conn.execute(
                "SELECT COUNT(*) FROM proyectos WHERE per_par_id=?", (PER_PAR_ID_ACTUAL,)
            ).fetchone()[0]
            leyes = conn.execute(
                "SELECT COUNT(*) FROM proyectos WHERE per_par_id=? AND "
                "(UPPER(estado) LIKE '%PUBLIC%PERUANO%' OR UPPER(estado) LIKE '%LEY PUBLICADA%')",
                (PER_PAR_ID_ACTUAL,),
            ).fetchone()[0]
            return {"total": total, "leyes": leyes}
        finally:
            conn.close()
    except Exception:
        return {"total": None, "leyes": None}


@st.cache_data(ttl=60)
def stats_agenda() -> dict:
    """Sesiones para HOY (comisiones + pleno) y proximas convocadas.
    Se lee de proyectos.db (tabla sesiones, alimentada por el scraper PE)."""
    import datetime as _dt
    db = _find_db_path()
    if db is None:
        return {"hoy": None, "proximas": None}
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro&immutable=1", uri=True)
        try:
            existe = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='sesiones'"
            ).fetchone()
            if not existe:
                return {"hoy": 0, "proximas": 0}
            hoy = _dt.date.today().isoformat()
            sesiones_hoy = conn.execute(
                "SELECT COUNT(*) FROM sesiones WHERE fecha = ?",
                (hoy,),
            ).fetchone()[0]
            proximas = conn.execute(
                "SELECT COUNT(*) FROM sesiones "
                "WHERE UPPER(estado)='CONVOCADA' AND fecha >= ?",
                (hoy,),
            ).fetchone()[0]
            return {"hoy": sesiones_hoy, "proximas": proximas}
        finally:
            conn.close()
    except Exception:
        return {"hoy": None, "proximas": None}


@st.cache_data(ttl=60)
def stats_agenda_ec() -> dict:
    """Sesiones EC para HOY y proximas. Lee proyectos_ec.db (tabla sesiones_ec
    poblada por agenda_ec.cli desde el ICS de Zimbra)."""
    import datetime as _dt
    db = _find_db_file("proyectos_ec.db")
    if db is None:
        return {"hoy": None, "proximas": None}
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro&immutable=1", uri=True)
        try:
            existe = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='sesiones_ec'"
            ).fetchone()
            if not existe:
                return {"hoy": 0, "proximas": 0}
            hoy = _dt.date.today().isoformat()
            sesiones_hoy = conn.execute(
                "SELECT COUNT(*) FROM sesiones_ec WHERE fecha = ?", (hoy,)
            ).fetchone()[0]
            proximas = conn.execute(
                "SELECT COUNT(*) FROM sesiones_ec WHERE fecha >= ?", (hoy,)
            ).fetchone()[0]
            return {"hoy": sesiones_hoy, "proximas": proximas}
        finally:
            conn.close()
    except Exception:
        return {"hoy": None, "proximas": None}


@st.cache_data(ttl=60)
def stats_ecuador() -> dict:
    db = _find_db_file("proyectos_ec.db")
    if db is None:
        return {"total": None, "publicados": None}
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro&immutable=1", uri=True)
        try:
            total = conn.execute("SELECT COUNT(*) FROM proyectos").fetchone()[0]
            publicados = conn.execute(
                "SELECT COUNT(*) FROM proyectos WHERE UPPER(estado) = 'REGISTRO OFICIAL'"
            ).fetchone()[0]
            return {"total": total, "publicados": publicados}
        finally:
            conn.close()
    except Exception:
        return {"total": None, "publicados": None}


# ====================== UI ======================

st.markdown('<div class="home-eyebrow">Asuntos Públicos · Vali Consultores</div>', unsafe_allow_html=True)
st.markdown(
    '<h1 class="home-title">Vali <span class="accent">Intelligence</span></h1>',
    unsafe_allow_html=True,
)
st.markdown(
    '<p class="home-sub">Suite de herramientas de inteligencia regulatoria para el equipo de '
    'Asuntos Públicos y de Gobierno. Monitoreo legislativo, clasificación temática, '
    'seguimiento de cambios de estado y alertas diarias automáticas.</p>',
    unsafe_allow_html=True,
)

# Stats por herramienta
s = stats_peru()
total_pe = f"{s['total']:,}" if s["total"] is not None else "—"
leyes_pe = f"{s['leyes']:,}" if s["leyes"] is not None else "—"

s_ec = stats_ecuador()
total_ec = f"{s_ec['total']:,}" if s_ec["total"] is not None else "—"
publicados_ec = f"{s_ec['publicados']:,}" if s_ec["publicados"] is not None else "—"

s_ag = stats_agenda()
hoy_ag = f"{s_ag['hoy']:,}" if s_ag["hoy"] is not None else "—"
proximas_ag = f"{s_ag['proximas']:,}" if s_ag["proximas"] is not None else "—"

s_ag_ec = stats_agenda_ec()
hoy_ag_ec = f"{s_ag_ec['hoy']:,}" if s_ag_ec["hoy"] is not None else "—"
proximas_ag_ec = f"{s_ag_ec['proximas']:,}" if s_ag_ec["proximas"] is not None else "—"

# ====================== Herramienta 1: Radar Legislativo ======================
st.markdown('<div class="section-label">Herramienta</div>', unsafe_allow_html=True)
st.markdown('<h2 class="tool-title">Radar Legislativo</h2>', unsafe_allow_html=True)
st.markdown(
    '<p class="tool-sub">Monitoreo de proyectos de ley: clasificación temática, '
    'cambios de estado, comisiones dictaminadoras y publicación en Registro Oficial.</p>',
    unsafe_allow_html=True,
)
st.markdown('<div class="section-label">Países</div>', unsafe_allow_html=True)
cols = st.columns([1, 1, 1])

# Perú — card completa clickeable. Hard-nav del browser, pero las cookies
# de auth (vi_session, 30 dias) preservan la sesion al rerender en /peru.
with cols[0]:
    st.markdown(
        f"""
        <a href="/peru" target="_self" class="country-card">
            <div class="country-header">
                <div class="flag">PE</div>
                <div class="name">Perú</div>
            </div>
            <div class="institution">Congreso de la República · Período 2026–2031 (bicameral)</div>
            <div class="stats">
                <div>
                    <div class="stat-num">{total_pe}</div>
                    <div class="stat-label">Proyectos</div>
                </div>
                <div>
                    <div class="stat-num">{leyes_pe}</div>
                    <div class="stat-label">Publicadas</div>
                </div>
            </div>
            <div class="cta">Ver dashboard ↗</div>
        </a>
        """,
        unsafe_allow_html=True,
    )

# Ecuador — card completa clickeable.
with cols[1]:
    st.markdown(
        f"""
        <a href="/ecuador" target="_self" class="country-card">
            <div class="country-header">
                <div class="flag">EC</div>
                <div class="name">Ecuador</div>
            </div>
            <div class="institution">Asamblea Nacional · Período 2025–2029</div>
            <div class="stats">
                <div>
                    <div class="stat-num">{total_ec}</div>
                    <div class="stat-label">Proyectos</div>
                </div>
                <div>
                    <div class="stat-num">{publicados_ec}</div>
                    <div class="stat-label">Reg. Oficial</div>
                </div>
            </div>
            <div class="cta">Ver dashboard ↗</div>
        </a>
        """,
        unsafe_allow_html=True,
    )

with cols[2]:
    st.markdown("&nbsp;", unsafe_allow_html=True)

# ====================== Herramienta 2: Agenda parlamentaria ======================
st.markdown('<div class="tool-block"></div>', unsafe_allow_html=True)
st.markdown('<div class="section-label">Herramienta</div>', unsafe_allow_html=True)
st.markdown('<h2 class="tool-title">Agenda parlamentaria</h2>', unsafe_allow_html=True)
st.markdown(
    '<p class="tool-sub">Sesiones convocadas y realizadas de comisiones ordinarias, '
    'investigadoras, especiales, Subcomisión de Acusaciones Constitucionales, '
    'Comisión Permanente y Pleno.</p>',
    unsafe_allow_html=True,
)
st.markdown('<div class="section-label">Países</div>', unsafe_allow_html=True)
ag_cols = st.columns([1, 1, 1])
with ag_cols[0]:
    st.markdown(
        f"""
        <a href="/peru-agenda" target="_self" class="country-card">
            <div class="country-header">
                <div class="flag">PE</div>
                <div class="name">Perú</div>
            </div>
            <div class="institution">Congreso de la República · Período 2026–2031 (bicameral)</div>
            <div class="stats">
                <div>
                    <div class="stat-num">{hoy_ag}</div>
                    <div class="stat-label">Sesiones hoy</div>
                </div>
                <div>
                    <div class="stat-num">{proximas_ag}</div>
                    <div class="stat-label">Próximas</div>
                </div>
            </div>
            <div class="cta">Ver agenda ↗</div>
        </a>
        """,
        unsafe_allow_html=True,
    )
with ag_cols[1]:
    st.markdown(
        f"""
        <a href="/ecuador-agenda" target="_self" class="country-card">
            <div class="country-header">
                <div class="flag">EC</div>
                <div class="name">Ecuador</div>
            </div>
            <div class="institution">Asamblea Nacional · Período 2025–2029</div>
            <div class="stats">
                <div>
                    <div class="stat-num">{hoy_ag_ec}</div>
                    <div class="stat-label">Sesiones hoy</div>
                </div>
                <div>
                    <div class="stat-num">{proximas_ag_ec}</div>
                    <div class="stat-label">Próximas</div>
                </div>
            </div>
            <div class="cta">Ver agenda ↗</div>
        </a>
        """,
        unsafe_allow_html=True,
    )
with ag_cols[2]:
    st.markdown("&nbsp;", unsafe_allow_html=True)

# ====================== Herramienta 3: Noticias y coyuntura ======================
@st.cache_data(ttl=60)
def stats_noticias(pais: str) -> dict:
    """Cuenta fuentes activas + noticias capturadas para un pais."""
    db = _find_db_path()
    if db is None:
        return {"fuentes": None, "noticias": None}
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro&immutable=1", uri=True)
        try:
            existe = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='noticias_fuentes'"
            ).fetchone()
            if not existe:
                return {"fuentes": 0, "noticias": 0}
            fuentes = conn.execute(
                "SELECT COUNT(*) FROM noticias_fuentes WHERE pais=? AND activa=1",
                (pais,),
            ).fetchone()[0]
            noticias = conn.execute(
                "SELECT COUNT(n.id) FROM noticias n JOIN noticias_fuentes f "
                "ON f.id=n.fuente_id WHERE f.pais=?", (pais,),
            ).fetchone()[0]
            return {"fuentes": fuentes, "noticias": noticias}
        finally:
            conn.close()
    except Exception:
        return {"fuentes": None, "noticias": None}


_st_pe = stats_noticias("PE")
fuentes_pe = f"{_st_pe['fuentes']:,}" if _st_pe["fuentes"] is not None else "—"
noticias_pe = f"{_st_pe['noticias']:,}" if _st_pe["noticias"] is not None else "—"

_st_ec = stats_noticias("EC")
fuentes_ec = f"{_st_ec['fuentes']:,}" if _st_ec["fuentes"] is not None else "—"
noticias_ec = f"{_st_ec['noticias']:,}" if _st_ec["noticias"] is not None else "—"

st.markdown('<div class="tool-block"></div>', unsafe_allow_html=True)
st.markdown('<div class="section-label">Herramienta</div>', unsafe_allow_html=True)
st.markdown('<h2 class="tool-title">Noticias y coyuntura</h2>', unsafe_allow_html=True)
st.markdown(
    '<p class="tool-sub">Mapeo de medios, instituciones, ministerios, agencias '
    'regulatorias y gremios sectoriales. Cobertura de Coyuntura Política, '
    'Salud, Agrarios, Tech, KYC/AML.</p>',
    unsafe_allow_html=True,
)
st.markdown('<div class="section-label">Países</div>', unsafe_allow_html=True)
nt_cols = st.columns([1, 1, 1])
with nt_cols[0]:
    st.markdown(
        f"""
        <a href="/peru-noticias" target="_self" class="country-card">
            <div class="country-header">
                <div class="flag">PE</div>
                <div class="name">Perú</div>
            </div>
            <div class="institution">Medios, instituciones, gremios sectoriales</div>
            <div class="stats">
                <div>
                    <div class="stat-num">{fuentes_pe}</div>
                    <div class="stat-label">Fuentes</div>
                </div>
                <div>
                    <div class="stat-num">{noticias_pe}</div>
                    <div class="stat-label">Noticias</div>
                </div>
            </div>
            <div class="cta">Ver noticias ↗</div>
        </a>
        """,
        unsafe_allow_html=True,
    )
with nt_cols[1]:
    st.markdown(
        f"""
        <a href="/ecuador-noticias" target="_self" class="country-card">
            <div class="country-header">
                <div class="flag">EC</div>
                <div class="name">Ecuador</div>
            </div>
            <div class="institution">Medios, instituciones, gremios sectoriales</div>
            <div class="stats">
                <div>
                    <div class="stat-num">{fuentes_ec}</div>
                    <div class="stat-label">Fuentes</div>
                </div>
                <div>
                    <div class="stat-num">{noticias_ec}</div>
                    <div class="stat-label">Noticias</div>
                </div>
            </div>
            <div class="cta">Ver noticias ↗</div>
        </a>
        """,
        unsafe_allow_html=True,
    )
with nt_cols[2]:
    st.markdown("&nbsp;", unsafe_allow_html=True)

# ====================== Herramienta 4: Alertas ======================
# Auditoria de UX 2026-09-13: el home no tenia ninguna tarjeta de Alertas -
# quedaba invisible pese a ser el paso final del flujo de trabajo diario.
# 2026-09-16: los conteos son POR PERSONA (creado_por) ahora que hay login -
# antes eran un total global de TODOS los clientes/personas mezclados, lo
# que no tenia sentido una vez que los borradores son personales.
@st.cache_data(ttl=60)
def stats_alertas_mios(email: str | None) -> dict:
    try:
        todos = list_borradores()
    except Exception:
        return {"pendientes": None, "listos": None}
    if email:
        todos = [b for b in todos if b.get("creado_por") == email]
    pendientes = sum(1 for b in todos if b.get("estado") == "pendiente")
    listos = sum(1 for b in todos if b.get("estado") == "borrador")
    return {"pendientes": pendientes, "listos": listos}


st.markdown('<div class="tool-block"></div>', unsafe_allow_html=True)
st.markdown('<div class="section-label">Herramienta</div>', unsafe_allow_html=True)
st.markdown('<h2 class="tool-title">Alertas</h2>', unsafe_allow_html=True)
st.markdown(
    '<p class="tool-sub">Cola de trabajo por cliente: lo que se marca desde Noticias o '
    'Radar Legislativo se redacta automáticamente cada hora — acá se revisa, edita y '
    'copia el texto final.</p>',
    unsafe_allow_html=True,
)
al_cols = st.columns([2, 1])
with al_cols[0]:
    _yo = st.user.get("email")
    _s_al = stats_alertas_mios(_yo)
    _pend, _listos = _s_al["pendientes"], _s_al["listos"]
    pend_txt = f"{_pend:,}" if _pend is not None else "—"
    listos_txt = f"{_listos:,}" if _listos is not None else "—"
    _institucion = "Tuyos" if _yo else "Todos los clientes"
    st.markdown(
        f"""
        <a href="/alertas" target="_self" class="country-card">
            <div class="country-header">
                <div class="flag">📝</div>
                <div class="name">Borradores</div>
            </div>
            <div class="institution">{_institucion}</div>
            <div class="stats">
                <div>
                    <div class="stat-num">{pend_txt}</div>
                    <div class="stat-label">Pendientes</div>
                </div>
                <div>
                    <div class="stat-num">{listos_txt}</div>
                    <div class="stat-label">Listos</div>
                </div>
            </div>
            <div class="cta">Ver alertas ↗</div>
        </a>
        """,
        unsafe_allow_html=True,
    )
with al_cols[1]:
    st.markdown("&nbsp;", unsafe_allow_html=True)

# Footer
st.markdown('<div class="footer-rule"></div>', unsafe_allow_html=True)
st.markdown(
    '<div class="footer-text">Radar Legislativo · Vali Consultores · '
    'github.com/nicosil02/Base_legislativa</div>',
    unsafe_allow_html=True,
)
