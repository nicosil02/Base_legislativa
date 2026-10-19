"""Radar Legislativo - ¿Qué pasó hoy? que le importe a los clientes.

El mismo resumen que sale por Telegram a las 18:00 (alerts/que_paso_hoy.py),
pero a pedido: muestra el ultimo guardado y con un boton lo vuelve a armar
con lo que la app tiene ahora (noticias filtradas por cliente, normas, PLs,
sesiones y TV de las ultimas 24 h).
"""
from __future__ import annotations

import re

import streamlit as st

from ui_kit import inject_theme

inject_theme()
st.markdown(
    """<style>
.block-container { padding-top:2rem; padding-bottom:4rem; max-width:900px; }
.country-eyebrow { font-size:11px; font-weight:800; letter-spacing:0.25em;
  text-transform:uppercase; color:var(--accent); margin-bottom:12px; }
.country-title { font-family: Georgia, 'Times New Roman', serif;
  font-size:clamp(2.2rem,4.5vw,3.2rem); font-weight:400; letter-spacing:-0.01em;
  line-height:0.98; color:var(--ink); margin:0 0 10px 0; }
.country-subtitle { font-size:1.05rem; color:var(--ink-soft); line-height:1.6; margin-bottom:28px; }
footer { visibility:hidden; }
</style>""",
    unsafe_allow_html=True,
)
st.markdown('<div class="country-eyebrow">Vali Intelligence</div>'
            '<h1 class="country-title">¿Qué pasó hoy?</h1>'
            '<p class="country-subtitle">Lo de las últimas 24 horas que le importa a cada cliente: '
            'noticias, normas, proyectos de ley, sesiones y TV, con el porqué y el link.</p>',
            unsafe_allow_html=True)

from alerts import que_paso_hoy as q
from cerebro.ui import conexion


def _md(texto: str) -> str:
    # Telegram usa *x* para negrita; en Streamlit eso es cursiva.
    return re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"**\1**", texto)


conn = conexion()
if conn is None:
    st.warning("El cerebro todavía no está publicado (lo arma el workflow «Cerebro» en GitHub).")
    st.stop()

if st.button("Armar ahora con lo último", type="primary"):
    with st.spinner("Juntando lo de las últimas 24 h y escribiendo el resumen (puede tardar 1 minuto)..."):
        try:
            m = q.material(conn)
            st.session_state["qph"] = (q._lima_ahora().strftime("%d/%m %H:%M"), q.escribir(m).strip(),
                                       {k: len(v) for k, v in m.items()})
        except Exception as e:
            st.error(f"No se pudo armar el resumen: {e}")

if "qph" in st.session_state:
    hora, texto, cuenta = st.session_state["qph"]
    st.caption(f"Armado a las {hora} (Lima) con: " + ", ".join(f"{v} {k}" for k, v in cuenta.items()))
    st.markdown(_md(texto))
else:
    try:
        fila = conn.execute("SELECT fecha, texto FROM resumen_dia ORDER BY fecha DESC LIMIT 1").fetchone()
    except Exception:
        fila = None
    if fila:
        st.caption(f"Último resumen enviado por Telegram ({fila[0]}). Usa el botón para armarlo de nuevo con lo último.")
        st.markdown(_md(fila[1]))
    else:
        st.info("Todavía no hay resumen guardado. Usa el botón para armar el de hoy.")
