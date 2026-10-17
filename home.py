"""Radar Legislativo — Home / landing.

Esta página se carga como `home.py` desde app.py vía st.navigation.
Muestra el grid de países disponibles. Cada card es un <a> clickeable
que navega a la página del país.
"""
from __future__ import annotations

from datetime import date

import streamlit as st

from consultas.portada import (
    stats_agenda, stats_agenda_ec, stats_ecuador, stats_noticias, stats_peru,
)

from alerts import historial
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
     critique 2026-09-22. El fallback de chip navy+texto "PE"/"EC" quedo
     repitiendo el codigo del pais al lado de su propio nombre 8 veces en
     la pagina (Nicolas, 2026-09-22: "se ve feo") - reemplazado por un
     mini SVG de la bandera real (inline, no depende de fuente/emoji del
     SO, mismo problema que se evito la primera vez). */
  display: inline-flex; align-items: center; justify-content: center;
  width: 40px; height: 40px; border-radius: 8px;
  overflow: hidden; flex-shrink: 0;
  box-shadow: inset 0 0 0 1px rgba(10,41,77,0.12);
}
.country-card .flag svg { width: 100%; height: 100%; display: block; }
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


# Mini SVG de cada bandera (inline, no emoji) - ver nota en el CSS de
# .country-card .flag sobre por que no se usa el emoji de bandera nativo.
_FLAG_PE = (
    '<svg viewBox="0 0 3 2" preserveAspectRatio="xMidYMid slice">'
    '<rect width="3" height="2" fill="#D91023"/>'
    '<rect x="1" width="1" height="2" fill="#FFFFFF"/>'
    '</svg>'
)
_FLAG_EC = (
    '<svg viewBox="0 0 3 2" preserveAspectRatio="xMidYMid slice">'
    '<rect width="3" height="1" fill="#FFD100"/>'
    '<rect y="1" width="3" height="0.5" fill="#034EA2"/>'
    '<rect y="1.5" width="3" height="0.5" fill="#EF3340"/>'
    '</svg>'
)


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
                <div class="flag">{_FLAG_PE}</div>
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
                <div class="flag">{_FLAG_EC}</div>
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
                <div class="flag">{_FLAG_PE}</div>
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
                <div class="flag">{_FLAG_EC}</div>
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
                <div class="flag">{_FLAG_PE}</div>
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
                <div class="flag">{_FLAG_EC}</div>
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
@st.cache_data(ttl=300)
def stats_alertas() -> dict:
    """Alertas enviadas segun clientes/*/historial_alertas.md."""
    fechas = [e["fecha"] for c in historial.clientes() for e in historial.entradas(c)]
    mes = date.today().isoformat()[:7]
    return {"total": len(fechas), "mes": sum(f.startswith(mes) for f in fechas)}


st.markdown('<div class="tool-block"></div>', unsafe_allow_html=True)
st.markdown('<div class="section-label">Herramienta</div>', unsafe_allow_html=True)
st.markdown('<h2 class="tool-title">Alertas</h2>', unsafe_allow_html=True)
st.markdown(
    '<p class="tool-sub">Desde Noticias, TV o los PL, "✍️ Armar alerta" abre un chat que ya '
    'conoce al cliente, sus alertas anteriores y lo que el cerebro sabe del tema.</p>',
    unsafe_allow_html=True,
)
al_cols = st.columns([2, 1])
with al_cols[0]:
    _s_al = stats_alertas()
    st.markdown(
        f"""
        <a href="/alertas" target="_self" class="country-card">
            <div class="country-header">
                <div class="flag">📝</div>
                <div class="name">Alertas</div>
            </div>
            <div class="institution">Enviadas a clientes</div>
            <div class="stats">
                <div>
                    <div class="stat-num">{_s_al["mes"]:,}</div>
                    <div class="stat-label">Este mes</div>
                </div>
                <div>
                    <div class="stat-num">{_s_al["total"]:,}</div>
                    <div class="stat-label">En total</div>
                </div>
            </div>
            <div class="cta">Redactar una alerta ↗</div>
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
