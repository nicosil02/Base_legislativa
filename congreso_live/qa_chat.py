"""Preguntas y respuestas sobre UNA transcripcion de sesion, via Gemini
(tier gratuito, para que el chat no tenga costo por uso)."""
from __future__ import annotations

from core import llm

SYSTEM_PROMPT = (
    "Sos un asistente que responde preguntas sobre UNA transcripcion de una "
    "sesion del Congreso del Peru (Pleno o comision). Respondes SOLO en base "
    "al texto de la transcripcion dada - si algo no aparece ahi, decis "
    "explicitamente que esta sesion no lo menciona, nunca inventas. "
    "Respuestas breves y directas, en espanol, sin repetir la pregunta."
)


def preguntar(pregunta: str, transcripcion: str, titulo: str = "") -> str:
    """Responde `pregunta` usando `transcripcion` como unico contexto.
    RuntimeError si falta GEMINI_API_KEY; los errores del SDK se propagan."""
    if not llm.disponible():
        raise RuntimeError("Falta GEMINI_API_KEY en el entorno")
    contexto = f"Sesion: {titulo}\n\nTranscripcion:\n{transcripcion}" if titulo else transcripcion
    return llm.generar(f"{contexto}\n\nPregunta: {pregunta}", system=SYSTEM_PROMPT, modelo=llm.FLASH)
