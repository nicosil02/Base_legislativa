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

UPDATE 2026-09-21 - Nicolas: "la parte de generacion de alertas no me sirve
mucho... normalmente voy a un agente de IA que conozco mi proyecto y ahi
hago las alertas". El flujo automatico de arriba sigue igual, pero se
agrego abajo un chat interactivo (alerts/chat.py) con el mismo contexto
completo del cliente ya cargado (notas.md, historial, formato, ejemplos) -
reemplaza el ir a una herramienta externa a pegar todo a mano.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import streamlit as st

from alerts.borradores_store import guardar_borrador, list_borradores
from alerts.chat import nueva_conversacion

CLIENTES_DIR = Path(__file__).resolve().parent.parent / "clientes"

_LIMA = timezone(timedelta(hours=-5))
_MESES_CORTO = ["ene", "feb", "mar", "abr", "may", "jun",
                "jul", "ago", "sep", "oct", "nov", "dic"]


def _fecha_legible(iso: str | None) -> str:
    """'2026-09-13T15:48:00Z' -> '13 sep, 10:48' (hora Lima) - crudo en ISO
    no es legible para Nicolas, confirmado en la auditoria de UX."""
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(_LIMA)
    except ValueError:
        return iso
    return f"{dt.day} {_MESES_CORTO[dt.month - 1]}, {dt.strftime('%H:%M')}"


def _vista_previa_whatsapp(texto: str) -> str:
    """Convierte *negrita* (sintaxis de WhatsApp) a <b>negrita</b> real (HTML,
    no markdown - esto se inyecta dentro de un <div> con unsafe_allow_html,
    donde ** no se interpreta) para que Nicolas vea como se va a ver ANTES
    de mandarlo - antes solo se veian los asteriscos literales. Escapa HTML
    primero para no romper el render con < o & del texto real."""
    import html as _html
    texto_escapado = _html.escape(texto)
    return re.sub(r"\*([^*\n]+?)\*", r"<b>\1</b>", texto_escapado)


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
  font-family: Georgia, 'Times New Roman', serif;
  font-size:clamp(2.2rem,4.5vw,3.2rem); font-weight:400;
  letter-spacing:-0.01em; line-height:0.98; color:var(--ink); margin:0 0 10px 0;
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
    'redacta cada hora. Edita y guarda el texto final aquí — esto NO envía nada a ningún cliente.</p>',
    unsafe_allow_html=True,
)

clientes = load_clientes()
if not clientes:
    st.error("No encuentro carpetas de clientes en `clientes/`.")
    st.stop()

_yo = st.user.get("email")
_cols_top = st.columns([2, 2])
sel_cliente = _cols_top[0].selectbox("Cliente", clientes)
# Sin login activo (auth no configurado todavia) _yo es None - en ese caso
# "Solo lo mío" no tiene con qué filtrar, así que se oculta y se ve todo,
# igual que antes de que existiera el login.
solo_mio = _cols_top[1].toggle("Solo lo mío", value=bool(_yo), disabled=not _yo) if _yo else False

todos_los_guardados = list_borradores(sel_cliente)
if solo_mio:
    todos_los_guardados = [b for b in todos_los_guardados if b.get("creado_por") == _yo]
pendientes = [b for b in todos_los_guardados if b.get("estado") == "pendiente"]
ya_redactados = [b for b in todos_los_guardados if b.get("estado") != "pendiente"]

st.markdown("##### ⏳ Pendientes de redactar (marcados desde Noticias)")
if not pendientes:
    st.caption(
        "Ninguno. Marca noticias con \"📌 Marcar\" en las páginas de Noticias PE/EC — "
        "el agente programado las redacta en la próxima hora."
    )
else:
    for p in pendientes:
        st.markdown(
            f'<div class="item-card"><div class="item-fuente">{p.get("pais")} · '
            f'marcado {_fecha_legible(p.get("created_at"))}</div><div class="item-titulo">'
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
        titulo_corto = b.get('item_titulo', '(sin título)')[:100]
        fecha = _fecha_legible(b.get('updated_at'))
        with st.expander(f"{titulo_corto} · {fecha}" if fecha else titulo_corto):
            texto = st.text_area(
                "Borrador", value=b.get("texto", ""), height=180,
                key=f"txt_{b['cliente']}_{b['item_id']}", label_visibility="collapsed",
            )
            if st.button("Guardar cambios", key=f"save_{b['cliente']}_{b['item_id']}"):
                try:
                    guardar_borrador(
                        cliente=sel_cliente, item_id=b["item_id"], item_tipo=b.get("item_tipo", ""),
                        pais=b.get("pais", ""), item_titulo=b.get("item_titulo", ""),
                        item_url=b.get("item_url"), texto=texto,
                    )
                    st.success("Guardado.")
                except Exception as e:
                    st.error(f"No se pudo guardar: {e}")
            st.caption("Vista previa (así se ve la negrita en WhatsApp):")
            st.markdown(
                f'<div style="border:1px solid var(--line-soft);border-radius:8px;'
                f'padding:10px 14px;font-size:14px;white-space:pre-wrap;">'
                f'{_vista_previa_whatsapp(texto)}</div>',
                unsafe_allow_html=True,
            )
            st.caption("Copiar (icono arriba a la derecha del bloque):")
            st.code(texto, language=None)
            if b.get("item_url"):
                st.markdown(f"[Ver fuente]({b['item_url']})")

st.markdown("---")
st.markdown("##### 💬 Chat de redacción")
st.caption(
    f"Pegá una noticia, un link, o contame de qué se trata — conversamos hasta que la alerta para "
    f"{sel_cliente} quede lista. Ya tengo cargado su perfil (notas.md), el historial de alertas y el "
    "formato real que usa el equipo — no manda nada, solo redacta."
)

# Reiniciar la conversacion si cambia el cliente seleccionado (el contexto
# cargado es especifico de cada uno).
if st.session_state.get("chat_cliente") != sel_cliente:
    st.session_state["chat_cliente"] = sel_cliente
    st.session_state["chat_historial_ui"] = []

for _rol, _texto in st.session_state.get("chat_historial_ui", []):
    with st.chat_message(_rol):
        st.markdown(_texto)

if _prompt := st.chat_input(f"Escribí acá para {sel_cliente}..."):
    with st.chat_message("user"):
        st.markdown(_prompt)
    with st.chat_message("assistant"):
        with st.spinner("Pensando..."):
            try:
                # Bug real 2026-09-21 (probado en vivo): guardar el objeto
                # Chat en session_state y reusarlo en el siguiente mensaje
                # tiraba "Cannot send a request, as the client has been
                # closed" - Streamlit re-ejecuta el script entero en cada
                # interaccion y el Client de Gemini no sobrevive de una
                # corrida a la otra. Se reconstruye la conversacion de
                # cero en cada mensaje, pasandole lo ya charlado.
                _historial_gemini = [
                    {"role": "user" if rol == "user" else "model", "parts": [{"text": texto}]}
                    for rol, texto in st.session_state["chat_historial_ui"]
                ]
                _chat = nueva_conversacion(sel_cliente, historial=_historial_gemini)
                _resp = _chat.send_message(_prompt)
                _respuesta = (_resp.text or "").strip()
            except Exception as e:
                _respuesta = f"⚠️ No se pudo conectar con Gemini: {e}"
        st.markdown(_respuesta)
    st.session_state["chat_historial_ui"].append(("user", _prompt))
    st.session_state["chat_historial_ui"].append(("assistant", _respuesta))

if st.session_state.get("chat_historial_ui"):
    if st.button("🔄 Nueva conversación"):
        st.session_state["chat_historial_ui"] = []
        st.rerun()

st.markdown('<div class="footer-rule"></div>', unsafe_allow_html=True)
st.markdown(
    '<div style="font-size:12px;color:var(--ink-soft);margin-top:40px;">Radar Legislativo · '
    'Vali Consultores</div>',
    unsafe_allow_html=True,
)
