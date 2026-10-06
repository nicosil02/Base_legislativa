"""Une openpolitica (2021-07 a 2024-03-07) + OCR propio (2024-03 a 2026-06)
en una sola tabla `voto_pleno` con nombre canonico y bancada completa.

  python -m votaciones.unificar --op op.db --ocr votaciones_pe.db --salida votaciones_pleno_2021_2026.db

Nombres: el PDF trunca los largos ("BAZAN CALDERON, DIEGO ALONSO") y el OCR
mete errores; se cruzan contra los nombres completos de openpolitica por
prefijo y, si no, por parecido (difflib >= 0.85). Lo que no cruza queda
con su nombre crudo y se lista para revisar.
Bancada: la sigla falta en ~35% de filas OCR; se completa con la sigla mas
frecuente de ese congresista en la misma sesion (y si no, en el mes).
"""
from __future__ import annotations

import argparse
import collections
import difflib
import re
import sqlite3
import unicodedata


def clave(s: str | None) -> str:
    s = "".join(c for c in unicodedata.normalize("NFD", (s or "").upper()) if unicodedata.category(c) != "Mn")
    return re.sub(r"[^A-Z]", "", s)


def canonizador(canonicos: list[str]):
    claves = {clave(c): c for c in canonicos}
    cache: dict[str, str | None] = {}

    def f(nombre: str) -> str | None:
        if nombre in cache:
            return cache[nombre]
        # sigla de bancada pegada al final: "MONTOYA MANRIQUE, JORGE JPP-VP"
        partes = nombre.rsplit(" ", 1)
        limpio = partes[0] if len(partes) == 2 and partes[1] in SIGLAS and "," in nombre else nombre
        k = clave(ALIAS.get(clave(limpio), limpio))
        res = claves.get(k)
        if not res and len(k) >= 12:
            pref = [c for kc, c in claves.items() if kc.startswith(k) or k.startswith(kc)]
            res = pref[0] if len(pref) == 1 else None
        if not res:
            m = difflib.get_close_matches(k, list(claves), n=1, cutoff=0.85)
            res = claves[m[0]] if m else None
        cache[nombre] = res
        return res
    return f


# Mismo congresista con otro formato de nombre en el PDF.
ALIAS = {"ECHAIZRAMOSVDADENUNEZGLADYS": "ECHAÍZ DE NÚÑEZ IZAGA, GLADYS MARGOT"}

# Solo estas se quitan del final del nombre (antes un regex generico se
# comia nombres de 4 letras como RUTH).
SIGLAS = {"FP", "PL", "AP", "APP", "AP-PIS", "RP", "NA", "BM", "CD-JPP", "PP", "SP", "PB", "PD", "ID",
          "JP", "UDP", "SP-PM", "CD", "JPP-VP", "HYD", "BDP", "BS", "LN", "JPP", "APAIS"}

BANCADA_OCR = {"8DP": "BDP", "8M": "BM", "8S": "BS", "CD-1PP": "CD-JPP", "1PP": "JPP", "HYO": "HYD",
               "CP-JPP": "CD-JPP", "IIYD": "HYD", "BOP": "BDP", "JPP-YP": "JPP-VP"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--op", required=True)
    ap.add_argument("--ocr", required=True)
    ap.add_argument("--salida", default="votaciones_pleno_2021_2026.db")
    a = ap.parse_args(argv)

    op = sqlite3.connect(a.op)
    ocr = sqlite3.connect(a.ocr)
    out = sqlite3.connect(a.salida)
    out.executescript("""
      DROP TABLE IF EXISTS voto_pleno;
      CREATE TABLE voto_pleno (fecha TEXT, hora TEXT, asunto TEXT, congresista TEXT,
        bancada TEXT, voto TEXT, fuente TEXT, votacion_id TEXT);
      CREATE INDEX IF NOT EXISTS ix_vp_cong ON voto_pleno(congresista);
      CREATE INDEX IF NOT EXISTS ix_vp_vot ON voto_pleno(votacion_id);
    """)
    canon = [r[0] for r in op.execute("SELECT DISTINCT congresista FROM votacion_congresista")]
    # Congresistas que entraron despues de marzo 2024 (accesitarios) no estan
    # en openpolitica: se suman los nombres OCR frecuentes que no cruzan.
    f = canonizador(canon)
    for nom, n in ocr.execute("SELECT congresista, COUNT(*) FROM voto GROUP BY 1 HAVING COUNT(*) >= 100"):
        if not f(nom):
            canon.append(nom if "," in nom else re.sub(r"^(\S+ \S+) ", r"\1, ", nom))
    f = canonizador(canon)

    # 1) openpolitica tal cual (nombres ya completos)
    out.executemany("INSERT INTO voto_pleno VALUES (?,?,?,?,?,?,?,?)", (
        (fe, ho, asu, c, g, r, "openpolitica", f"op:{fe}:{ho}") for fe, ho, asu, c, g, r in op.execute(
            "SELECT fecha, hora, asunto, congresista, grupo_parlamentario, resultado FROM votacion_congresista")))

    # 2) OCR: nombre canonico + bancada completada
    filas = ocr.execute("SELECT v.id, v.fecha, v.hora, v.asunto, w.congresista, w.bancada, w.voto "
                        "FROM votacion v JOIN voto w ON w.votacion_id = v.id").fetchall()
    sin_cruce = collections.Counter()
    norm = []
    for vid, fe, ho, asu, nom, ban, vot in filas:
        c = f(nom)
        if not c:
            sin_cruce[nom] += 1
        norm.append((vid, fe, ho, asu, c or nom, BANCADA_OCR.get(ban, ban), vot))
    por_sesion = collections.defaultdict(collections.Counter)
    por_mes = collections.defaultdict(collections.Counter)
    for vid, fe, ho, asu, c, ban, vot in norm:
        if ban:
            por_sesion[(c, fe)][ban] += 1
            por_mes[(c, fe[:7])][ban] += 1
    for vid, fe, ho, asu, c, ban, vot in norm:
        if not ban:
            cnt = por_sesion.get((c, fe)) or por_mes.get((c, fe[:7]))
            ban = cnt.most_common(1)[0][0] if cnt else None
        out.execute("INSERT INTO voto_pleno VALUES (?,?,?,?,?,?,?,?)", (fe, ho, asu, c, ban, vot, "ocr", f"ocr:{vid}"))
    out.commit()
    tot = len(filas)
    print(f"OCR: {tot} votos, sin cruce de nombre {sum(sin_cruce.values())} ({sum(sin_cruce.values())/tot:.2%})")
    print("nombres sin cruce mas frecuentes:", sin_cruce.most_common(15))
    print(out.execute("SELECT fuente, COUNT(DISTINCT votacion_id), COUNT(*), SUM(bancada IS NULL), "
                      "COUNT(DISTINCT congresista) FROM voto_pleno GROUP BY fuente").fetchall())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
