"""Preguntas y respuestas sobre UNA transcripcion de sesion, via Gemini.

Gemini (tier gratuito de Google AI Studio) en vez de la API de Claude -
decision de Nicolas 2026-09-15 para que este chat no genere costo por uso.
GEMINI_API_KEY vive en st.secrets (Streamlit Cloud) o .env (local), nunca
en el codigo - ver app.py, que ya proyecta ambos a variables de entorno.
"""
from __future__ import annotations

import os

SYSTEM_PROMPT = (
    "Sos un asistente que responde preguntas sobre UNA transcripcion de una "
    "sesion del Congreso del Peru (Pleno o comision). Respondes SOLO en base "
    "al texto de la transcripcion dada - si algo no aparece ahi, decis "
    "explicitamente que esta sesion no lo menciona, nunca inventas. "
    "Respuestas breves y directas, en espanol, sin repetir la pregunta."
)


def preguntar(pregunta: str, transcripcion: str, titulo: str = "") -> str:
    """Responde `pregunta` usando `transcripcion` como unico contexto.

    Levanta RuntimeError si falta la API key, o lo que levante el SDK de
    Gemini ante un error de red/API - el caller decide como mostrarlo."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("Falta GEMINI_API_KEY en el entorno")

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    contexto = f"Sesion: {titulo}\n\nTranscripcion:\n{transcripcion}" if titulo else transcripcion
    resp = client.models.generate_content(
        model="gemini-3.6-flash",
        contents=f"{contexto}\n\nPregunta: {pregunta}",
        config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT),
    )
    return (resp.text or "").strip()


def _demo():
    """Self-check sin red: preguntar() debe exigir GEMINI_API_KEY antes de
    intentar nada. Para probar contra la API real: python -m congreso_live.qa_chat live"""
    saved = os.environ.pop("GEMINI_API_KEY", None)
    try:
        try:
            preguntar("test", "texto de prueba")
            raise AssertionError("deberia haber fallado sin API key")
        except RuntimeError as e:
            assert "GEMINI_API_KEY" in str(e), e
    finally:
        if saved is not None:
            os.environ["GEMINI_API_KEY"] = saved
    print("OK qa_chat: preguntar() exige GEMINI_API_KEY antes de llamar a la API")


def _demo_live():
    """Prueba real contra la API de Gemini (requiere GEMINI_API_KEY valida
    en el entorno) - no se corre en el self-check normal para no gastar
    cuota/depender de red."""
    transcripcion = (
        "Presidenta: Damos inicio a la sesion. Primer punto: se aprueba "
        "por unanimidad el proyecto de ley 1234 sobre pesca artesanal. "
        "Segundo punto: se posterga el debate sobre mineria informal para "
        "la proxima sesion por falta de quorum."
    )
    respuesta = preguntar("¿Que se aprobo en esta sesion?", transcripcion,
                          titulo="Sesion de prueba")
    assert respuesta, "respuesta vacia"
    print("OK qa_chat: respuesta real de Gemini:")
    print(respuesta)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "live":
        _demo_live()
    else:
        _demo()
