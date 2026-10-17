"""Gemini: un solo cliente por proceso y los nombres de modelo en un lugar."""
from __future__ import annotations

import os

FLASH = "gemini-3.6-flash"  # 20 pedidos/dia compartidos con los chats
LITE = "gemini-3.5-flash-lite"

_cliente = None


def cliente():
    """El cliente vive a nivel de modulo: si el GC lo recolecta, cierra la
    sesion HTTP que siguen usando los chats creados con el."""
    global _cliente
    if _cliente is None:
        key = os.environ.get("GEMINI_API_KEY")
        if not key:
            raise RuntimeError("Falta GEMINI_API_KEY en el entorno")
        from google import genai
        _cliente = genai.Client(api_key=key)
    return _cliente


def disponible() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY"))


def generar(prompt: str, system: str | None = None, modelo: str = FLASH,
            json: bool = False, schema=None) -> str:
    """Texto de la respuesta (vacio si Gemini no devolvio nada)."""
    from google.genai import types
    extra = {}
    if json or schema is not None:
        extra["response_mime_type"] = "application/json"
    if schema is not None:
        extra["response_schema"] = schema
    resp = cliente().models.generate_content(
        model=modelo, contents=prompt,
        config=types.GenerateContentConfig(system_instruction=system, **extra))
    return (resp.text or "").strip()
