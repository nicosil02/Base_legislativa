"""Juntar la misma historia contada por varios canales/medios: una alerta
por historia, no por medio.

Embeddings del cerebro (MiniLM multilingue, cerebro/embeddings.embeber) +
clustering greedy por similitud coseno: dos canales cuentan lo mismo con
palabras distintas. Si el modelo no esta disponible, cae a TF-IDF.
"""
from __future__ import annotations

import re

from core.text import norm

UMBRAL_EMB = 0.78    # ponytail: elegido con los fragmentos reales del 28/09 (sueldo minimo en 3 canales); ajustar mirando grupos reales
UMBRAL_TFIDF = 0.45


def _similitudes(textos: list[str], modelo: bool = True):
    import numpy as np
    try:
        if not modelo:
            raise RuntimeError("sin modelo")
        from cerebro.embeddings import embeber
        v = np.array(embeber(textos), dtype="float32")
        v /= np.linalg.norm(v, axis=1, keepdims=True) + 1e-9
        return v @ v.T, UMBRAL_EMB
    except Exception:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity
        m = TfidfVectorizer(min_df=1).fit_transform(textos)
        return cosine_similarity(m), UMBRAL_TFIDF


def agrupar(textos: list[str], sims=None, umbral: float | None = None,
            modelo: bool = True) -> list[int]:
    """Indice de grupo por texto. Greedy: cada texto entra al primer grupo
    cuyo representante (el primero, o sea el mas reciente si vienen
    ordenados) supera el umbral. modelo=False usa TF-IDF (para la app web:
    cargar el modelo de embeddings ahi cuesta ~600 MB de RAM)."""
    if not textos:
        return []
    if sims is None:
        sims, umbral_def = _similitudes(textos, modelo)
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


# Noticias escritas, con los vectores ya guardados en cerebro.db (la app web no
# carga el modelo). Calibrado 2026-10-17 con noticias PE/EC reales de dos dias:
# entre portales distintos, desde 0.82 es el mismo hecho (Senado y facultades en
# El Comercio e Infobae, crudo colombiano en Vistazo y Primicias). Dentro de un
# mismo portal no se junta: ahi lo parecido son plantillas (clima de Piura vs
# Iquitos, dos sesiones de la Agenda). Normas con el mismo formato y numero
# distinto (DS 200-2026-EF vs 201-2026-EF) tampoco.
UMBRAL_NOTICIAS = 0.82
_NUM_NORMA = re.compile(r"\b\d{1,6}-\d{4}(?:-[A-Z]+)?\b")


def similitudes_noticias(vectores: list, titulos: list[str], fuentes: list[str] | None = None):
    """Matriz para agrupar(): coseno entre vectores (None = sin vector, queda
    sola), 0 entre noticias del mismo portal y entre normas con numeros distintos."""
    import numpy as np
    n = len(titulos)
    dim = next((len(v) for v in vectores if v is not None), 1)
    m = np.stack([np.asarray(v, dtype="float32") if v is not None else np.zeros(dim, "float32")
                  for v in vectores]) if n else np.zeros((0, dim), "float32")
    sims = m @ m.T
    np.fill_diagonal(sims, 1.0)
    normas = [set(_NUM_NORMA.findall(t or "")) for t in titulos]
    for i in range(n):
        for j in range(i + 1, n):
            if (fuentes and fuentes[i] == fuentes[j]) or (normas[i] and normas[j] and not normas[i] & normas[j]):
                sims[i, j] = sims[j, i] = 0.0
    return sims


def _tokens(s: str) -> set[str]:
    return {t for t in re.findall(r"\w{4,}", s.lower())}


def ya_avisado(que: str, recientes: list[str], umbral: float = 0.5) -> bool:
    """Para los avisos de WhatsApp: el 'que' (una oracion de Gemini) se
    parece a uno ya enviado. Jaccard de palabras largas, sin modelo: corre
    en los runners de GitHub, donde no bajamos los 120 MB del MiniLM."""
    a = _tokens(que)
    return any(a and len(a & (b := _tokens(r))) / len(a | b) >= umbral for r in recientes)


_RELLENO = {"gobierno", "presentado", "presento", "considerarlo", "considera", "anuncio", "resolvio",
            "senalo", "afirmo", "indico", "desde", "sobre", "segun", "tiene", "hacia", "entre", "porque",
            "tambien", "manera", "mediante", "respecto", "importa", "busca", "podria", "seria", "ademas",
            "acreditar", "amplio", "urgencia", "nuevo", "nueva", "durante"}


def _claves_busqueda(que: str) -> list[str]:
    """Nombres propios primero (Keiko, Senasa, Vinelli), despues las palabras
    largas con contenido; sin verbos de relleno ("resolvio", "presentado")
    que vuelven la busqueda demasiado especifica y no trae nada."""
    n = norm  # palabras \w{4,}: sin espacios, norm == sin_tildes(lower)
    palabras = re.findall(r"\w{4,}", que)
    propios = [w for w in palabras[1:] if w[0].isupper() and n(w) not in _RELLENO]
    resto = sorted({w for w in palabras if not w[0].isupper() and n(w) not in _RELLENO}, key=len, reverse=True)
    vistos, out = set(), []
    for w in propios + resto:
        if n(w) not in vistos:
            vistos.add(n(w))
            out.append(w)
    return out[:5]


def titulos_prensa(que: str, pais: str = "PE") -> list[str]:
    """Titulos de Google News de las ultimas 24 h para las palabras clave de
    `que` (sin API key, el mismo RSS que ya usa noticias/fuentes.py)."""
    import html
    import urllib.parse
    import urllib.request
    claves = _claves_busqueda(que)
    if not claves:
        return []
    q = urllib.parse.quote(" ".join(claves) + " when:1d")
    gl = "EC" if pais == "EC" else "PE"
    url = f"https://news.google.com/rss/search?q={q}&hl=es-419&gl={gl}&ceid={gl}:es-419"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        xml = urllib.request.urlopen(req, timeout=15).read().decode("utf-8", "replace")
    except Exception:
        return []
    return [html.unescape(t) for t in re.findall(r"<item>.*?<title>(.*?)</title>", xml, re.S)]


def ya_en_prensa(que: str, pais: str = "PE") -> str | None:
    """Titulo de prensa escrita (Google News, 24 h) que ya cuenta el mismo
    hecho, o None: el aviso de TV solo sirve si se adelanta a la prensa.
    Gemini compara (mismo hecho con otras palabras: 'propone rechazar' vs
    'resolvio rechazar'); sin key, palabras."""
    import json
    import os

    from core import llm
    titulos = titulos_prensa(que, pais)[:15]
    if not titulos:
        return None
    if llm.disponible():
        try:
            lista = "\n".join(f"{i}. {t}" for i, t in enumerate(titulos))
            texto = llm.generar(
                f"Hecho: {que}\n\nTitulares:\n{lista}",
                system="Decidi si alguno de los titulares informa el MISMO hecho concreto "
                       "(no solo el mismo tema). Responde SOLO JSON {\"indice\": n} con el "
                       "numero del titular, o {\"indice\": null} si ninguno.",
                modelo=llm.LITE, json=True)
            i = json.loads(texto or "{}").get("indice")
            if os.environ.get("TV_AVISO_DEBUG"):
                print(f"[prensa] {len(titulos)} titulares, Gemini indice={i}", flush=True)
            return titulos[i] if isinstance(i, int) and 0 <= i < len(titulos) else None
        except Exception:
            pass
    a = _tokens(que)
    for t in titulos:
        b2 = _tokens(t)
        if a and len(a & b2) / min(len(a), len(b2) or 1) >= 0.4:
            return t
    return None

