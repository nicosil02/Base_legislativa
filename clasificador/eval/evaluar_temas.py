"""Evalua clasificar() (noticias/temas.py) contra un set de oro etiquetado a mano.

gold_noticias.csv: 300 noticias PE/EC (25/08 a 12/10/2026) etiquetadas por un
humano, multi-etiqueta, en los 4 temas de clientes (Salud, Crop, Tech / Digital,
KYC / AML / Financiero; "Coyuntura política" no se etiqueto). La muestra NO es
aleatoria: se enriquecio con candidatos de cada tema (lo que marcan las
keywords y lo que el cerebro ve parecido sin keyword), asi que la precision y
el recall valen por tema, no como tasa de la base completa.

Uso:  python -X utf8 -m clasificador.eval.evaluar_temas [--errores N]
Sin red ni modelos: solo lee el CSV y corre las keywords actuales.
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

from noticias.temas import clasificar

GOLD = Path(__file__).with_name("gold_noticias.csv")
TEMAS = ["Salud", "Crop", "Tech / Digital", "KYC / AML / Financiero"]


def cargar(path: Path = GOLD) -> list[dict]:
    with open(path, encoding="utf-8", newline="") as f:
        filas = list(csv.DictReader(f))
    for r in filas:
        r["gold"] = set(filter(None, r["labels"].split(";")))
    return filas


def prf(pred: list[bool], real: list[bool]) -> tuple[float, float, float]:
    tp = sum(p and g for p, g in zip(pred, real))
    fp = sum(p and not g for p, g in zip(pred, real))
    fn = sum(g and not p for p, g in zip(pred, real))
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return p, r, (2 * p * r / (p + r) if p + r else 0.0)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--errores", type=int, default=8, help="ejemplos de FN/FP por tema")
    n = ap.parse_args().errores
    filas = cargar()
    for r in filas:
        r["kw"] = set(clasificar(r["titulo"], r["resumen"], r["url"]))
    print(f"{len(filas)} noticias\n{'tema':<24}{'pos':>5}{'P':>7}{'R':>7}{'F1':>7}")
    for t in TEMAS:
        real = [t in r["gold"] for r in filas]
        p, rc, f1 = prf([t in r["kw"] for r in filas], real)
        print(f"{t:<24}{sum(real):>5}{p:>7.2f}{rc:>7.2f}{f1:>7.2f}")
    for t in TEMAS:
        fn = [r["titulo"] for r in filas if t in r["gold"] and t not in r["kw"]]
        fp = [r["titulo"] for r in filas if t in r["kw"] and t not in r["gold"]]
        print(f"\n== {t}: {len(fn)} FN, {len(fp)} FP")
        for x in fn[:n]:
            print("  FN", x[:110])
        for x in fp[:n]:
            print("  FP", x[:110])


def _test_prf():
    assert prf([True, True, False], [True, False, True]) == (0.5, 0.5, 0.5)
    assert prf([False], [False]) == (0.0, 0.0, 0.0)


if __name__ == "__main__":
    _test_prf()
    main()
