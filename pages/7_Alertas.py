"""Radar Legislativo - Alertas - Borradores por cliente.

Cola de trabajo por cliente: toma los candidatos ya rankeados por
alerts.relevancia (noticias tageadas para ese cliente + PLs relevantes por
tema/similitud NL contra su perfil), deja redactar un borrador ahi mismo
y lo guarda (via alerts.borradores_store, GitHub Contents API - mismo
backend que auth/).

OJO (decision de Nicolas, 2026-09-12): esta pagina SI persiste datos al
repo publico (a diferencia de clientes/, que esta gitignoreado) - confirmado
que por ahora no es un problema. No es un mecanismo de envio: nada se manda
a ningun cliente desde aca, es solo para redactar/guardar el borrador.
"""
from __future__ import annotations

from pathlib import Path

import streamlit as st

from alerts import relevancia
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
    '<p class="country-subtitle">Candidatos rankeados por relevancia para un cliente (fuentes '
    'tageadas + similitud de texto contra su perfil). Redactá el borrador acá y guardalo — '
    'esto NO envía nada a ningún cliente, es solo para vos.</p>',
    unsafe_allow_html=True,
)

clientes = load_clientes()
if not clientes:
    st.error("No encuentro carpetas de clientes en `clientes/`.")
    st.stop()

col1, col2, col3 = st.columns([1.3, 1, 1])
sel_cliente = col1.selectbox("Cliente", clientes)
sel_pais = col2.selectbox("País", ["PE + EC", "PE", "EC"])
sel_top = col3.slider("Cuántos candidatos", min_value=3, max_value=15, value=8)

pais_arg = None if sel_pais == "PE + EC" else sel_pais


def _item_id(item: dict) -> str:
    return f"{item['tipo']}_{item['pais']}_{item.get('id')}"


def _skeleton(item: dict) -> str:
    bandera = "🇵🇪" if item["pais"] == "PE" else "🇪🇨" if item["pais"] == "EC" else ""
    prefijo = f"{bandera} " if sel_cliente in ("google", "incode") and bandera else ""
    pais_label = "Perú" if item["pais"] == "PE" else "Ecuador" if item["pais"] == "EC" else item["pais"]
    return (
        f"{prefijo}🎯 {pais_label}: {item.get('titulo', '')[:80]}\n\n"
        f"¿Qué pasó? \n\n"
        f"Puntos a tener en cuenta\n"
        f"* \n"
        f"* \n"
        f"* \n\n"
        f"{item.get('url') or ''}"
    )


with st.spinner("Rankeando candidatos..."):
    try:
        candidatos = relevancia.rankear(sel_cliente, pais_arg, sel_top)
    except Exception as e:
        st.error(f"No pude rankear candidatos: {e}")
        candidatos = []

if not candidatos:
    st.info("Sin candidatos en la ventana actual para este cliente/país.")
else:
    st.markdown(f"##### {len(candidatos)} candidato(s) para **{sel_cliente}**")
    guardados = {b["item_id"]: b for b in list_borradores(sel_cliente)}

    for item in candidatos:
        iid = _item_id(item)
        hist = relevancia.contexto_historial(sel_cliente, item)
        st.markdown(
            f'<div class="item-card">'
            f'<div class="item-fuente">{item.get("fuente") or item["tipo"].upper()} · {item["pais"]} '
            f'· score {item.get("score")}</div>'
            f'<div class="item-titulo"><a href="{item.get("url") or "#"}" target="_blank">'
            f'{item.get("titulo") or ""}</a></div>'
            f'<div class="item-meta">{(item.get("resumen") or "")[:200]}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
        if hist:
            st.caption(
                "Posible antecedente en el historial: "
                + "; ".join(f"{h['titulo']} ({h['score']})" for h in hist)
            )

        default_texto = guardados.get(iid, {}).get("texto") or _skeleton(item)
        texto = st.text_area(
            "Borrador", value=default_texto, height=180, key=f"txt_{iid}",
            label_visibility="collapsed",
        )
        bcol1, bcol2 = st.columns([1, 5])
        if bcol1.button("Guardar borrador", key=f"save_{iid}"):
            try:
                guardar_borrador(
                    cliente=sel_cliente, item_id=iid, item_tipo=item["tipo"],
                    pais=item["pais"], item_titulo=item.get("titulo") or "",
                    item_url=item.get("url"), texto=texto,
                )
                st.success("Guardado.")
            except Exception as e:
                st.error(f"No se pudo guardar: {e}")
        if iid in guardados:
            bcol2.caption(f"Guardado por última vez: {guardados[iid].get('updated_at', '')}")

st.markdown("---")
st.markdown("##### Borradores ya guardados para este cliente")
guardados_lista = list_borradores(sel_cliente)
if not guardados_lista:
    st.caption("Ninguno todavía.")
else:
    for b in guardados_lista:
        with st.expander(f"{b.get('item_titulo', '(sin título)')[:100]} · {b.get('updated_at', '')}"):
            st.text(b.get("texto", ""))
            if b.get("item_url"):
                st.markdown(f"[Ver fuente]({b['item_url']})")

st.markdown('<div class="footer-rule"></div>', unsafe_allow_html=True)
st.markdown(
    '<div style="font-size:12px;color:var(--ink-soft);margin-top:40px;">Radar Legislativo · '
    'Vali Consultores</div>',
    unsafe_allow_html=True,
)
