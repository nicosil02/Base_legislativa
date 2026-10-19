"""Gemini: un solo cliente por proceso y los nombres de modelo en un lugar."""
from __future__ import annotations

import os
import time

FLASH = "gemini-3.6-flash"  # 20 pedidos/dia compartidos con los chats
LITE = "gemini-3.5-flash-lite"
GEMMA = "gemma-4-26b-a4b-it"  # cupo propio; ultimo respaldo (lo usa cerebro/grafo.py)
ESPERAS = (3, 10)  # segundos entre reintentos del mismo modelo

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


def _cadena(modelo: str) -> list[str]:
    """Modelos a probar en orden: el pedido y despues los mas baratos."""
    orden = [FLASH, LITE, GEMMA]
    return orden[orden.index(modelo):] if modelo in orden else [modelo]


def _tipo_error(e: Exception) -> str:
    """'dia' (cupo diario: pasar al siguiente modelo), 'pasajero' (429 por
    minuto, 500, 503: esperar y reintentar) u 'otro' (levantar)."""
    txt = str(e)
    codigo = getattr(e, "code", None)
    if "PerDay" in txt:
        return "dia"
    if codigo in (429, 500, 503) or any(x in txt for x in ("429", "503", "UNAVAILABLE", "RESOURCE_EXHAUSTED")):
        return "pasajero"
    return "otro"


def _llamar(modelo: str, prompt: str, system: str | None, json: bool, schema) -> str:
    from google.genai import types
    extra = {}
    if modelo.startswith("gemma"):
        # Gemma no acepta system_instruction ni modo JSON: va todo en el texto.
        if json or schema is not None:
            import json as _json
            prompt += "\n\nResponde SOLO con JSON valido, sin texto alrededor"
            prompt += f" y con este esquema: {_json.dumps(schema)}" if schema is not None else "."
        if system:
            prompt = f"{system}\n\n{prompt}"
        system = None
    else:
        if json or schema is not None:
            extra["response_mime_type"] = "application/json"
        if schema is not None:
            extra["response_schema"] = schema
    resp = cliente().models.generate_content(
        model=modelo, contents=prompt,
        config=types.GenerateContentConfig(system_instruction=system, **extra))
    texto = (resp.text or "").strip()
    if modelo.startswith("gemma") and texto.startswith("```"):
        texto = texto.strip("`").removeprefix("json").strip()
    return texto


def generar(prompt: str, system: str | None = None, modelo: str = FLASH,
            json: bool = False, schema=None) -> str:
    """Texto de la respuesta (vacio si Gemini no devolvio nada).

    429 por minuto / 503: reintenta el mismo modelo con espera corta. Cupo
    diario agotado o reintentos gastados: pasa al siguiente de la cadena
    (FLASH -> LITE -> GEMMA). Quien pide LITE nunca sube a FLASH."""
    ultimo = None
    for m in _cadena(modelo):
        for espera in ESPERAS + (None,):
            try:
                return _llamar(m, prompt, system, json, schema)
            except Exception as e:
                tipo = _tipo_error(e)
                if tipo == "otro":
                    raise
                ultimo = e
                print(f"[llm] {m} fallo ({str(e)[:120]})", flush=True)
                if tipo == "dia" or espera is None:
                    break
                time.sleep(espera)
    raise ultimo
