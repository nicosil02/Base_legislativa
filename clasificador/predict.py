"""Inferencia con el clasificador entrenado.

Carga el modelo persistido en models/clasificador_pe.joblib y expone una
funcion `predict_tema(titulo, sumilla)` que devuelve (tema, confianza).

Usado por:
- scraper/sync incremental para clasificar PLs nuevos
- clasificador/reclassify para revisar PLs en "Otros"
- Streamlit UI (futuro) para mostrar sugerencias
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import joblib

from .train import MODEL_PATH, normalize_text


@lru_cache(maxsize=1)
def _load_model(path: str = str(MODEL_PATH)):
    """Carga lazy + memoiza el modelo (cara por joblib.load: ~500 ms)."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"Modelo no encontrado en {p}. Entrena primero con: "
            "python -m clasificador.cli train"
        )
    return joblib.load(p)


def predict_tema(
    titulo: str | None,
    sumilla: str | None = None,
    model_path: str | None = None,
) -> tuple[str, float]:
    """Predice el tema para un PL nuevo.

    Args:
        titulo: titulo del PL
        sumilla: sumilla/descripcion (opcional, mejora precision)
        model_path: ruta custom al modelo (default: models/clasificador_pe.joblib)

    Returns:
        (tema, confidence) donde confidence es la probabilidad del LogReg
        para la clase elegida (0..1).
    """
    text = normalize_text(f"{titulo or ''} {sumilla or ''}")
    if not text.strip():
        return ("Otros", 0.0)
    model = _load_model(model_path or str(MODEL_PATH))
    probas = model.predict_proba([text])[0]
    idx = int(probas.argmax())
    return (model.classes_[idx], float(probas[idx]))


def predict_tema_batch(
    textos: list[str],
    model_path: str | None = None,
) -> list[tuple[str, float]]:
    """Version batch (mas eficiente para reclassify)."""
    if not textos:
        return []
    model = _load_model(model_path or str(MODEL_PATH))
    norm = [normalize_text(t) for t in textos]
    probas = model.predict_proba(norm)
    idxs = probas.argmax(axis=1)
    return [
        (model.classes_[idxs[i]], float(probas[i, idxs[i]]))
        for i in range(len(textos))
    ]


def topk(titulo: str | None, sumilla: str | None = None, k: int = 5) -> list[tuple[str, float]]:
    """Top-K predicciones con sus probabilidades. Util para debug."""
    text = normalize_text(f"{titulo or ''} {sumilla or ''}")
    if not text.strip():
        return [("Otros", 1.0)]
    model = _load_model()
    probas = model.predict_proba([text])[0]
    pairs = list(zip(model.classes_, probas))
    pairs.sort(key=lambda p: -p[1])
    return [(cat, float(prob)) for cat, prob in pairs[:k]]
