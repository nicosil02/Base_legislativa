"""Entrenamiento del clasificador supervisado de temas.

Lee PLs con `tema_manual=1` de proyectos.db (14,589 ejemplos), construye
TF-IDF features con word + char n-grams, entrena Logistic Regression
multinomial, evalua con stratified k-fold cross-validation, persiste el
modelo a models/clasificador_pe.joblib.

Notas de diseno:
- Usamos titulo + sumilla (cuando existe) como texto de entrada
- Normalizacion: lowercase + sin acentos (consistente con scraper/categorias.py)
- TF-IDF combinado: word 1-2gram (semantica) + char 4-5gram (morfologia
  y robustez a errores). El char n-gram permite captar variaciones tipo
  "agroindustri" matcheando con "agroindustria" o "agroindustrias".
- LogisticRegression con C alto (poca regularizacion) y class_weight=balanced
  para que las categorias raras (Deporte, Seguros) no se ahoguen frente
  a las dominantes (Otros, Educacion).
- max_iter=2000 (LR a veces no converge en <1000 con char n-grams).
"""
from __future__ import annotations

import sqlite3
import unicodedata
from pathlib import Path
from typing import Sequence

import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, f1_score
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.pipeline import FeatureUnion, Pipeline


# Path por defecto donde se persiste el modelo entrenado.
MODEL_DIR = Path(__file__).resolve().parent.parent / "models"
MODEL_PATH = MODEL_DIR / "clasificador_pe.joblib"


def normalize_text(s: str | None) -> str:
    """Lowercase + sin acentos. Mismo criterio que scraper/categorias.py."""
    if not s:
        return ""
    s = s.lower()
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s


def load_training_data(db_path: str = "proyectos.db") -> tuple[list[str], list[str]]:
    """Lee PLs etiquetados manualmente. Devuelve (textos, etiquetas).

    Texto = titulo + sumilla concatenados (normalizado).
    Etiqueta = columna `tema`.
    """
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT
              COALESCE(titulo, '') AS titulo,
              COALESCE(sumilla, '') AS sumilla,
              tema
            FROM proyectos
            WHERE tema_manual = 1 AND tema IS NOT NULL AND tema != ''
            """
        ).fetchall()
    finally:
        conn.close()

    textos: list[str] = []
    labels: list[str] = []
    for titulo, sumilla, tema in rows:
        text = normalize_text(f"{titulo} {sumilla}")
        if not text.strip():
            continue
        textos.append(text)
        labels.append(tema)
    return textos, labels


def build_pipeline() -> Pipeline:
    """Construye el pipeline TF-IDF (word + char) + LogReg multinomial.

    Hyperparameters elegidos en base a benchmarks en datasets de texto
    espanol de tamano similar:
    - word 1-2gram con min_df=3, max_df=0.7: captura colocaciones tipo
      "salud mental" sin ahogarse en stopwords.
    - char 4-5gram con min_df=5: robustez a morfologia (plurales, verbos
      conjugados) y errores tipograficos.
    - sublinear_tf=True: aplica 1+log(tf), suaviza valores de frequencia.
    - LR C=4.0: poca regularizacion (tenemos mucho data, low overfitting risk).
    - class_weight='balanced': pesa por frecuencia inversa, levanta clases raras.
    """
    word_tfidf = TfidfVectorizer(
        analyzer="word",
        ngram_range=(1, 2),
        min_df=3,
        max_df=0.7,
        sublinear_tf=True,
        strip_accents=None,  # ya lo hicimos en normalize_text
        lowercase=False,     # idem
    )
    char_tfidf = TfidfVectorizer(
        analyzer="char_wb",
        ngram_range=(4, 5),
        min_df=5,
        max_df=0.85,
        sublinear_tf=True,
        strip_accents=None,
        lowercase=False,
    )
    features = FeatureUnion(
        [("word", word_tfidf), ("char", char_tfidf)],
        n_jobs=1,  # evitar overhead en CI
    )
    clf = LogisticRegression(
        C=4.0,
        max_iter=3000,
        class_weight="balanced",
        # sklearn 1.8 removio el soporte multiclass de liblinear → lbfgs
        # es el default moderno y maneja 30 clases sin problema en este
        # tamano de dataset (~14k ejemplos, ~50k features).
        solver="lbfgs",
    )
    return Pipeline([("features", features), ("clf", clf)])


def evaluate(textos: Sequence[str], labels: Sequence[str], k: int = 5) -> dict:
    """Cross-validation k-fold estratificado. Devuelve metricas."""
    pipeline = build_pipeline()
    skf = StratifiedKFold(n_splits=k, shuffle=True, random_state=42)
    print(f"[evaluate] {k}-fold cross-validation sobre {len(textos):,} ejemplos...")
    y_pred = cross_val_predict(pipeline, textos, labels, cv=skf, n_jobs=1)
    # Macro F1 (promedio simple, igual peso por clase) y weighted F1
    f1_macro = f1_score(labels, y_pred, average="macro", zero_division=0)
    f1_weighted = f1_score(labels, y_pred, average="weighted", zero_division=0)
    print(f"\n[evaluate] F1 macro    = {f1_macro:.3f}")
    print(f"[evaluate] F1 weighted = {f1_weighted:.3f}\n")
    print(classification_report(labels, y_pred, zero_division=0, digits=3))
    return {
        "f1_macro": f1_macro,
        "f1_weighted": f1_weighted,
        "n_samples": len(textos),
    }


def train_final(textos: Sequence[str], labels: Sequence[str]) -> Pipeline:
    """Entrena con TODO el dataset (sin CV) y devuelve el pipeline final."""
    pipeline = build_pipeline()
    print(f"[train] entrenando modelo final con {len(textos):,} ejemplos...")
    pipeline.fit(textos, labels)
    return pipeline


def save(model: Pipeline, path: Path = MODEL_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, path, compress=3)
    size_mb = path.stat().st_size / (1024 * 1024)
    print(f"[save] modelo guardado en {path} ({size_mb:.1f} MB)")


def load(path: Path = MODEL_PATH) -> Pipeline:
    return joblib.load(path)
