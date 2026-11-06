"""Chat interactivo para redactar alertas de WhatsApp por cliente.

Es lo que Nicolas usa a diario en vez de un borrador ya armado: una
conversacion con Gemini (tier gratuito, nunca la API de Claude para esto)
que ya tiene cargado el contexto completo del cliente (notas.md e
historial_alertas.md enteros, no un top-k) mas las reglas y ejemplos reales.
"""
from __future__ import annotations

import re
from functools import lru_cache
from html import unescape
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
    correcciones = _leer(CLIENTES_DIR / "_plantillas" / "correcciones_alertas.md")

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

=== CORRECCIONES DE NICOLAS (correcciones_alertas.md - reglas que salieron de corregir borradores reales;
pesan MAS que todo lo anterior: si chocan con un ejemplo, gana la correccion) ===
{correcciones}
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


def nueva_conversacion(slug: str, historial: list[dict] | None = None, modelo: str = MODEL):
    """Conversacion de Gemini con el contexto de `slug` como
    system_instruction. Levanta RuntimeError si falta GEMINI_API_KEY.

    Devuelve (client, chat): el caller retiene `client` porque chats.create()
    no guarda una referencia fuerte y el GC cerraria su sesion HTTP."""
    from google.genai import types

    client = llm.cliente()
    system = construir_system_prompt(slug)
    historial = list(historial or [])
    if modelo.startswith("gemma"):  # Gemma no acepta system_instruction: va como primer turno
        historial[:0] = [{"role": "user", "parts": [{"text": system}]},
                         {"role": "model", "parts": [{"text": "Entendido."}]}]
        system = None
    chat = client.chats.create(
        model=modelo,
        config=types.GenerateContentConfig(system_instruction=system),
        history=historial or None,
    )
    return client, chat


URL = re.compile(r"https?://[^\s<>\"')\]]+")
MAX_ENLACE = 40_000  # caracteres por enlace
MAX_ENLACES = 5


def _texto_html(html: str) -> str:
    html = re.sub(r"(?is)<(script|style|nav|header|footer|aside|form|noscript)\b.*?</\1>", " ", html)
    m = re.search(r"(?is)<article\b.*?</article>", html)
    cuerpo = m.group(0) if m else html
    bloques = re.findall(r"(?is)<(?:p|h[1-4]|li|td)\b[^>]*>(.*?)</(?:p|h[1-4]|li|td)>", cuerpo)
    lineas = [re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", b))).strip() for b in bloques]
    texto = "\n".join(l for l in lineas if len(l) > 2)
    if len(texto) >= 500:
        return texto
    # Sitios que arman la nota con <div> (Andina): lineas largas de toda la pagina.
    crudo = unescape(re.sub(r"<[^>]+>", "", re.sub(r"(?i)<(?:/div|br|/p|/li|/h\d)[^>]*>", "\n", html)))
    return "\n".join(l for l in (re.sub(r"\s+", " ", x).strip() for x in crudo.split("\n")) if len(l) >= 80)


@lru_cache(maxsize=64)
def leer_enlace(url: str) -> str:
    """Texto de una pagina o PDF; si no se puede, el motivo entre corchetes
    (asi Gemini sabe que no lo leyo en vez de inventar). Cacheado: el chat
    reenvia la historia completa en cada turno."""
    if "news.google.com" in url:
        return "[enlace de Google News: no abre la nota directo, pegar el enlace del medio]"
    try:
        from core.http import session
        r = session(reintentos=1).get(url, timeout=30)
        if r.status_code >= 400:
            return f"[no se pudo abrir: HTTP {r.status_code}]"
        if r.content[:4] == b"%PDF":
            import pymupdf
            doc = pymupdf.open(stream=r.content, filetype="pdf")
            paginas = [p.get_text().strip() for p in doc]
            vacias = sum(1 for p in paginas if len(p) < 30)
            texto = "\n".join(p for p in paginas if p)
            nota = f"[PDF de {len(paginas)} paginas" + (f", {vacias} escaneadas sin texto]" if vacias else "]")
            texto = f"{nota}\n{texto}"
        else:
            texto = _texto_html(r.text)
        if len(texto) < 200:
            return "[la pagina no tiene texto legible (puede cargarse con JavaScript o pedir inicio de sesion)]"
        if len(texto) > MAX_ENLACE:
            texto = texto[:MAX_ENLACE] + f"\n[recortado: se leyeron los primeros {MAX_ENLACE} caracteres]"
        return texto
    except Exception as e:
        return f"[no se pudo abrir: {type(e).__name__}]"


def con_enlaces(texto: str) -> str:
    """El mensaje mas el contenido de los enlaces que trae."""
    urls = list(dict.fromkeys(u.rstrip(".,;") for u in URL.findall(texto or "")))[:MAX_ENLACES]
    if not urls:
        return texto
    bloques = [f"--- {u}\n{leer_enlace(u)}" for u in urls]
    return (f"{texto}\n\n=== CONTENIDO DE LOS ENLACES (lo bajo el sistema; usalo como fuente y "
            f"si un enlace dice que no se pudo leer, decimelo en vez de suponer lo que trae) ===\n"
            + "\n\n".join(bloques))


REVISION = """Antes de darla por buena, revisa la alerta contra el texto de la fuente y contesta para ti estas preguntas:
1. Que cambia frente a la version anterior de la norma o la situacion previa. Pon lado a lado lo de antes y lo de
   ahora: un plazo que se acorta, un requisito que se agrega o algo que ya existia no se presenta como novedad.
2. Desde cuando rige. OBLIGATORIO si es una norma: la alerta debe decir la fecha de publicacion y desde cuando rige
   segun el texto; si el texto no lo fija, decirlo asi.
3. Por que le importa a este cliente segun su perfil. OBLIGATORIO: explica en palabras simples que regula y a que
   actividad concreta del cliente toca (sin nombrar al cliente). Si de verdad no hay relacion, dilo en tu respuesta
   en vez de rellenar.
4. Que vineta no le aporta nada al cliente (contexto de relleno, motivos internos de la entidad). Quitala.
5. Que fecha, cifra o dato no sale de la fuente. Quitalo.
Despues entrega SOLO la alerta corregida, lista para WhatsApp, sin explicar los cambios."""


def responder(slug: str, historia: list, prompt: str) -> tuple[str, str]:
    """Un turno del chat: (texto, modelo que lo escribio). Lee los enlaces de todos
    los mensajes del usuario y reintenta/cambia de modelo si Gemini esta saturado
    (503) o sin cupo."""
    previo = [{"role": "user" if rol == "user" else "model",
               "parts": [{"text": con_enlaces(t) if rol == "user" else t}]} for rol, t, *_ in historia]
    mensaje = con_enlaces(prompt)

    def turno(modelo):
        _client, chat = nueva_conversacion(slug, historial=previo, modelo=modelo)  # _client vivo hasta el send
        return (chat.send_message(mensaje).text or "").strip(), modelo
    return llm.con_respaldo(turno, MODEL)
