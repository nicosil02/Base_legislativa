"""¿Dos noticias de portales distintos cuentan el mismo hecho?

1. Candidatos: los vectores del cerebro proponen pares desde 0.72 de
   similitud (mismo pais, distinto portal, fechas a 3 dias o menos).
2. Juez: un cross-encoder propio, afinado con las etiquetas de Gemini; hasta
   que exista (o si no le gana al umbral de vectores), Gemini flash-lite.
   El cross-encoder lee las dos noticias juntas, como el modelo MRPC de la
   sesion 09 de la clase, en vez de comparar dos vectores sueltos.
3. Los veredictos van a la tabla `mismo_hecho` de cerebro.db; la pagina de
   Noticias junta las tarjetas con eso (noticias/historias.py).

    python -m noticias.mismo_hecho etiquetar --dias 30 --max 1500   # Gemini etiqueta
    python -m noticias.mismo_hecho entrenar                         # afina y evalua
    python -m noticias.mismo_hecho run                              # lo nuevo (cerebro.yml)
"""
from __future__ import annotations

import argparse
import html
import itertools
import json
import random
import re
import sqlite3
import time
from datetime import date, datetime, timedelta, timezone

from core import llm
from core.db import ROOT
from core.text import norm

UMBRAL_CANDIDATO = 0.72
MAX_DIAS_ENTRE = 3
LOTE_GEMINI = 30
PAUSA_GEMINI = 4.5    # flash-lite gratis: 15 pedidos por minuto
MAX_PARES_GEMINI = 300   # por corrida diaria sin modelo propio (10 llamadas)
MAX_PARES_MODELO = 3000  # ~5 min en CPU
MODELO_DIR = ROOT / "data" / "mismo_hecho_modelo"
BASE = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"   # cross-encoder multilingue (es incluido)
_NUM_NORMA = re.compile(r"\b\d{1,6}-\d{4}(?:-[A-Z]+)?\b")
_TAGS = re.compile(r"<[^>]+>")

SYSTEM = ("Decides si dos noticias cuentan el MISMO hecho concreto: el mismo acontecimiento, "
          "declaracion, decision o norma, aunque lo digan con otras palabras o una agregue "
          "detalles. Mismo tema pero hechos distintos (dos normas distintas, dos sesiones, el "
          "clima de dos ciudades, una noticia y su consecuencia dias despues) NO es el mismo hecho.")
SCHEMA = {"type": "array", "items": {"type": "object", "properties": {
    "indice": {"type": "integer"}, "mismo": {"type": "boolean"}}, "required": ["indice", "mismo"]}}


def asegurar_tabla(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS mismo_hecho (
        a INTEGER, b INTEGER, igual INTEGER, juez TEXT, prob REAL, sim REAL, evaluado_at TEXT,
        PRIMARY KEY (a, b))""")


def texto(titulo: str | None, resumen: str | None) -> str:
    r = html.unescape(_TAGS.sub(" ", resumen or ""))
    r = re.sub(r"\s+", " ", r).strip()
    t = html.unescape(titulo or "").strip()
    return t if not r or norm(r).startswith(norm(t)[:40]) else f"{t}. {r[:300]}"


def _noticias(conn: sqlite3.Connection, desde: str, hasta: str | None = None) -> dict[int, dict]:
    sql = """SELECT n.id, n.titulo, n.resumen, date(COALESCE(n.fecha_pub, n.first_seen_at)), f.nombre, f.pais
             FROM noticias n JOIN noticias_fuentes f ON f.id = n.fuente_id
             WHERE f.activa = 1 AND n.first_seen_at >= ?""" + (" AND n.first_seen_at < ?" if hasta else "")
    filas = conn.execute(sql, (desde, hasta) if hasta else (desde,)).fetchall()
    return {r[0]: {"id": r[0], "titulo": r[1], "texto": texto(r[1], r[2]), "fecha": r[3],
                   "fuente": r[4], "pais": r[5]} for r in filas}


def candidatos(cerebro: sqlite3.Connection, noticias: sqlite3.Connection, desde: str,
               hasta: str | None = None) -> list[dict]:
    """Pares (a < b) que vale la pena juzgar y que todavia no tienen veredicto."""
    import numpy as np
    from cerebro.embeddings import vectores_noticias
    info = _noticias(noticias, desde, hasta)
    vec = vectores_noticias(info, cerebro)
    ya = {(r[0], r[1]) for r in cerebro.execute("SELECT a, b FROM mismo_hecho")}
    out = []
    for pais in ("PE", "EC"):
        ids = [i for i in vec if info[i]["pais"] == pais]
        if len(ids) < 2:
            continue
        m = np.stack([vec[i] for i in ids])
        sims = m @ m.T
        for x, y in zip(*np.nonzero(np.triu(sims, 1) >= UMBRAL_CANDIDATO)):
            a, b = sorted((ids[x], ids[y]))
            na, nb = info[a], info[b]
            if na["fuente"] == nb["fuente"] or (a, b) in ya:
                continue
            if norm(na["titulo"])[:80] == norm(nb["titulo"])[:80]:
                continue  # titulo identico: la pagina ya lo deduplica
            try:
                if abs((date.fromisoformat(na["fecha"]) - date.fromisoformat(nb["fecha"])).days) > MAX_DIAS_ENTRE:
                    continue
            except (TypeError, ValueError):
                continue
            out.append({"a": a, "b": b, "sim": float(sims[x, y]), "ta": na["texto"], "tb": nb["texto"]})
    return out


def juzgar_gemini(pares: list[dict], generar=llm.generar) -> list[bool | None]:
    """Un veredicto por par (None si Gemini no lo devolvio)."""
    out: list[bool | None] = []
    for k in range(0, len(pares), LOTE_GEMINI):
        lote = pares[k:k + LOTE_GEMINI]
        lista = "\n\n".join(f"[{i}]\nA: {p['ta']}\nB: {p['tb']}" for i, p in enumerate(lote, 1))
        if k and generar is llm.generar:
            time.sleep(PAUSA_GEMINI)
        for intento in range(4):
            try:
                resp = generar(f"Para cada par responde {{indice, mismo}}.\n\n{lista}",
                               system=SYSTEM, modelo=llm.LITE, schema=SCHEMA)
                break
            except Exception as e:  # 429 por minuto: esperar y reintentar; el diario corta
                if "429" not in str(e) or "PerDay" in str(e) or intento == 3:
                    raise
                time.sleep(30)
        v = {}
        for x in json.loads(resp or "[]"):
            if isinstance(x, dict) and isinstance(x.get("indice"), int):
                v[x["indice"]] = bool(x.get("mismo"))
        out += [v.get(i) for i in range(1, len(lote) + 1)]
    return out


def guardar(cerebro: sqlite3.Connection, pares: list[dict], veredictos: list, juez: str,
            probs: list[float] | None = None) -> int:
    ahora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    filas = [(p["a"], p["b"], int(v), juez, probs[i] if probs else None, p["sim"], ahora)
             for i, (p, v) in enumerate(zip(pares, veredictos)) if v is not None]
    cerebro.executemany("INSERT OR REPLACE INTO mismo_hecho VALUES (?,?,?,?,?,?,?)", filas)
    cerebro.commit()
    return len(filas)


# ------------------------------------------------------------------ modelo propio

def importar_humanos(cerebro: sqlite3.Connection) -> int:
    """Las noticias juntadas con "Combinar" en la pagina (data/noticias_combinadas.json)
    son el mismo hecho segun una persona: le ganan a Gemini y al modelo."""
    from noticias.feedback_store import COMBINADAS_PATH
    p = ROOT / COMBINADAS_PATH
    grupos = json.loads(p.read_text(encoding="utf-8")) if p.exists() else []
    ahora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    filas = [(a, b, 1, "humano", None, None, ahora)
             for g in grupos for a, b in itertools.combinations(sorted(g["ids"]), 2)]
    cerebro.executemany("INSERT OR REPLACE INTO mismo_hecho VALUES (?,?,?,?,?,?,?)", filas)
    cerebro.commit()
    return len(filas)


def _dispositivo():
    import torch
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def _probs(modelo, tok, pares: list[tuple[str, str]], lote: int = 32) -> list[float]:
    import torch
    modelo.eval()
    out = []
    with torch.no_grad():
        for k in range(0, len(pares), lote):
            a, b = zip(*pares[k:k + lote])
            x = tok(list(a), list(b), truncation=True, max_length=256, padding=True, return_tensors="pt")
            out += torch.sigmoid(modelo(**x.to(_dispositivo())).logits.squeeze(-1)).tolist()
    return out


def _metricas(reales: list[int], pred: list[int]) -> dict:
    tp = sum(r and p for r, p in zip(reales, pred))
    fp = sum((not r) and p for r, p in zip(reales, pred))
    fn = sum(r and (not p) for r, p in zip(reales, pred))
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    return {"precision": round(prec, 3), "recall": round(rec, 3),
            "f1": round(2 * prec * rec / (prec + rec), 3) if prec + rec else 0.0,
            "exactitud": round(sum(r == p for r, p in zip(reales, pred)) / len(reales), 3)}


def entrenar(cerebro: sqlite3.Connection, noticias: sqlite3.Connection, epocas: int = 3,
             semilla: int = 13) -> dict:
    """Afina BASE con los pares que etiqueto Gemini, evalua contra el 20% que
    no vio (y contra el umbral de vectores de hoy) y guarda en MODELO_DIR."""
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer
    from noticias.historias import UMBRAL_NOTICIAS

    importar_humanos(cerebro)
    filas = cerebro.execute(
        "SELECT a, b, igual, sim FROM mismo_hecho WHERE juez IN ('gemini', 'humano')").fetchall()
    ids = {x for r in filas for x in r[:2]}
    txt = {i: texto(t, r) for i, t, r in noticias.execute(
        f"SELECT id, titulo, resumen FROM noticias WHERE id IN ({','.join(map(str, ids))})")} if ids else {}
    datos = [(txt[a], txt[b], y, s) for a, b, y, s in filas if a in txt and b in txt]
    random.Random(semilla).shuffle(datos)
    corte = int(len(datos) * 0.8)
    train, test = datos[:corte], datos[corte:]
    if len(train) < 100 or not test:
        raise SystemExit(f"[mismo_hecho] pocas etiquetas ({len(datos)}): correr etiquetar primero")

    torch.manual_seed(semilla)
    tok = AutoTokenizer.from_pretrained(BASE)
    modelo = AutoModelForSequenceClassification.from_pretrained(BASE, num_labels=1).to(_dispositivo())
    opt = torch.optim.AdamW(modelo.parameters(), lr=2e-5)
    perdida = torch.nn.BCEWithLogitsLoss()
    for ep in range(epocas):
        modelo.train()
        random.Random(semilla + ep).shuffle(train)
        total = 0.0
        for k in range(0, len(train), 16):
            a, b, y, _ = zip(*train[k:k + 16])
            x = tok(list(a), list(b), truncation=True, max_length=256, padding=True, return_tensors="pt")
            loss = perdida(modelo(**x.to(_dispositivo())).logits.squeeze(-1),
                           torch.tensor(y, dtype=torch.float32, device=_dispositivo()))
            loss.backward()
            opt.step()
            opt.zero_grad()
            total += loss.item() * len(y)
        print(f"[mismo_hecho] epoca {ep + 1}: perdida {total / len(train):.4f}")

    reales = [y for *_, y, _ in test]
    probs = _probs(modelo, tok, [(a, b) for a, b, *_ in test])
    res = {"entrenado": datetime.now(timezone.utc).isoformat(timespec="seconds"), "base": BASE,
           "pares_train": len(train), "pares_test": len(test),
           "positivos_test": sum(reales),
           "modelo": _metricas(reales, [int(p >= 0.5) for p in probs]),
           "umbral_vectores": _metricas(reales, [int(s >= UMBRAL_NOTICIAS) for *_, s in test])}
    MODELO_DIR.mkdir(parents=True, exist_ok=True)
    modelo.to(torch.float16).save_pretrained(MODELO_DIR)   # la mitad de peso; se lee en float32
    tok.save_pretrained(MODELO_DIR)
    # lo que juzgo el modelo anterior se vuelve a juzgar con este
    cerebro.execute("DELETE FROM mismo_hecho WHERE juez = 'modelo'")
    cerebro.commit()
    (MODELO_DIR / "metricas.json").write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(res, indent=2, ensure_ascii=False))
    return res


def modelo_util() -> bool:
    """Hay modelo propio y le gana (F1) al umbral de vectores en su prueba."""
    m = MODELO_DIR / "metricas.json"
    if not m.exists():
        return False
    r = json.loads(m.read_text(encoding="utf-8"))
    return r["modelo"]["f1"] > r["umbral_vectores"]["f1"]


def juzgar_modelo(pares: list[dict]) -> tuple[list[bool], list[float]]:
    from transformers import AutoModelForSequenceClassification, AutoTokenizer
    tok = AutoTokenizer.from_pretrained(MODELO_DIR)
    import torch
    modelo = AutoModelForSequenceClassification.from_pretrained(
        MODELO_DIR, dtype=torch.float32).to(_dispositivo())
    probs = _probs(modelo, tok, [(p["ta"], p["tb"]) for p in pares])
    return [p >= 0.5 for p in probs], probs


# ------------------------------------------------------------------ comandos

def _conexiones():
    from cerebro.embeddings import _db, conectar
    pe = _db("proyectos.db")
    if not pe:
        raise SystemExit("[mismo_hecho] falta proyectos.db")
    cerebro = conectar()
    asegurar_tabla(cerebro)
    return cerebro, sqlite3.connect(f"file:{pe}?mode=ro", uri=True)


def _iso(dias: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=dias)).strftime("%Y-%m-%dT%H:%M:%S")


def etiquetar(dias: int, maximo: int) -> int:
    """Muestra pares de los ultimos `dias` (de a 3 dias, para no armar una
    matriz gigante) repartidos en toda la franja de similitud, y que Gemini
    los juzgue."""
    cerebro, noticias = _conexiones()
    pares = []
    for d in range(dias, 0, -MAX_DIAS_ENTRE):
        pares += candidatos(cerebro, noticias, _iso(d), _iso(max(d - MAX_DIAS_ENTRE, 0)))
    random.Random(7).shuffle(pares)
    # mitad altos (>= 0.82) y mitad zona dudosa, para que el modelo vea las dos
    altos = [p for p in pares if p["sim"] >= 0.82][:maximo // 2]
    medios = [p for p in pares if p["sim"] < 0.82][:maximo - len(altos)]
    pares = altos + medios
    random.Random(8).shuffle(pares)   # si el cupo corta a mitad, igual quedan de las dos franjas
    print(f"[mismo_hecho] {len(pares)} pares a etiquetar ({len(altos)} >= 0.82)")
    hechos = 0
    for k in range(0, len(pares), LOTE_GEMINI * 5):
        lote = pares[k:k + LOTE_GEMINI * 5]
        try:
            hechos += guardar(cerebro, lote, juzgar_gemini(lote), "gemini")
        except Exception as e:  # cupo: lo guardado queda, la proxima corrida sigue
            print(f"[mismo_hecho] Gemini fallo: {e}")
            break
    print(f"[mismo_hecho] {hechos} etiquetas guardadas")
    return hechos


def run(dias: float = 2) -> int:
    cerebro, noticias = _conexiones()
    print(f"[mismo_hecho] {importar_humanos(cerebro)} pares humanos (Combinar)")
    pares = candidatos(cerebro, noticias, _iso(dias))
    if not pares:
        print("[mismo_hecho] sin pares nuevos")
        return 0
    juez = "modelo" if modelo_util() else "gemini"
    pares = sorted(pares, key=lambda p: -p["sim"])[:MAX_PARES_MODELO if juez == "modelo" else MAX_PARES_GEMINI]
    if juez == "modelo":
        v, probs = juzgar_modelo(pares)
        n = guardar(cerebro, pares, v, juez, probs)
    else:
        n = guardar(cerebro, pares, juzgar_gemini(pares), juez)
    print(f"[mismo_hecho] {n} pares juzgados ({juez})")
    return n


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("etiquetar")
    e.add_argument("--dias", type=int, default=30)
    e.add_argument("--max", type=int, default=1500)
    t = sub.add_parser("entrenar")
    t.add_argument("--epocas", type=int, default=3)
    sub.add_parser("run")
    args = ap.parse_args()
    if args.cmd == "etiquetar":
        etiquetar(args.dias, args.max)
    elif args.cmd == "entrenar":
        cerebro, noticias = _conexiones()
        entrenar(cerebro, noticias, args.epocas)
    else:
        run()
