"""Radar Legislativo - Alertas - Borradores por cliente.

Cola de trabajo por cliente: Nicolas marca noticias desde las paginas de
Noticias PE/EC ("Marcar" -> estado='pendiente'), el agente programado
(cron cada hora) las redacta y las deja en estado='borrador'. Esta pagina
solo muestra ese estado - pendientes y ya redactados - y deja editar/
guardar el texto final a mano.

OJO (decision de Nicolas, 2026-09-12): esta pagina SI persiste datos al
repo publico (a diferencia de clientes/, que esta gitignoreado) - confirmado
que por ahora no es un problema. No es un mecanismo de envio: nada se manda
a ningun cliente desde aca, es solo para redactar/guardar el borrador.

NOTA (2026-09-13): esta pagina tenia ademas una seccion de "candidatos"
rankeados automaticamente por similitud de texto (alerts/relevancia.py) -
se saco porque Nicolas confirmo que no quiere que el sistema decida solo
que es relevante (TF-IDF matchea vocabulario, no tema real - ej. "MEF"
tageado para Google por el angulo de IVA digital hacia que CUALQUIER
noticia de MEF apareciera como candidata para Google, sin distinguir cual
es la relevante de verdad). El modulo relevancia.py sigue en el repo
(rankear/contexto_historial), pero ya no se muestra en la UI.
"""
from __future__ import annotations

from pathlib import Path

import streamlit as st

from alerts.borradores_store import guardar_borrador, list_borradores

CLIENTES_DIR = Path(__file__).resolve().parent.parent / "clientes"


def load_clientes() -> list[str]:
    if not CLIENTES_DIR.is_dir():
        return []
    return sorted(
        p.name for p in CLIENTES_DIR.iterdir()
        if p.is_dir() and not p.name.startswith("_")
    )


# ====================== CSS (misma estetica que Noticias) ======================
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
.block-container { padding-top:2rem; padding-bottom:4rem; max-width:1100px; }
.country-eyebrow {
  font-size:11px; font-weight:800; letter-spacing:0.25em;
  text-transform:uppercase; color:var(--accent); margin-bottom:12px;
}
.country-title {
  font-size:clamp(2.2rem,4.5vw,3.2rem); font-weight:900;
  letter-spacing:-0.03em; line-height:0.95; color:var(--ink); margin:0 0 10px 0;
}
.country-title .accent { color:var(--accent); }
.country-subtitle {
  font-size:1.05rem; color:var(--ink-soft); line-height:1.6; margin-bottom:28px;
}
.item-card {
  border: 1px solid var(--line-soft); border-radius: 10px;
  padding: 14px 16px; margin: 8px 0 4px 0;
}
.item-fuente {
  font-size:11px; font-weight:700; color:var(--ink-mute);
  text-transform:uppercase; letter-spacing:0.06em;
}
.item-titulo { font-size:15px; font-weight:700; color:var(--ink); line-height:1.35; margin: 4px 0; }
.item-titulo a { color:var(--ink); text-decoration:none; }
.item-titulo a:hover { color:var(--accent-red); text-decoration:underline; }
.item-meta { font-size:11px; color:var(--ink-mute); }
footer { visibility:hidden; }
</style>""",
    unsafe_allow_html=True,
)

st.markdown('<div class="country-eyebrow">Radar Legislativo · Alertas</div>', unsafe_allow_html=True)
st.markdown(
    '<h1 class="country-title">Borradores <span class="accent">por cliente</span></h1>',
    unsafe_allow_html=True,
)
st.markdown(
    '<p class="country-subtitle">Lo que marcaste desde Noticias PE/EC — el agente programado lo '
    'redacta cada hora. Editá y guardá el texto final acá — esto NO envía nada a ningún cliente.</p>',
    unsafe_allow_html=True,
)

clientes = load_clientes()
if not clientes:
    st.error("No encuentro carpetas de clientes en `clientes/`.")
    st.stop()

sel_cliente = st.selectbox("Cliente", clientes)

todos_los_guardados = list_borradores(sel_cliente)
pendientes = [b for b in todos_los_guardados if b.get("estado") == "pendiente"]
ya_redactados = [b for b in todos_los_guardados if b.get("estado") != "pendiente"]

st.markdown("##### ⏳ Pendientes de redactar (marcados desde Noticias)")
if not pendientes:
    st.caption(
        "Ninguno. Marcá noticias con \"📌 Marcar\" en las páginas de Noticias PE/EC — "
        "el agente programado las redacta en la próxima hora."
    )
else:
    for p in pendientes:
        st.markdown(
            f'<div class="item-card"><div class="item-fuente">{p.get("pais")} · '
            f'marcado {p.get("created_at","")}</div><div class="item-titulo">'
            f'<a href="{p.get("item_url") or "#"}" target="_blank">{p.get("item_titulo")}</a>'
            f'</div></div>',
            unsafe_allow_html=True,
        )

st.markdown("---")
st.markdown("##### ✅ Ya redactados para este cliente")
if not ya_redactados:
    st.caption("Ninguno todavía.")
else:
    for b in ya_redactados:
        with st.expander(f"{b.get('item_titulo', '(sin título)')[:100]} · {b.get('updated_at', '')}"):
            texto = st.text_area(
                "Borrador", value=b.get("texto", ""), height=180,
                key=f"txt_{b['item_id']}", label_visibility="collapsed",
            )
            if st.button("Guardar cambios", key=f"save_{b['item_id']}"):
                try:
                    guardar_borrador(
                        cliente=sel_cliente, item_id=b["item_id"], item_tipo=b.get("item_tipo", ""),
                        pais=b.get("pais", ""), item_titulo=b.get("item_titulo", ""),
                        item_url=b.get("item_url"), texto=texto,
                    )
                    st.success("Guardado.")
                except Exception as e:
                    st.error(f"No se pudo guardar: {e}")
            if b.get("item_url"):
                st.markdown(f"[Ver fuente]({b['item_url']})")

st.markdown('<div class="footer-rule"></div>', unsafe_allow_html=True)
st.markdown(
    '<div style="font-size:12px;color:var(--ink-soft);margin-top:40px;">Radar Legislativo · '
    'Vali Consultores</div>',
    unsafe_allow_html=True,
)
