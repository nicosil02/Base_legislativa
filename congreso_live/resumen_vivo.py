"""Resumen en vivo de una sesion, cada ~10 min, a Telegram SOLO si lo nuevo
le toca a un cliente (perfil = clientes/<slug>/notas.md). Lo que no
interesa no se manda: la web guarda la transcripcion entera igual.

Mismo criterio que las mesas de trabajo: opiniones sueltas no valen, solo
hechos (votacion, aprobacion, compromiso, anuncio, PL o norma nombrados,
autoridad que fija posicion sobre un tema del cliente)."""
from __future__ import annotations

import json

from core import llm

CADA_SEG = 600
MIN_CHARS = 800  # menos texto nuevo que esto: se espera al siguiente tramo

SYSTEM = ("Eres analista de asuntos publicos. Lees un tramo de la transcripcion automatica "
          "(con errores de dictado) de una sesion parlamentaria y decides si hay algo que un "
          "cliente deba saber YA, segun su perfil. Solo hechos: votaciones, aprobaciones, "
          "compromisos, anuncios, proyectos de ley o normas nombrados, una autoridad que fija "
          "posicion sobre un tema del cliente. Opiniones sin resultado, saludos, tramite y "
          "debate general NO. Ante la duda, no. Español simple, sin dos puntos como conector.")

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


def resumir(tipo: str, titulo: str, texto_nuevo: str, generar=llm.generar) -> str | None:
    """Mensaje de Telegram listo para mandar, o None si no hay nada de interes."""
    pais = "EC" if tipo.endswith("(EC)") else "PE"
    perfiles = _perfiles(pais)
    if not perfiles:
        return None
    prompt = (f"Perfiles de los clientes:\n{perfiles}\n\nSesion: {tipo} — {titulo}\n\n"
              f"Tramo nuevo de la transcripcion:\n{texto_nuevo[-12000:]}\n\n"
              "Si hay algo, 'puntos' son 1 a 3 frases cortas con el hecho y a quien le toca; "
              "'clientes' son los slugs afectados.")
    r = json.loads(generar(prompt, system=SYSTEM, modelo=llm.LITE, schema=SCHEMA) or "{}")
    puntos = [p.strip() for p in r.get("puntos") or [] if p.strip()]
    if not r.get("hay_algo") or not puntos:
        return None
    quienes = ", ".join(c.capitalize() for c in r.get("clientes") or [])
    return (f"📝 *{tipo}* en vivo" + (f" ({quienes})" if quienes else "") + f"\n{titulo}\n\n"
            + "\n".join(f"• {p}" for p in puntos))
