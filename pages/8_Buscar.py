"""Radar Legislativo - Buscar por significado en todo (PLs PE/EC, noticias,
sesiones del Congreso y la Asamblea).

A diferencia de los filtros de las otras paginas (palabras exactas), esto
busca por SIGNIFICADO: "datos biometricos" encuentra tambien "reconocimiento
facial" o "identidad digital" aunque no compartan palabras. Usa el cerebro
(cerebro/embeddings.py): vectores de Gemini en data/cerebro.db, bajado del
release "cerebro" que actualiza .github/workflows/cerebro.yml.
"""
from __future__ import annotations

import html
import json

import streamlit as st

from ui_kit import inject_theme

inject_theme()
st.markdown(
    """<style>
.block-container { padding-top:2rem; padding-bottom:4rem; max-width:1100px; }
.country-eyebrow { font-size:11px; font-weight:800; letter-spacing:0.25em;
  text-transform:uppercase; color:var(--accent); margin-bottom:12px; }
.country-title { font-family: Georgia, 'Times New Roman', serif;
  font-size:clamp(2.2rem,4.5vw,3.2rem); font-weight:400; letter-spacing:-0.01em;
  line-height:0.98; color:var(--ink); margin:0 0 10px 0; }
.country-title .accent { color:var(--accent); }
.country-subtitle { font-size:1.05rem; color:var(--ink-soft); line-height:1.6; margin-bottom:28px; }
.item-card { border: 1px solid var(--line-soft); border-radius: 10px; padding: 12px 16px; margin: 8px 0; }
.item-fuente { font-size:11px; font-weight:700; color:var(--ink-mute); text-transform:uppercase; letter-spacing:0.06em; }
.item-titulo { font-size:15px; font-weight:700; color:var(--ink); line-height:1.35; margin: 4px 0; }
.item-titulo a { color:var(--ink); text-decoration:none; }
.item-titulo a:hover { color:var(--accent-red); text-decoration:underline; }
.item-meta { font-size:12px; color:var(--ink-mute); }
footer { visibility:hidden; }
</style>""",
    unsafe_allow_html=True,
)

st.markdown('<div class="country-eyebrow">Vali Intelligence · Cerebro</div>', unsafe_allow_html=True)
st.markdown('<h1 class="country-title">Buscar <span class="accent">por significado</span></h1>',
            unsafe_allow_html=True)
st.markdown(
    '<p class="country-subtitle">Proyectos de ley, noticias y sesiones de Perú y Ecuador en un solo '
    'lugar. Escribe una idea, no palabras exactas: "datos biométricos" encuentra también '
    '"reconocimiento facial" o "identidad digital".</p>',
    unsafe_allow_html=True,
)


from cerebro.ui import conexion

conn = conexion()
if conn is None:
    st.warning("El cerebro todavía no está publicado (lo arma el workflow «Cerebro» en GitHub).")
    st.stop()

total = conn.execute("SELECT count(*) FROM items").fetchone()[0]
cols = st.columns([4, 1.2, 1.4, 1])
consulta = cols[0].text_input("Qué buscas", placeholder="Ej.: regulación de plaguicidas, biometría, "
                              "impuesto a servicios digitales...", label_visibility="collapsed")
pais = cols[1].selectbox("País", ["Ambos", "PE", "EC"], label_visibility="collapsed")
tipo = cols[2].selectbox("Tipo", ["Todo", "Proyectos de ley", "Noticias", "Sesiones"],
                         label_visibility="collapsed")
k = cols[3].selectbox("Resultados", [15, 30, 60], label_visibility="collapsed")
st.caption(f"{total:,} documentos en el cerebro.")

if consulta.strip():
    from cerebro.embeddings import buscar

    tipo_db = {"Proyectos de ley": "pl", "Noticias": "noticia", "Sesiones": "sesion"}.get(tipo)
    with st.spinner("Buscando..."):
        try:
            resultados = buscar(consulta, k=k, tipo=tipo_db,
                                pais=None if pais == "Ambos" else pais, conn=conn)
        except Exception as e:
            st.error(f"No se pudo buscar: {e}")
            resultados = []
    etiqueta = {"pl": "Proyecto de ley", "noticia": "Noticia", "sesion": "Sesión"}
    for r in resultados:
        extra = json.loads(r["extra"] or "{}")
        detalle = " · ".join(str(v) for v in (extra.get("fuente"), extra.get("organo"),
                                              extra.get("tema"), extra.get("estado")) if v)
        st.markdown(
            f'<div class="item-card"><div class="item-fuente">{etiqueta.get(r["tipo"], r["tipo"])} · '
            f'{r["pais"]} · {r["fecha"] or "sin fecha"}</div>'
            f'<div class="item-titulo"><a href="{html.escape(r["url"] or "#")}" target="_blank">'
            f'{html.escape(r["titulo"] or "(sin título)")}</a></div>'
            f'<div class="item-meta">{html.escape(detalle)} · afinidad {r["similitud"]:.2f}</div></div>',
            unsafe_allow_html=True,
        )

# ---------- Preguntar al cerebro (grafo de conocimiento, LightRAG) ----------
# La busqueda de arriba devuelve DOCUMENTOS parecidos; esto responde una
# PREGUNTA cruzando hechos entre documentos (PLs, sesiones, noticias y el
# perfil de cada cliente) - ver cerebro/grafo.py.
# El grafo usa modelos livianos con cupo gratuito propio (ver cerebro/grafo.py).
# Mientras se va armando (unos dias), responde solo con lo ya procesado.
GRAFO_ACTIVO = True
if not GRAFO_ACTIVO:
    st.stop()

st.markdown("---")
st.markdown("### Preguntarle al cerebro")
st.caption("Responde cruzando proyectos de ley, sesiones, noticias y lo que le importa a cada cliente. "
           "Tarda unos segundos y cita en qué se basa.")


@st.cache_data(ttl=3600, show_spinner=False)
def _respuesta(pregunta: str) -> str:
    from cerebro.grafo import descargar_si_falta, preguntar
    if not descargar_si_falta():
        return "El grafo todavía no está publicado (lo arma el workflow «Cerebro» en GitHub)."
    return preguntar(pregunta)


with st.form("preguntar_cerebro"):
    pregunta = st.text_area(
        "Pregunta", label_visibility="collapsed", height=90,
        placeholder="Ej.: ¿Qué se discutió esta semana sobre agroquímicos que le importe a Bayer? · "
                    "¿Qué proyectos sobre datos personales hay en Ecuador y en qué comisión están?")
    enviar = st.form_submit_button("Preguntar")
if enviar and pregunta.strip():
    with st.spinner("Pensando..."):
        try:
            st.markdown(_respuesta(pregunta.strip()))
        except Exception as e:
            st.error(f"No se pudo responder: {e}")
