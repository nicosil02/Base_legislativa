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
    from alerts.historial import leer as leer_historial

    notas = _leer(CLIENTES_DIR / slug / "notas.md")
    historial = leer_historial(slug)
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


_ETIQUETA = {"pl": "PL", "noticia": "Noticia", "sesion": "Sesión", "alerta": "Alerta enviada"}


def contexto_relacionado(consulta: str, pais: str | None = None, k: int = 8,
                         excluir_url: str | None = None) -> str:
    """Lo que el cerebro tiene parecido a `consulta` (PL, sesiones, noticias
    y alertas anteriores), una linea por item, sin links (Gemini no los abre).
    "" si el cerebro no esta."""
    try:
        from cerebro.embeddings import buscar, descargar_si_falta
        if not descargar_si_falta():
            return ""
        res = buscar(consulta[:600], k=k + 1, pais=pais)
    except Exception as e:
        print(f"[chat] cerebro no disponible: {e}")
        return ""
    lineas = [f"- [{_ETIQUETA.get(r['tipo'], r['tipo'])} · {r.get('fecha') or 's/f'}] {r.get('titulo')}"
              for r in res if not excluir_url or r.get("url") != excluir_url]
    return "\n".join(lineas[:k])


def mensaje_inicial(semilla: dict, contexto: str) -> str:
    """Primer mensaje del chat cuando se llega desde "Armar alerta"."""
    items = semilla["items"]
    bloques = []
    for i, it in enumerate(items):
        cab = "Principal" if i == 0 and len(items) > 1 else ("Otra fuente" if i else "Material")
        bloques.append("\n".join(x for x in (
            f"[{cab}] {it['titulo']}",
            " · ".join(p for p in (it.get("fuente"), it.get("fecha"), it.get("pais")) if p),
            it.get("resumen") or "", it.get("url") or "") if x))
    partes = [f"Armá la alerta para {semilla['cliente']} a partir de esto:", *bloques]
    if semilla.get("por_que"):
        partes.append(f"Por qué le interesaría (filtro automático): {semilla['por_que']}")
    if contexto:
        partes.append("Contexto relacionado que encontré en el cerebro (PL, sesiones, noticias y "
                      "alertas anteriores). Usalo solo si de verdad se conecta:\n" + contexto)
    partes.append("Si falta información para escribirla bien, preguntame antes de inventar.")
    return "\n\n".join(partes)


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
