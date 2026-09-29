"""Juntar la misma historia contada por varios canales/medios (pedido de
Nicolas 2026-09-28, punto 1 de la revision de repos de monitoreo de medios:
"una alerta por historia, no por medio").

Embeddings del cerebro (MiniLM multilingue, cerebro/embeddings.embeber) +
clustering greedy por similitud coseno, igual criterio que
noticias/digest._agrupar_por_similitud pero por significado y no por
palabras del titulo: dos canales cuentan lo mismo con palabras distintas.
Si el modelo no esta disponible, cae a TF-IDF.
"""
from __future__ import annotations

import re

UMBRAL_EMB = 0.78    # ponytail: elegido con los fragmentos reales del 28/09 (sueldo minimo en 3 canales); ajustar mirando grupos reales
UMBRAL_TFIDF = 0.45


def _similitudes(textos: list[str]):
    import numpy as np
    try:
        from cerebro.embeddings import embeber
        v = np.array(embeber(textos), dtype="float32")
        v /= np.linalg.norm(v, axis=1, keepdims=True) + 1e-9
        return v @ v.T, UMBRAL_EMB
    except Exception:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity
        m = TfidfVectorizer(min_df=1).fit_transform(textos)
        return cosine_similarity(m), UMBRAL_TFIDF


def agrupar(textos: list[str], sims=None, umbral: float | None = None) -> list[int]:
    """Indice de grupo por texto. Greedy: cada texto entra al primer grupo
    cuyo representante (el primero, o sea el mas reciente si vienen
    ordenados) supera el umbral."""
    if not textos:
        return []
    if sims is None:
        sims, umbral_def = _similitudes(textos)
        umbral = umbral if umbral is not None else umbral_def
    grupo = [-1] * len(textos)
    reps: list[int] = []
    for i in range(len(textos)):
        for g, r in enumerate(reps):
            if sims[i][r] >= umbral:
                grupo[i] = g
                break
        else:
            grupo[i] = len(reps)
            reps.append(i)
    return grupo


def _tokens(s: str) -> set[str]:
    return {t for t in re.findall(r"\w{4,}", s.lower())}


def ya_avisado(que: str, recientes: list[str], umbral: float = 0.5) -> bool:
    """Para los avisos de WhatsApp: el 'que' (una oracion de Gemini) se
    parece a uno ya enviado. Jaccard de palabras largas, sin modelo: corre
    en los runners de GitHub, donde no bajamos los 120 MB del MiniLM."""
    a = _tokens(que)
    return any(a and len(a & (b := _tokens(r))) / len(a | b) >= umbral for r in recientes)


def _demo():
    import numpy as np
    sims = np.array([[1, .9, .1], [.9, 1, .2], [.1, .2, 1]])
    assert agrupar(["a", "b", "c"], sims=sims, umbral=0.78) == [0, 0, 1]
    assert ya_avisado("El gobierno sube el sueldo minimo a 1230 soles desde octubre",
                      ["Gobierno anuncia que el sueldo minimo sube a 1230 soles desde octubre"])
    assert not ya_avisado("Senasa aprueba requisitos para importar semillas",
                          ["Gobierno anuncia que el sueldo minimo sube a 1230 soles"])
    print("OK historias: agrupa por similitud y detecta avisos repetidos")


if __name__ == "__main__":
    _demo()
