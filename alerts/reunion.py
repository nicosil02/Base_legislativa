"""Resumen para preparar una reunion sobre un PL (boton "Preparar reunion"
de las paginas de PLs Peru/Ecuador).

Adaptado del skill meeting-briefing de anthropics/knowledge-work-plugins
(legal) al trabajo de asuntos publicos: en vez de contratos y calendario,
el PL, quien lo impulsa, que paso falta y que le cambia al cliente.

Gemini gratis (GEMINI_API_KEY), como alerts/chat.py. Primero el modelo del
chat; si su cuota del dia se acabo (20/dia, compartida) cae a flash-lite,
que tiene cuota propia.
"""
from __future__ import annotations

import os

from alerts.chat import CLIENTES_DIR, MODEL, _leer

MODELO_RESPALDO = "gemini-3.5-flash-lite"

CON_QUIEN = {
    "cliente": "con el cliente, para explicarle el PL y qué debería hacer",
    "despacho": "con el despacho del autor o con la comisión, para plantear la posición del cliente",
}


def armar_prompt(pl: dict, pais: str, cliente: str | None, con_quien: str) -> str:
    perfil = _leer(CLIENTES_DIR / cliente / "notas.md") if cliente else ""
    historial = _leer(CLIENTES_DIR / cliente / "historial_alertas.md") if cliente else ""
    datos = "\n".join(f"- {k}: {v}" for k, v in pl.items() if v not in (None, "", "—"))
    return f"""Prepara un resumen de una página para una reunión {CON_QUIEN[con_quien]}.
País: {"Perú" if pais == "PE" else "Ecuador"}. Cliente: {cliente or "ninguno en particular"}.

=== DATOS DEL PROYECTO DE LEY (los únicos hechos comprobados que tienes) ===
{datos}

=== PERFIL DEL CLIENTE (notas.md) ===
{perfil or "(sin cliente elegido)"}

=== ALERTAS YA ENVIADAS A ESTE CLIENTE (para conectar antecedentes reales) ===
{historial[-6000:] or "(sin historial)"}

Usa exactamente estas secciones, en markdown, cortas y concretas.

### De qué se trata
Dos o tres frases en lenguaje simple.

### Dónde está y qué falta
Quién decide ahora, qué paso sigue para que sea obligatorio (dictamen, Pleno, segunda votación,
reglamento, publicación) y qué tan probable es que avance, con la razón.

### Quién lo impulsa
Autor, bancada y comisión según los datos. Qué interés se le puede suponer, dejando claro que es una
suposición si no hay una declaración pública en los datos.

### Qué le cambia al cliente
La cadena completa, el PL trae un requisito, el requisito afecta un área puntual del cliente y eso tiene
una consecuencia comercial. Si no hay cliente, el impacto para el sector.

### Puntos para decir
Tres puntos.

### Preguntas para hacer
Tres preguntas, cada una con por qué importa.

### Lo que no sabemos todavía
Lo que falta verificar antes de la reunión. No inventes datos que no estén arriba (fechas, votos,
declaraciones). Si algo no está en los datos, va en esta sección.

Escribe como lo haría una persona del equipo, en español neutro. No uses dos puntos ni guiones largos
como conectores de ideas. No escribas "Para {cliente or 'el cliente'}," dentro del texto."""


def preparar_reunion(pl: dict, pais: str, cliente: str | None, con_quien: str = "cliente") -> str:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("Falta GEMINI_API_KEY en el entorno")
    from google import genai

    client = genai.Client(api_key=api_key)
    prompt = armar_prompt(pl, pais, cliente, con_quien)
    try:
        return client.models.generate_content(model=MODEL, contents=prompt).text
    except Exception as e:
        # 429 por cuota diaria del modelo del chat -> el de respaldo
        if "429" not in str(e) and "RESOURCE_EXHAUSTED" not in str(e):
            raise
        return client.models.generate_content(model=MODELO_RESPALDO, contents=prompt).text


def render_panel(pl: dict, pais: str, clientes: list[str], key: str) -> None:
    """Panel de Streamlit, igual en Peru y Ecuador. `pl` = datos de la fila."""
    import streamlit as st

    st.markdown("##### 🗂️ Preparar reunión")
    st.caption(f"Sobre el PL elegido arriba: **{pl.get('PL')}** · {str(pl.get('Título'))[:80]}")
    c = st.columns([2, 3, 1.2])
    cli = c[0].selectbox("Cliente", ["Ninguno"] + clientes, key=f"reu_cli_{key}")
    quien = c[1].radio("Reunión con", list(CON_QUIEN), horizontal=True, key=f"reu_con_{key}",
                       format_func=lambda k: {"cliente": "El cliente",
                                              "despacho": "Autor o comisión"}[k])
    estado = f"reu_txt_{key}"
    if c[2].button("Preparar", key=f"reu_btn_{key}", use_container_width=True):
        with st.spinner("Armando el resumen (puede tardar un minuto)..."):
            try:
                st.session_state[estado] = (pl.get("PL"), preparar_reunion(
                    pl, pais, None if cli == "Ninguno" else cli, quien))
            except Exception as e:
                st.error(f"No se pudo preparar el resumen: {e}")
    guardado = st.session_state.get(estado)
    if guardado and guardado[0] == pl.get("PL"):
        with st.container(border=True):
            st.markdown(guardado[1])
        st.download_button("Descargar (.md)", guardado[1], file_name=f"reunion_{pl.get('PL')}.md",
                           key=f"reu_dl_{key}")


if __name__ == "__main__":
    p = armar_prompt({"PL": "00011-2026-2031-CD", "Título": "Ley de semillas", "Estado": "En comisión"},
                     "PE", "bayer", "despacho")
    assert "Ley de semillas" in p and "despacho del autor" in p and "(sin cliente" not in p
    assert "Lo que no sabemos todavía" in p
    print("OK reunion: prompt con datos del PL, perfil del cliente y secciones")
