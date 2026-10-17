"""Radar Legislativo - Alertas.

Se llega desde "✍️ Armar alerta" (Noticias, TV, PL, Agenda) o se abre directo.
El chat de Gemini ya tiene el bluebook del cliente, todas las alertas que se
le mandaron, el formato y los ejemplos reales (alerts/chat.py). Al llegar con
material, primero busca en el cerebro lo relacionado (PL, sesiones, noticias y
alertas anteriores) y lo suma al primer mensaje. "Guardar como enviada" agrega
la alerta final al historial del cliente (commit en GitHub) y el cerebro la
indexa en la proxima corrida. Nada se manda a ningun cliente desde aca.
"""
from __future__ import annotations

import html
import re

import streamlit as st

from alerts import historial
from alerts.armar import SEMILLA
from alerts.chat import contexto_relacionado, mensaje_inicial, nueva_conversacion
from ui_kit import inject_theme

_PAISES = {"PE": "Perú", "EC": "Ecuador"}


def _vista_previa_whatsapp(texto: str) -> str:
    """*negrita* de WhatsApp como <b> real, para ver como queda antes de mandarla."""
    return re.sub(r"\*([^*\n]+?)\*", r"<b>\1</b>", html.escape(texto))


def _enviar(prompt: str) -> str:
    historial_gemini = [{"role": "user" if rol == "user" else "model", "parts": [{"text": t}]}
                        for rol, t in st.session_state["chat_historial_ui"]]
    try:
        # Se retiene _client hasta despues del send: el Chat no lo referencia.
        _client, chat = nueva_conversacion(sel_cliente, historial=historial_gemini)
        respuesta = (chat.send_message(prompt).text or "").strip()
    except Exception as e:
        respuesta = f"⚠️ No se pudo conectar con Gemini: {e}"
    st.session_state["chat_historial_ui"] += [("user", prompt), ("assistant", respuesta)]
    return respuesta


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
.item-card { border: 1px solid var(--line-soft); border-radius: 10px; padding: 12px 16px; margin: 6px 0; }
.item-fuente { font-size:11px; font-weight:700; color:var(--ink-mute);
  text-transform:uppercase; letter-spacing:0.06em; }
.item-titulo { font-size:15px; font-weight:700; color:var(--ink); line-height:1.35; margin-top:4px; }
.item-titulo a { color:var(--ink); text-decoration:none; }
.item-titulo a:hover { color:var(--accent-red); text-decoration:underline; }
footer { visibility:hidden; }
</style>""",
    unsafe_allow_html=True,
)
st.markdown('<div class="country-eyebrow">Radar Legislativo · Alertas</div>', unsafe_allow_html=True)
st.markdown('<h1 class="country-title">Redactar <span class="accent">con contexto</span></h1>',
            unsafe_allow_html=True)
st.markdown(
    '<p class="country-subtitle">Llega acá con "✍️ Armar alerta" desde Noticias, TV o los PL, o '
    'pega lo que quieras en el chat. Ya tiene el bluebook del cliente, sus alertas anteriores y lo '
    'que el cerebro sabe del tema. No envía nada a ningún cliente.</p>',
    unsafe_allow_html=True,
)

clientes = historial.clientes()
if not clientes:
    st.error("No encuentro clientes con `notas.md` en `clientes/`.")
    st.stop()

semilla = st.session_state.pop(SEMILLA, None)
if semilla and semilla.get("cliente") in clientes:
    st.session_state["alerta_cliente"] = semilla["cliente"]
    st.session_state["chat_cliente"] = semilla["cliente"]
    st.session_state["chat_historial_ui"] = []
    st.session_state["chat_material"] = semilla
    st.session_state["chat_por_enviar"] = True

sel_cliente = st.selectbox("Cliente", clientes, key="alerta_cliente")
if st.session_state.get("chat_cliente") != sel_cliente:
    st.session_state["chat_cliente"] = sel_cliente
    st.session_state["chat_historial_ui"] = []
    st.session_state.pop("chat_material", None)

material = st.session_state.get("chat_material")
if material:
    for it in material["items"]:
        meta = " · ".join(p for p in (it.get("fuente"), it.get("fecha"), it.get("pais")) if p)
        st.markdown(
            f'<div class="item-card"><div class="item-fuente">{html.escape(meta)}</div>'
            f'<div class="item-titulo"><a href="{html.escape(it.get("url") or "#")}" target="_blank">'
            f'{html.escape(it["titulo"])}</a></div></div>', unsafe_allow_html=True)
    if material.get("por_que"):
        st.caption(f"Por qué le interesaría: {material['por_que']}")

st.markdown("##### 💬 Chat de redacción")
for rol, texto in st.session_state.get("chat_historial_ui", []):
    with st.chat_message(rol):
        st.markdown(texto)

if st.session_state.pop("chat_por_enviar", False) and material:
    primero = material["items"][0]
    with st.spinner("Buscando contexto en el cerebro..."):
        consulta = f"{primero['titulo']}. {primero.get('resumen') or ''}"
        contexto = contexto_relacionado(consulta, pais=primero.get("pais"), excluir_url=primero.get("url"))
    prompt = mensaje_inicial(material, contexto)
    with st.chat_message("user"):
        st.markdown(prompt)
    with st.chat_message("assistant"), st.spinner("Redactando..."):
        st.markdown(_enviar(prompt))

if prompt := st.chat_input(f"Escribí acá para {sel_cliente}..."):
    with st.chat_message("user"):
        st.markdown(prompt)
    with st.chat_message("assistant"), st.spinner("Pensando..."):
        st.markdown(_enviar(prompt))

respuestas = [t for rol, t in st.session_state.get("chat_historial_ui", []) if rol == "assistant"
              and not t.startswith("⚠️")]
if respuestas:
    n = len(st.session_state["chat_historial_ui"])
    primero = (material or {}).get("items", [{}])[0]
    with st.expander("✅ Guardar como enviada", expanded=True):
        texto = st.text_area("Texto final (editalo si hace falta)", value=respuestas[-1], height=240,
                             key=f"final_{sel_cliente}_{n}")
        c = st.columns([3, 1, 1])
        titulo = c[0].text_input("Título para el historial", value=primero.get("titulo", ""),
                                 key=f"final_tit_{n}")
        paises = list(_PAISES.values()) + ["Regional"]
        pais = c[1].selectbox("País", paises, key=f"final_pais_{n}",
                              index=paises.index(_PAISES.get(primero.get("pais"), "Perú")))
        linea = c[2].text_input("Línea (opcional)", placeholder="Farma, Crop...", key=f"final_lin_{n}")
        url = st.text_input("Fuente", value=primero.get("url") or "", key=f"final_url_{n}")
        st.caption("Vista previa (así se ve la negrita en WhatsApp):")
        st.markdown(f'<div style="border:1px solid var(--line-soft);border-radius:8px;padding:10px 14px;'
                    f'font-size:14px;white-space:pre-wrap;">{_vista_previa_whatsapp(texto)}</div>',
                    unsafe_allow_html=True)
        st.code(texto, language=None)
        if st.button(f"Guardar en el historial de {sel_cliente}", type="primary",
                     disabled=not (texto.strip() and titulo.strip()), key=f"final_btn_{n}"):
            try:
                historial.agregar(sel_cliente, historial.entrada(titulo, texto, pais, url or None,
                                                                 linea or None),
                                  autor=st.user.get("email"))
                st.success(f"Guardada en el historial de {sel_cliente}. Desde ahora el chat la tiene en "
                           "cuenta, y el cerebro la suma en la próxima corrida (menos de una hora).")
            except Exception as e:
                st.error(f"No se pudo guardar: {e}")

if st.session_state.get("chat_historial_ui") and st.button("🔄 Nueva conversación"):
    st.session_state["chat_historial_ui"] = []
    st.session_state.pop("chat_material", None)
    st.rerun()
