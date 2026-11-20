"""Resumen + ideas clave de cada sesion transcrita, leido por Gemma.

Reemplaza a la rutina de Claude "Resumir transcripciones" (apagada desde el 12/11/2026:
el sistema no debe depender de Claude). Corre dentro de posturas.yml, antes de las
posturas, para no pisar el limite por minuto de Gemma (es la misma clave).

Pendiente = sin resumen, o la transcripcion crecio desde el ultimo resumen (sesion en
vivo), o un resumen viejo que todavia dice "en curso". Sesiones largas: cada trozo se
lee aparte (notas) y una ultima llamada arma el resumen con todas las notas.
Guarda en data/transcripciones_resumenes.json (resumenes_store); el workflow hace el
commit, porque el archivo pasa el limite de 1 MB de la API de GitHub.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone

from congreso_live.resumenes_store import _local_path, guardar_resumen
from consultas.posturas import _turno, trozos
from core import llm

DESDE = "2026-07-26"  # nada anterior al periodo actual queda pendiente

_ESQ_NOTAS = {"type": "array", "items": {"type": "string"}}
_ESQ = {"type": "object", "properties": {
    "resumen": {"type": "string"}, "ideas_clave": {"type": "array", "items": {"type": "string"}},
    "agenda_cumplida": {"type": "string"}}, "required": ["resumen", "ideas_clave", "agenda_cumplida"]}

_REGLAS = """Escribe en español con tildes, tono neutro e informativo. No inventes nada que no este en el texto.
Los nombres propios vienen de una transcripcion automatica: si un nombre no se entiende, describe el cargo
("un diputado", "el ministro de Salud") en vez de adivinarlo. Ignora el pase de lista salvo que no hubo quorum.
{lugar}"""

NOTAS = """Parte {n} de {total} de la transcripcion automatica de: {titulo} ({fecha}).
Saca en una lista los hechos concretos de esta parte: quien expuso y que dijo (cifras, fechas, compromisos),
que proyecto se sustento o debatio (numero y de que trata), quien apoyo o cuestiono y que pidio, y cada
votacion con su resultado. Una oracion por hecho. Nada vago como "se hablo de salud".
{reglas}

TRANSCRIPCION
{texto}"""

FINAL = """{base}: {titulo} ({fecha}).
Devuelve:
- resumen: 2 o 3 oraciones que digan de que trato la sesion (quien expuso, sobre que, que se decidio).
- ideas_clave: de 4 a 7 hechos CONCRETOS, cada uno legible solo: votaciones con resultado, proyectos con
  numero, declaraciones de ministros o funcionarios con cifras, compromisos con fecha. Prioriza votos y decisiones.
  Cada proyecto de ley que se sustento o debatio va en su propia idea: numero, autor y de que trata.
  Si un nombre, empresa o cifra suena raro o mal transcrito, dejalo fuera antes que arriesgar un error.
- agenda_cumplida: {agenda_txt}
{reglas}

{material}"""

_EC = ("Es la Asamblea Nacional del Ecuador: usa asambleista, Asamblea Nacional, primer/segundo debate; "
       "nunca congresista ni Congreso.")
_ENTREVISTA = ("No es una sesion legislativa: es una entrevista o declaracion en medios. En el resumen di quien "
               "habla, en que medio (sale del titulo) y de que temas; en las ideas, anuncios, cifras, posiciones "
               "sobre proyectos o normas y compromisos con fecha.")


def _gemma(prompt: str, schema) -> str:
    """Una llamada por minuto como mucho (igual que posturas). La clave la comparten otros
    procesos (cerebro, la app): si el cupo por minuto ya se fue, espera un minuto y reintenta."""
    for intento in range(4):
        _turno()
        try:
            return llm.generar(prompt, modelo=llm.GEMMA, json=True, schema=schema, respaldo=False)
        except Exception as e:
            if intento == 3 or llm._tipo_error(e) != "pasajero":
                raise
            time.sleep(60)


def agenda(c: sqlite3.Connection, vid: str, tipo: str, fecha: str) -> list[str]:
    """Puntos agendados de la sesion: comisiones por el link del video, Pleno por la fecha
    (si hay exactamente un Pleno ese dia). [] si no se encuentra; nunca se adivina."""
    if tipo.endswith("(EC)") or tipo.startswith("Entrevista:"):
        return []
    s = c.execute("SELECT id_sesion FROM sesiones WHERE link_video LIKE ?", (f"%{vid}%",)).fetchone()
    if s:
        return [r[0] for r in c.execute("SELECT descripcion_texto FROM sesion_agenda_punto WHERE id_sesion=? "
                                        "ORDER BY orden", (s[0],)) if r[0]]
    plenos = c.execute("SELECT cod_agenda FROM pleno_sesiones WHERE fecha_sesion=?", (fecha,)).fetchall()
    if tipo.startswith("Pleno") and len(plenos) == 1:
        return [r[0] for r in c.execute("SELECT COALESCE(des_resumen, des_tema_texto) FROM pleno_tema "
                                        "WHERE cod_agenda=? ORDER BY num_tema", (plenos[0][0],)) if r[0]]
    return []


def resumir(titulo: str, tipo: str, fecha: str, texto: str, puntos: list[str], generar=_gemma) -> dict:
    ec = tipo.endswith("(EC)")
    reglas = _REGLAS.format(lugar=_ENTREVISTA if tipo.startswith("Entrevista:") else _EC if ec else "")
    partes = trozos(texto)
    if len(partes) == 1:
        material = "TRANSCRIPCION\n" + texto
    else:
        notas = []
        for n, t in enumerate(partes, 1):
            notas += json.loads(generar(NOTAS.format(n=n, total=len(partes), titulo=titulo, fecha=fecha,
                                                     reglas=reglas, texto=t), _ESQ_NOTAS) or "[]")
        material = "NOTAS DE TODA LA SESION, EN ORDEN\n" + "\n".join(f"- {x}" for x in notas)
    agenda_txt = ("1 o 2 oraciones sobre cuanto de esta agenda se trato realmente:\n"
                  + "\n".join(f"  {i}. {p[:300]}" for i, p in enumerate(puntos, 1))) if puntos else 'deja "".'
    base = "Resumen de la entrevista" if tipo.startswith("Entrevista:") else "Resumen de la sesion"
    r = json.loads(generar(FINAL.format(base=base, titulo=titulo, fecha=fecha, agenda_txt=agenda_txt,
                                        reglas=reglas, material=material), _ESQ))
    return {"resumen": r["resumen"].strip(), "ideas_clave": [i.strip() for i in r["ideas_clave"] if i.strip()][:7],
            "agenda_cumplida": (r.get("agenda_cumplida") or "").strip() or None}


def pendientes(c: sqlite3.Connection, hechos: dict) -> list[tuple]:
    """Entrevistas primero (alguien las pidio desde la app), despues lo mas nuevo."""
    hace3h = (datetime.now(timezone.utc) - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = []
    for vid, tipo, titulo, fecha, dur in c.execute(
            "SELECT video_id, tipo, titulo, fecha, duracion_seg FROM sesiones_transcripciones "
            "WHERE fecha >= ? AND length(texto) > 1500", (DESDE,)):
        r = hechos.get(vid)
        if (not r or r.get("duracion_seg") is None or (dur or 0) > r["duracion_seg"]
                or ("en curso" in str(r.get("resumen")) and (r.get("generated_at") or "") < hace3h)):
            out.append((vid, tipo or "", titulo or "", fecha, dur))
    out.sort(key=lambda x: x[3], reverse=True)
    return sorted(out, key=lambda x: not x[1].startswith("Entrevista:"))  # sort estable: fecha queda desc


def correr(db: str, minutos: float) -> int:
    hechos = {r["video_id"]: r for r in json.loads(_local_path().read_text("utf-8"))} if _local_path().exists() else {}
    c = sqlite3.connect(db)
    faltan = pendientes(c, hechos)
    print(f"[resumir] {len(faltan)} sesiones pendientes", flush=True)
    fin, hechas = time.time() + minutos * 60, 0
    for vid, tipo, titulo, fecha, dur in faltan:
        if time.time() > fin:
            break
        texto = c.execute("SELECT texto FROM sesiones_transcripciones WHERE video_id=?", (vid,)).fetchone()[0]
        try:
            r = resumir(titulo, tipo, fecha, texto, agenda(c, vid, tipo, fecha))
        except Exception as e:  # sin cupo o JSON roto: queda para la proxima corrida
            print(f"[resumir] {vid}: {str(e)[:150]}", flush=True)
            continue
        guardar_resumen(video_id=vid, duracion_seg=dur, **r)
        hechas += 1
        print(f"[resumir] {vid} {fecha} {titulo[:60]}", flush=True)
    return hechas


if __name__ == "__main__":
    falso = lambda p, s: json.dumps(["Hecho A.", "Hecho B."]) if s is _ESQ_NOTAS else json.dumps(
        {"resumen": "Se vio X.", "ideas_clave": ["Uno", " ", "Dos"], "agenda_cumplida": ""})
    r = resumir("t", "Comision: Salud", "2026-11-17", "palabra " * 12_000, [], falso)
    assert r == {"resumen": "Se vio X.", "ideas_clave": ["Uno", "Dos"], "agenda_cumplida": None}, r
    m = sqlite3.connect(":memory:")
    m.execute("CREATE TABLE sesiones_transcripciones (video_id, tipo, titulo, fecha, duracion_seg, texto)")
    m.executemany("INSERT INTO sesiones_transcripciones VALUES (?,?,?,?,?,?)", [
        ("a", "Comision: X", "", "2026-11-10", 100, "x" * 2000), ("b", "Pleno", "", "2026-11-18", 100, "x" * 2000),
        ("c", "Entrevista: Y", "", "2026-11-01", 50, "x" * 2000), ("d", "Pleno", "", "2026-11-19", 100, "x" * 2000),
        ("e", "Pleno", "", "2026-11-19", 300, "x" * 2000), ("f", "Pleno", "", "2026-11-19", 100, "corto")])
    hechos = {"d": {"duracion_seg": 100, "resumen": "ok"}, "e": {"duracion_seg": 200, "resumen": "ok"}}
    assert [x[0] for x in pendientes(m, hechos)] == ["c", "e", "b", "a"], pendientes(m, hechos)
    if "correr" in sys.argv:
        print(f"[resumir] {correr('proyectos.db', float(sys.argv[sys.argv.index('correr') + 1]))} resumidas")
