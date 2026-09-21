"""Chat interactivo para redactar alertas de WhatsApp por cliente.

Nicolas 2026-09-21: "la parte de generacion de alertas no me sirve mucho...
normalmente voy a un agente de IA que conozco mi proyecto y ahi hago las
alertas" - el flujo automatico de fondo (alerts/relevancia.py + la rutina
que redacta pendientes) sigue existiendo para lo que el marca desde
Noticias PE/EC, pero lo que el realmente usa a diario es conversar con una
IA que ya tiene el contexto completo cargado, no un texto ya armado
esperando revision.

Gemini (tier gratuito, mismo criterio de costo que congreso_live.qa_chat.py
y alerts/relevancia.py - nunca la API de Claude para esto) con el contexto
REAL del cliente como system_instruction de toda la conversacion: notas.md
entero, historial_alertas.md entero (a diferencia de relevancia.py, que solo
usa el top-k vectorizado - aca es una conversacion libre, Gemini puede
navegar todo), y las reglas + ejemplos gold-standard reales del equipo.
Es lo mismo que Nicolas tendria que pegar el a mano en su herramienta
externa, ya cargado de una.
"""
from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CLIENTES_DIR = REPO_ROOT / "clientes"
MODEL = "gemini-3.6-flash"


def _leer(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def construir_system_prompt(slug: str) -> str:
    """Contexto completo del cliente, igual al que tendria Nicolas leyendo
    todo a mano - no una version resumida/vectorizada."""
    notas = _leer(CLIENTES_DIR / slug / "notas.md")
    historial = _leer(CLIENTES_DIR / slug / "historial_alertas.md")
    formato = _leer(CLIENTES_DIR / "_plantillas" / "whatsapp_alerta.md")
    ejemplos = _leer(CLIENTES_DIR / "_plantillas" / "ejemplos_alertas.md")

    return f"""Sos el asistente de redaccion de alertas de Vali Intelligence / Vali Consultores,
ayudando a Nicolas a escribir la alerta de WhatsApp final para el cliente "{slug}".

Nicolas te va a pegar una noticia, un proyecto de ley, un link, o simplemente te va a contar de que se
trata - tu trabajo es ayudarlo a redactar la alerta siguiendo EXACTAMENTE el formato y las reglas de abajo,
conversando con el hasta que quede lista. Podes preguntar si falta contexto, sugerir angulos que le
interesarian a este cliente puntual segun su perfil real (no genericos), y iterar las veces que haga falta.
Cuando te pida la version final, entregala sola, lista para copiar y pegar a WhatsApp - sin explicaciones
alrededor ni encabezados tipo "Aca esta la alerta:".

=== PERFIL DEL CLIENTE (notas.md completo) ===
{notas or "(sin notas.md para este cliente)"}

=== HISTORIAL DE ALERTAS YA MANDADAS A ESTE CLIENTE (para no repetir, y para conectar continuidad real -
"regla de oro" del formato: si la noticia nueva se conecta con algo ya reportado, tejerlo en el bullet de
analisis, no como dato de relleno separado) ===
{historial or "(sin historial de alertas todavia para este cliente)"}

=== FORMATO Y REGLAS EXACTAS (whatsapp_alerta.md) ===
{formato}

=== EJEMPLOS REALES gold-standard (ejemplos_alertas.md - incluye comparacion de un borrador de IA vs. la
redaccion real del equipo, estudiala) ===
{ejemplos}
"""


def nueva_conversacion(slug: str, historial: list[dict] | None = None):
    """Crea una conversacion de Gemini con el contexto de `slug` ya cargado
    como system_instruction. Levanta RuntimeError si falta GEMINI_API_KEY
    (mismo patron que congreso_live.qa_chat.py).

    Bug real 2026-09-21 (probado en vivo contra la app deployada):
    "Cannot send a request, as the client has been closed" - Streamlit
    re-ejecuta el script ENTERO en cada interaccion, y el objeto
    genai.Client (y su sesion HTTP interna) de una corrida anterior no
    sobrevive confiablemente a la siguiente, aunque el objeto Chat este
    guardado en st.session_state. Fix: nunca reusar un Client/Chat viejo -
    se crea uno nuevo en cada mensaje, pasandole `historial` (turnos
    previos, formato [{"role": "user"|"model", "parts": [{"text": ...}]}])
    para que la conversacion siga de donde quedo."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("Falta GEMINI_API_KEY en el entorno")

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    return client.chats.create(
        model=MODEL,
        config=types.GenerateContentConfig(system_instruction=construir_system_prompt(slug)),
        history=historial or None,
    )


# ============================================================
# self-check (Ponytail: 1 chequeo ejecutable de la logica no trivial)
# ============================================================

def _demo():
    """Sin red: construir_system_prompt() debe incluir el contenido real
    de los 4 archivos fuente, y nueva_conversacion() debe exigir
    GEMINI_API_KEY antes de intentar nada."""
    prompt = construir_system_prompt("bayer")
    assert "PERFIL DEL CLIENTE" in prompt
    assert "FORMATO Y REGLAS EXACTAS" in prompt
    assert "EJEMPLOS REALES" in prompt
    # bayer tiene notas.md real con contenido - si esto viniera vacio,
    # el prompt le mentiria a Gemini diciendo "sin notas.md" en produccion.
    assert "(sin notas.md" not in prompt, "bayer deberia tener notas.md real"

    # Cliente inexistente no debe romper, solo avisar que no hay datos.
    prompt_vacio = construir_system_prompt("cliente_que_no_existe")
    assert "(sin notas.md para este cliente)" in prompt_vacio

    saved = os.environ.pop("GEMINI_API_KEY", None)
    try:
        try:
            nueva_conversacion("bayer")
            raise AssertionError("deberia haber fallado sin API key")
        except RuntimeError as e:
            assert "GEMINI_API_KEY" in str(e), e
    finally:
        if saved is not None:
            os.environ["GEMINI_API_KEY"] = saved
    print("OK chat: construir_system_prompt() arma el contexto real, nueva_conversacion() exige API key")


def _test_reconstruye_con_historial():
    """Bug real 2026-09-21, probado en vivo contra la app deployada:
    reusar un objeto Chat guardado entre reruns de Streamlit tiraba
    "Cannot send a request, as the client has been closed". El fix
    reconstruye la conversacion de cero en cada mensaje pasando el
    historial ya charlado - esto verifica que esa reconstruccion carga
    bien los turnos previos (sin red, chats.create() no llama a la API)."""
    os.environ["GEMINI_API_KEY"] = "fake-key-solo-para-construir-el-objeto"
    try:
        historial = [
            {"role": "user", "parts": [{"text": "hola"}]},
            {"role": "model", "parts": [{"text": "hola, en que te ayudo"}]},
        ]
        chat = nueva_conversacion("bayer", historial=historial)
        assert len(chat.get_history()) == 2
    finally:
        os.environ.pop("GEMINI_API_KEY", None)
    print("OK chat: nueva_conversacion() reconstruye la conversacion con el historial previo")


if __name__ == "__main__":
    _demo()
    _test_reconstruye_con_historial()
