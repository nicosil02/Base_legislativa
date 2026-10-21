"""Resumen en vivo de una sesion, cada ~10 min, a Telegram SOLO si lo nuevo
le toca a un cliente (perfil = clientes/<slug>/notas.md). Lo que no
interesa no se manda: la web guarda la transcripcion entera igual.

Mismo criterio que las mesas de trabajo: opiniones sueltas no valen, solo
hechos (votacion, aprobacion, compromiso, anuncio, PL o norma nombrados,
autoridad que fija posicion sobre un tema del cliente).

Lo ya avisado en la sesion se pasa en cada tramo para no repetirlo (el
20/10 la Comision de Salud mando 12 avisos del mismo predictamen). Al
terminar la sesion, si hubo avisos, sale una alerta final con el formato de
WhatsApp (alerta_final)."""
from __future__ import annotations

import json

from core import llm

CADA_SEG = 600
MIN_CHARS = 800  # menos texto nuevo que esto: se espera al siguiente tramo

SYSTEM = ("Eres analista de asuntos publicos. Lees un tramo de la transcripcion automatica "
          "(con errores de dictado) de una sesion parlamentaria y decides si hay algo que un "
          "cliente deba saber YA, segun su perfil. Solo hechos: votaciones con resultado, "
          "aprobaciones, compromisos con plazo, anuncios oficiales, proyectos de ley o normas "
          "nombrados, una autoridad que fija posicion sobre un tema del cliente. "
          "NO avisar: opiniones sin resultado, saludos, tramite, lectura de agenda, debate general, "
          "temas que solo tocan al cliente por la region o de rebote (penales, obras, pesca, clima "
          "si el perfil no lo pide). Nunca inventes la conexion con el cliente ni lo nombres en los "
          "puntos. Un resultado de votacion solo se afirma si se oye el conteo o el anuncio del "
          "presidente; si no esta claro, di que se debate. Lo que ya se aviso NO se repite ni se "
          "reformula; solo vale si cambio (por ejemplo, lo que se debatia ahora se voto). "
          "Ante la duda, no. Español simple, sin dos puntos como conector.")

SCHEMA = {
    "type": "object",
    "properties": {
        "hay_algo": {"type": "boolean"},
        "clientes": {"type": "array", "items": {"type": "string"}},
        "puntos": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["hay_algo", "clientes", "puntos"],
}


def _perfiles(pais: str) -> str:
    from clientes import config
    out = []
    for slug in config.slugs(pais):
        notas = config.CARPETA / slug / "notas.md"
        if notas.exists():
            out.append(f"=== {slug} ===\n{notas.read_text(encoding='utf-8')}")
    return "\n\n".join(out)


def _quienes(clientes) -> str:
    """Nombres de los clientes reales; Gemini a veces inventa ('Inconde', 'Informa')."""
    from clientes import config
    validos = config.slugs()
    return ", ".join(c.strip().lower().capitalize() for c in clientes or []
                     if c.strip().lower() in validos)


def _pais(tipo: str) -> str:
    return "EC" if tipo.endswith("(EC)") else "PE"


def resumir(tipo: str, titulo: str, texto_nuevo: str, avisado: list[str] | None = None,
            previo: str = "", generar=llm.generar) -> str | None:
    """Mensaje de Telegram listo para mandar, o None si no hay nada de interes.
    `avisado`: puntos ya mandados en esta sesion; se le agregan los nuevos.
    `previo`: texto justo antes del tramo, para no leer una votacion a medias."""
    avisado = [] if avisado is None else avisado
    perfiles = _perfiles(_pais(tipo))
    if not perfiles:
        return None
    ya = "\n".join(f"- {p}" for p in avisado) or "(nada todavia)"
    prompt = (f"Perfiles de los clientes:\n{perfiles}\n\nSesion: {tipo} — {titulo}\n\n"
              f"Ya avisado en esta sesion (no repetir):\n{ya}\n\n"
              f"Contexto anterior (ya leido):\n{previo[-3000:]}\n\n"
              f"Tramo nuevo de la transcripcion:\n{texto_nuevo[-12000:]}\n\n"
              "Si hay algo nuevo, 'puntos' son 1 a 3 frases cortas con el hecho; "
              "'clientes' son los slugs afectados.")
    r = json.loads(generar(prompt, system=SYSTEM, modelo=llm.LITE, schema=SCHEMA) or "{}")
    puntos = [p.strip() for p in r.get("puntos") or [] if p.strip()]
    if not r.get("hay_algo") or not puntos:
        return None
    avisado.extend(puntos)
    quienes = _quienes(r.get("clientes"))
    return (f"📝 *{tipo}* en vivo" + (f" ({quienes})" if quienes else "") + f"\n{titulo}\n\n"
            + "\n".join(f"• {p}" for p in puntos))


SYSTEM_FINAL = ("Eres analista de asuntos publicos y redactas alertas de WhatsApp para clientes, "
                "siguiendo al pie de la letra la plantilla que te dan. Te pasan la transcripcion "
                "automatica completa de una sesion parlamentaria (con errores de dictado) y lo que "
                "se aviso en vivo. Escribe UNA alerta con lo que de verdad le sirve al cliente, con "
                "el resultado final de cada tema (lo que se aprobo, se voto, se devolvio a comision "
                "o quedo pendiente). Si al final nada vale una alerta, hay_algo=false. "
                "Negritas con *asteriscos* de WhatsApp. Sin dos puntos ni guiones como conector, "
                "sin nombrar al cliente dentro del texto.")

SCHEMA_FINAL = {
    "type": "object",
    "properties": {
        "hay_algo": {"type": "boolean"},
        "clientes": {"type": "array", "items": {"type": "string"}},
        "alerta": {"type": "string"},
    },
    "required": ["hay_algo", "clientes", "alerta"],
}


def alerta_final(tipo: str, titulo: str, texto: str, avisado: list[str],
                 generar=llm.generar) -> str | None:
    """Alerta de cierre en formato WhatsApp, o None. Solo si en vivo hubo algo:
    sin avisos no se gasta FLASH (20 pedidos/dia compartidos con los chats)."""
    if not avisado:
        return None
    perfiles = _perfiles(_pais(tipo))
    if not perfiles:
        return None
    from clientes import config
    plantilla = config.CARPETA / "_plantillas" / "whatsapp_alerta.md"
    plantilla = plantilla.read_text(encoding="utf-8") if plantilla.exists() else ""
    ya = "\n".join(f"- {p}" for p in avisado)
    prompt = (f"Plantilla de alerta:\n{plantilla}\n\nPerfiles de los clientes:\n{perfiles}\n\n"
              f"Sesion: {tipo} — {titulo}\n\nAvisado en vivo (puede tener errores; manda la "
              f"transcripcion):\n{ya}\n\nTranscripcion completa:\n{texto[-200000:]}")
    r = json.loads(generar(prompt, system=SYSTEM_FINAL, modelo=llm.FLASH, schema=SCHEMA_FINAL) or "{}")
    alerta = (r.get("alerta") or "").strip()
    if not r.get("hay_algo") or not alerta:
        return None
    quienes = _quienes(r.get("clientes"))
    return f"✅ Fin de sesión · {tipo}" + (f" (para {quienes})" if quienes else "") + f"\n\n{alerta}"


SCHEMA_INICIO = {
    "type": "object",
    "properties": {
        "hay_algo": {"type": "boolean"},
        "puntos": {"type": "array", "items": {"type": "object", "properties": {
            "texto": {"type": "string"}, "clientes": {"type": "array", "items": {"type": "string"}}},
            "required": ["texto", "clientes"]}},
    },
    "required": ["hay_algo", "puntos"],
}


def aviso_inicio(tipo: str, titulo: str, url: str, agenda: list[str],
                 generar=llm.generar) -> str | None:
    """Aviso de sesion EN VIVO solo si su agenda (o, sin agenda, la comision)
    le toca a un cliente; None si no. El 20/10 avisaba de todas las comisiones."""
    perfiles = _perfiles(_pais(tipo))
    if not perfiles:
        return None
    ag = "\n".join(f"- {p}" for p in agenda) or "(sin agenda; juzga por la comision y el titulo)"
    prompt = (f"Perfiles de los clientes:\n{perfiles}\n\nSesion que empieza: {tipo} — {titulo}\n"
              f"Agenda:\n{ag}\n\n'puntos' = solo los puntos de agenda (resumidos en una frase) que "
              "le tocan a un cliente, con sus slugs. Sin agenda, un solo punto si la comision trata "
              "temas del cliente.")
    r = json.loads(generar(prompt, system=SYSTEM, modelo=llm.LITE, schema=SCHEMA_INICIO) or "{}")
    puntos = [p for p in r.get("puntos") or [] if str(p.get("texto", "")).strip()]
    if not r.get("hay_algo") or not puntos:
        return None
    lineas = [f"• {p['texto'].strip()}" + (f" ({_quienes(p['clientes'])})"
                                           if _quienes(p.get("clientes")) else "") for p in puntos]
    pre = "Asamblea EC" if _pais(tipo) == "EC" else "Congreso"
    return f"🔴 {pre} EN VIVO · {tipo}\n{titulo}\n\n" + "\n".join(lineas) + f"\n\n{url}"


SYSTEM_VOTO = ("Te pasan un extracto de transcripcion automatica (con errores de dictado) de un "
               "Pleno donde hubo una votacion o un cuarto intermedio. Di en 1 o 2 frases cortas que "
               "se voto y el resultado con el conteo si se oye. Si no se entiende que se voto, dilo. "
               "Español simple, sin dos puntos como conector.")


def resumir_votacion(extracto: str, generar=llm.generar) -> str:
    """Una o dos frases de que se voto; si Gemini falla, el extracto tal cual."""
    try:
        return (generar(extracto, system=SYSTEM_VOTO, modelo=llm.LITE) or "").strip() or extracto
    except Exception as e:
        print(f"[live-transcribe] resumen de votacion fallo: {e}")
        return extracto
