"""Inferencia con el modelo de models/clasificador_pe.joblib: (tema, confianza)."""
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


def predict_tema(titulo: str | None, sumilla: str | None = None) -> tuple[str, float]:
    """(tema, probabilidad de esa clase 0..1)."""
    text = normalize_text(f"{titulo or ''} {sumilla or ''}")
    if not text.strip():
        return ("Otros", 0.0)
    model = _load_model()
    probas = model.predict_proba([text])[0]
    idx = int(probas.argmax())
    return (model.classes_[idx], float(probas[idx]))


def predict_tema_batch(textos: list[str]) -> list[tuple[str, float]]:
    """Versión batch (para reclassify)."""
    if not textos:
        return []
    model = _load_model()
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
