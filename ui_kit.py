"""Polish compartido de UI para toda la app Vali - complementa (no
reemplaza) el bloque de CSS propio de cada pagina (paleta, tipografia,
sidebar). Evita repetir estas reglas en las 9 paginas.

Aplica principios de la skill de diseño de Emil Kowalski (emil-design-eng):
botones con feedback de "press" (scale al :active), curvas de easing
propias en vez de las de CSS por defecto, y transiciones cortas (<300ms)
en vez de "transition: all".
"""
from __future__ import annotations

import streamlit as st

FONT_LINKS = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">
"""

THEME_CSS = """
:root {
  --ink:        #0A294D;
  --ink-soft:   #435D74;
  --ink-mute:   #5D7286;  /* era #869FB2 (~2.6:1 sobre blanco, falla WCAG
                             AA); critique 2026-09-22. Nuevo valor ~5:1. */
  --line:       #CFD9E0;
  --line-soft:  #E3E9ED;
  --accent:     #0A294D;
  --accent-red: #BF1A1A;
  --gold:       #9C7A2E;  /* sello/registro oficial - solo para Normativa,
                             nunca como color de marca general */
  --bg:         #FBFAF7;  /* antes #FFFFFF puro - blanco calido tipo papel
                             de gaceta, no blanco "SaaS generico". Pase de
                             diseno 2026-09-22 (frontend-design skill). */
  --bg-soft:    #F4F6F8;
}
html, body, [class*="css"], .stApp {
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
  color: var(--ink);
  background-color: var(--bg);
}
/* === Entrada escalonada de las tarjetas de KPI ===
   Hallazgo real 2026-09-22 (Nicolas: "no se ve nada mejorado, quiero
   animaciones, se siente lenta y fea"): las tarjetas de KPI (lo primero
   que se ve en cada pagina) no tenian ningun movimiento, a diferencia
   de las country-card del Inicio que si tienen entrada escalonada.
   Mismo patron aca, aplicado centralizado para las 6 paginas. */
@keyframes kpiEnter {
  from { opacity: 0; transform: translateY(10px); }
  to   { opacity: 1; transform: translateY(0); }
}
div[data-testid="stMetric"] {
  animation: kpiEnter 380ms cubic-bezier(.16,1,.3,1) both;
}
[data-testid="stColumn"]:nth-child(1) div[data-testid="stMetric"] { animation-delay: 0ms; }
[data-testid="stColumn"]:nth-child(2) div[data-testid="stMetric"] { animation-delay: 40ms; }
[data-testid="stColumn"]:nth-child(3) div[data-testid="stMetric"] { animation-delay: 80ms; }
[data-testid="stColumn"]:nth-child(4) div[data-testid="stMetric"] { animation-delay: 120ms; }
[data-testid="stColumn"]:nth-child(5) div[data-testid="stMetric"] { animation-delay: 160ms; }
[data-testid="stColumn"]:nth-child(6) div[data-testid="stMetric"] { animation-delay: 200ms; }
[data-testid="stColumn"]:nth-child(7) div[data-testid="stMetric"] { animation-delay: 240ms; }
[data-testid="stColumn"]:nth-child(8) div[data-testid="stMetric"] { animation-delay: 280ms; }
/* === st.tabs con la marca (Agenda PE: Agenda/Por comisión/Mesas
   tecnicas/Transcripciones/Seguimiento) - por defecto salen en gris
   Streamlit generico, sin relacion con la paleta navy/rojo del resto. */
[data-testid="stTabs"] [data-baseweb="tab-list"] {
  gap: 4px; border-bottom: 1px solid var(--line);
}
[data-testid="stTabs"] [data-baseweb="tab"] {
  height: auto; padding: 10px 16px; background: transparent;
  font-size: 13px; font-weight: 700; color: var(--ink-mute);
  transition: color 140ms ease;
}
[data-testid="stTabs"] [data-baseweb="tab"]:hover {
  color: var(--ink);
}
[data-testid="stTabs"] [aria-selected="true"] {
  color: var(--accent) !important;
}
[data-testid="stTabs"] [data-baseweb="tab-highlight"] {
  background-color: var(--accent);
  height: 2px;
}
/* === st.expander con la marca (Noticias: "Mas filtros"/"Seguimiento de
   PL"; Alertas: lista "Ya redactados") - por defecto sale con borde gris
   Streamlit generico y texto negro plano, sin relacion con la marca.
   DOM real (verificado en vivo): [data-testid="stExpander"] > details >
   summary > ... [data-testid="stIconMaterial"] (flecha) + stMarkdownContainer p. */
[data-testid="stExpander"] {
  border: 1px solid var(--line) !important;
  border-radius: 10px !important;
  background: var(--bg) !important;
}
[data-testid="stExpander"] summary p {
  font-weight: 700 !important;
  color: var(--ink-soft) !important;
  transition: color 140ms ease;
}
[data-testid="stExpander"] [data-testid="stIconMaterial"] {
  color: var(--ink-mute) !important;
  transition: color 140ms ease;
}
[data-testid="stExpander"] summary:hover p,
[data-testid="stExpander"] summary:hover [data-testid="stIconMaterial"] {
  color: var(--accent) !important;
}
/* === st.chat_message (Alertas: chat de redacción) - los avatares salen
   en rojo/naranja default de Streamlit (#FF4B4B / #FFA421), sin relacion
   con la paleta navy/rojo Vali, y la burbuja del usuario en gris frio
   (#F0F2F6) en vez del gris calido (--bg-soft) del resto de la app -
   verificado en vivo que el input de chat de abajo SI hereda bien el
   tema (bg-soft + borde navy vía primaryColor de config.toml), solo los
   mensajes quedaban afuera. */
[data-testid="stChatMessageAvatarUser"],
[data-testid="stChatMessageAvatarAssistant"] {
  background-color: var(--ink) !important;
}
[data-testid="stChatMessageAvatarAssistant"] {
  background-color: var(--ink-mute) !important;
}
[data-testid="stChatMessage"] {
  background-color: var(--bg-soft) !important;
  border-radius: 12px !important;
}
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarAssistant"]) {
  background-color: transparent !important;
}
/* === st.container(border=True) (Peru: sugerencias de reclasificacion;
   Ecuador: noticias de tramite de la Asamblea) - por defecto sale con
   borde gris Streamlit generico, sin relacion con las demas listas
   (noticia-card, item-card, session-card) que ya tienen borde propio +
   hover. Mismo tratamiento aca para que no se sientan una lista de debug
   suelta dentro del expander. */
[data-testid="stVerticalBlockBorderWrapper"] {
  border-color: var(--line-soft) !important;
  border-radius: 10px !important;
  transition: border-color .15s ease, box-shadow .15s ease;
}
[data-testid="stVerticalBlockBorderWrapper"]:hover {
  border-color: var(--accent) !important;
  box-shadow: 0 2px 8px rgba(10,41,77,0.08);
}
/* === .detail-card (Ecuador: panel "Documentos del proyecto" al
   seleccionar un PL en la tabla) - definida pero MUERTA en
   pages/1_Peru.py (Perú no tiene panel de detalle por PL). Ecuador tenía
   su propio panel con hex crudos inline (#FFFFFF, #CFD9E0, #0A294D,
   #435D74) que no usaba ningún token del tema - quedaba blanco puro en
   vez del papel cálido (--bg) del resto de la app, y sin la entrada
   animada / hover que ya tienen session-card, noticia-card, item-card.
   Centralizada acá con el mismo tratamiento. */
@keyframes detailCardEnter {
  from { opacity: 0; transform: translateY(8px); }
  to   { opacity: 1; transform: translateY(0); }
}
.detail-card {
  background: var(--bg);
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 28px 32px;
  margin-top: 28px;
  animation: detailCardEnter 320ms cubic-bezier(.16,1,.3,1) both;
  transition: border-color .15s ease, box-shadow .15s ease;
}
.detail-card:hover {
  border-color: var(--accent);
  box-shadow: 0 2px 8px rgba(10,41,77,0.08);
}
.detail-eyebrow {
  font-size: 11px; font-weight: 800; letter-spacing: 0.22em;
  text-transform: uppercase; color: var(--accent); margin-bottom: 10px;
}
.detail-title {
  font-size: 1.6rem; font-weight: 800; letter-spacing: -0.015em;
  line-height: 1.25; color: var(--ink); margin-bottom: 8px;
}
.detail-meta-label {
  font-size: 10px; font-weight: 700; letter-spacing: 0.18em;
  text-transform: uppercase; color: var(--ink-mute); margin-bottom: 4px;
}
.detail-meta-value { font-size: 14px; font-weight: 600; color: var(--ink); }
.detail-section-title {
  font-size: 11px; font-weight: 800; letter-spacing: 0.22em;
  text-transform: uppercase; color: var(--ink-soft); margin: 24px 0 8px 0;
}
/* === Sidebar navy + texto blanco === */
section[data-testid="stSidebar"] {
  background-color: var(--ink) !important;
  border-right: 0 !important;
}
section[data-testid="stSidebar"] *,
section[data-testid="stSidebar"] a,
section[data-testid="stSidebar"] p,
section[data-testid="stSidebar"] h1, section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3, section[data-testid="stSidebar"] label,
section[data-testid="stSidebar"] span {
  color: #FFFFFF !important;
  font-family: 'Inter', sans-serif !important;
}
section[data-testid="stSidebar"] [data-testid="stSidebarNav"] a:hover {
  background-color: rgba(255,255,255,0.06) !important;
}
section[data-testid="stSidebar"] [data-testid="stSidebarNav"] [aria-current="page"] {
  background-color: rgba(255,255,255,0.10) !important;
}
"""


def inject_theme() -> None:
    """Paleta Vali + tema base + texto del sidebar - antes copy-pasteado
    (con pequeñas variaciones de formato/orden) en las 9 paginas; una
    de esas variaciones tenia una regla vieja que causo el bug real del
    icono duplicado del sidebar (2026-09-22). Una sola fuente ahora.

    La fuente Inter se cargaba con @import DENTRO del <style> - eso
    bloquea la aplicacion de TODO ese bloque (colores de marca, sidebar
    navy, todo) hasta que Google Fonts responde, en cada carga de
    pagina (Streamlit navega con hard-reload del browser entre paginas,
    asi que esto se repetia constantemente). Hallazgo real 2026-09-22
    (Nicolas: "se siente lenta"). <link rel="preconnect"> + <link
    rel="stylesheet"> es el metodo que la propia Google Fonts recomienda
    para produccion en vez de @import - el browser lo descarga en
    paralelo con el resto de la pagina en lugar de bloquearla."""
    st.markdown(FONT_LINKS, unsafe_allow_html=True)
    st.markdown(f"<style>{THEME_CSS}</style>", unsafe_allow_html=True)


BUTTON_POLISH_CSS = """
/* === Polish de botones/checkboxes del area principal (ui_kit.py) ===
   Streamlit los pinta en gris chrome por defecto, sin relacion con la
   marca. Escapado a [data-testid="stMain"] para no pisar el estilo ya
   existente de los botones del sidebar. */
[data-testid="stMain"] [data-testid="stPopoverButton"],
[data-testid="stMain"] button[data-testid="stBaseButton-secondary"] {
  border: 1px solid var(--line) !important;
  border-radius: 8px !important;
  color: var(--ink-soft) !important;
  background: var(--bg) !important;
  font-weight: 700 !important;
  font-size: 12.5px !important;
  transition: transform 140ms cubic-bezier(0.23,1,0.32,1),
              border-color 140ms ease, color 140ms ease !important;
}
[data-testid="stMain"] [data-testid="stPopoverButton"]:hover,
[data-testid="stMain"] button[data-testid="stBaseButton-secondary"]:hover {
  border-color: var(--accent) !important;
  color: var(--ink) !important;
}
[data-testid="stMain"] [data-testid="stPopoverButton"]:active,
[data-testid="stMain"] button[data-testid="stBaseButton-secondary"]:active {
  transform: scale(0.97);
}
/* "primary" es el unico kind que usamos para acciones destructivas/
   principales (ej. Descartar) - rojo Vali en version ligera (outline,
   no bloque solido) para no romper el minimalismo del resto. */
[data-testid="stMain"] button[data-testid="stBaseButton-primary"] {
  background: var(--bg) !important;
  border: 1px solid var(--accent-red) !important;
  color: var(--accent-red) !important;
  border-radius: 8px !important;
  font-weight: 700 !important;
  font-size: 12.5px !important;
  transition: transform 140ms cubic-bezier(0.23,1,0.32,1),
              background-color 140ms ease !important;
}
[data-testid="stMain"] button[data-testid="stBaseButton-primary"]:hover {
  background: #FFF3F3 !important;
}
[data-testid="stMain"] button[data-testid="stBaseButton-primary"]:active {
  transform: scale(0.97);
}
[data-testid="stMain"] [data-testid="stCheckbox"] label p {
  font-size: 12.5px !important;
  color: var(--ink-soft) !important;
  font-weight: 600 !important;
}
/* Inputs de texto/select: borde mas suave, foco con el navy de marca en
   vez del rojo default de Streamlit. */
[data-testid="stMain"] input, [data-testid="stMain"] textarea {
  border-radius: 8px !important;
}
[data-testid="stMain"] div[data-baseweb="select"] > div {
  border-radius: 8px !important;
  transition: border-color 140ms ease !important;
}
"""


def inject_button_polish() -> None:
    st.markdown(f"<style>{BUTTON_POLISH_CSS}</style>", unsafe_allow_html=True)


def render_evolucion_mensual(df, height: int = 340) -> None:
    """Grafico de lineas por mes (Perú/Ecuador: "Evolución mensual") con
    Altair en vez de st.line_chart. Bug real (Nicolas 2026-09-22, "el
    grafico es pesimo, las fechas salen volteadas"): con solo 2-3 puntos
    st.line_chart trata el eje X como categorico y Vega-Lite rota las
    etiquetas ISO completas ("2026-08-01") a vertical para que no se
    superpongan - con Altair se fija el eje como temporal, formato mes
    corto + año, y las etiquetas quedan horizontales (labelAngle=0).
    `df` es el DataFrame que devuelven evolucion_mensual() en Perú/Ecuador:
    index = mes (string 'YYYY-MM-DD'), columnas = series a graficar."""
    import altair as alt
    import pandas as pd

    d = df.reset_index()
    mes_col = d.columns[0]
    d[mes_col] = pd.to_datetime(d[mes_col])
    d_melt = d.melt(mes_col, var_name="Serie", value_name="Cantidad")
    chart = (
        alt.Chart(d_melt)
        .mark_line(point={"size": 60}, strokeWidth=2.5)
        .encode(
            x=alt.X(f"{mes_col}:T", title=None,
                    # "%m/%Y" en vez de nombre de mes: los nombres cortos de
                    # Vega-Lite salen en ingles (Aug/Sep) sin configurar un
                    # locale aparte - inconsistente con el resto de la app
                    # en español. Numerico evita el problema.
                    axis=alt.Axis(format="%m/%Y", labelAngle=0, tickCount="month")),
            y=alt.Y("Cantidad:Q", title=None, axis=alt.Axis(grid=True)),
            color=alt.Color("Serie:N", title=None,
                             scale=alt.Scale(range=["#0A294D", "#9C7A2E"]),
                             legend=alt.Legend(orient="top", title=None)),
            tooltip=[alt.Tooltip(f"{mes_col}:T", format="%m/%Y", title="Mes"),
                     "Serie:N", "Cantidad:Q"],
        )
        .properties(height=height)
    )
    st.altair_chart(chart, use_container_width=True)
