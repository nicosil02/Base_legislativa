"""Chat interactivo para redactar alertas de WhatsApp por cliente.

Es lo que Nicolas usa a diario en vez de un borrador ya armado: una
conversacion con Gemini (tier gratuito, nunca la API de Claude para esto)
que ya tiene cargado el contexto completo del cliente (notas.md e
historial_alertas.md enteros, no un top-k) mas las reglas y ejemplos reales.
"""
from __future__ import annotations

from pathlib import Path

from core import llm

REPO_ROOT = Path(__file__).resolve().parent.parent
CLIENTES_DIR = REPO_ROOT / "clientes"
MODEL = llm.FLASH


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
    """Conversacion de Gemini con el contexto de `slug` como
    system_instruction. Levanta RuntimeError si falta GEMINI_API_KEY.

    Devuelve (client, chat): el caller retiene `client` porque chats.create()
    no guarda una referencia fuerte y el GC cerraria su sesion HTTP."""
    from google.genai import types

    client = llm.cliente()
    chat = client.chats.create(
        model=MODEL,
        config=types.GenerateContentConfig(system_instruction=construir_system_prompt(slug)),
        history=historial or None,
    )
    return client, chat
