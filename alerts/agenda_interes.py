"""Aviso por Telegram de las agendas que traen algo para un cliente.

Sesiones de hoy y los proximos DIAS: comisiones PE (sesion_agenda_punto),
Pleno Senado/Diputados (PDF de agenda) y Asamblea EC (sesiones_ec). Cada
agenda se juzga UNA vez por version (hash del texto) con los perfiles de
los clientes del pais (notas.md); si no interesa, no se manda nada. Si la
agenda cambia, se vuelve a juzgar y solo se avisa lo nuevo.

Estado en cerebro.db (agenda_avisada). Corre en cerebro.yml.
Uso: python -m alerts.agenda_interes run [--no-enviar]"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import date, datetime, timedelta

from core import llm
from core.tiempo import LIMA

DIAS = 3
LOTE = 8
MAX_CHARS = 6000  # por agenda (el Pleno trae decenas de puntos)

SYSTEM = ("Eres analista de asuntos publicos. Lees agendas de sesiones parlamentarias y "
          "marcas SOLO los puntos que un cliente debe saber, segun su perfil: un proyecto "
          "de ley, dictamen, norma, invitado o tema que toca su negocio o sus reguladores. "
          "Tramite interno, mociones de saludo, nombramientos protocolares y temas ajenos "
          "no. Ante la duda, no. Español simple, frases cortas, sin dos puntos como conector.")

SCHEMA = {"type": "array", "items": {"type": "object", "properties": {
    "indice": {"type": "integer"},
    "puntos": {"type": "array", "items": {"type": "object", "properties": {
        "texto": {"type": "string"}, "clientes": {"type": "array", "items": {"type": "string"}}},
        "required": ["texto", "clientes"]}}},
    "required": ["indice", "puntos"]}}


def _ro(nombre: str) -> sqlite3.Connection | None:
    from core.db import db_path
    p = db_path(nombre)
    return sqlite3.connect(f"file:{p}?mode=ro", uri=True) if p.exists() else None


def sesiones(hoy: str, hasta: str) -> list[dict]:
    """[{clave, pais, nombre, fecha, hora, texto, hash}] con agenda cargada (core.legislativo)."""
    from core import legislativo
    d, h = date.fromisoformat(hoy), date.fromisoformat(hasta)
    out = [a for pais in legislativo.PAISES for a in legislativo.agendas(pais, d, h)]
    for s in out:
        s["texto"] = s["texto"][:MAX_CHARS]
        s["hash"] = hashlib.sha1(s["texto"].encode()).hexdigest()
    return out


def _perfiles(pais: str) -> str:
    from congreso_live.resumen_vivo import _perfiles
    return _perfiles(pais)


def juzgar(lote: list[dict], previos: dict[str, list[str]], generar=llm.generar) -> dict[int, list[dict]]:
    """{indice (1..n): [{texto, clientes}]} solo con lo de interes (y nuevo)."""
    pais = lote[0]["pais"]
    bloques = []
    for i, s in enumerate(lote, 1):
        ya = previos.get(s["clave"])
        bloques.append(f"[{i}] {s['nombre']} — {s['fecha']}\n{s['texto']}"
                       + ("\nYA AVISADO de esta sesion (no repetir, solo lo nuevo):\n- " + "\n- ".join(ya) if ya else ""))
    prompt = (f"Perfiles de los clientes:\n{_perfiles(pais)}\n\nAgendas:\n\n" + "\n\n".join(bloques)
              + "\n\nPara cada agenda responde {indice, puntos}. 'puntos' = solo lo que le toca a un "
                "cliente (vacio si nada): 'texto' es el punto resumido en una frase y 'clientes' los slugs.")
    out = {}
    for v in json.loads(generar(prompt, system=SYSTEM, modelo=llm.LITE, schema=SCHEMA) or "[]"):
        if isinstance(v, dict) and isinstance(v.get("indice"), int) and 1 <= v["indice"] <= len(lote):
            out[v["indice"]] = [p for p in v.get("puntos") or [] if str(p.get("texto", "")).strip()]
    return out


def mensaje(avisos: list[tuple[dict, list[dict], bool]]) -> str:
    partes = ["📅 *Agendas con temas de clientes*"]
    for s, puntos, actualizada in sorted(avisos, key=lambda a: (a[0]["fecha"], a[0]["hora"] or "")):
        f = datetime.fromisoformat(s["fecha"]).strftime("%d/%m")
        cab = f"*{s['nombre']}* · {f}" + (f" {s['hora']}" if s["hora"] else "") + (" (agenda actualizada)" if actualizada else "")
        lineas = [f"• {p['texto'].strip()}" + (f" ({', '.join(c.capitalize() for c in p['clientes'])})" if p["clientes"] else "")
                  for p in puntos]
        partes.append(cab + "\n" + "\n".join(lineas))
    return "\n\n".join(partes)


def _tabla(cerebro: sqlite3.Connection) -> None:
    cerebro.execute("CREATE TABLE IF NOT EXISTS agenda_avisada (clave TEXT PRIMARY KEY, hash TEXT, "
                    "puntos TEXT, juzgado_at TEXT)")


def run(enviar: bool = True, generar=llm.generar) -> str | None:
    from cerebro.embeddings import conectar
    cerebro = conectar()
    _tabla(cerebro)
    hoy = datetime.now(LIMA).date()
    todas = sesiones(hoy.isoformat(), (hoy + timedelta(days=DIAS)).isoformat())
    guardado = {c: (h, json.loads(p or "[]")) for c, h, p in cerebro.execute("SELECT clave, hash, puntos FROM agenda_avisada")}
    nuevas = [s for s in todas if guardado.get(s["clave"], (None,))[0] != s["hash"]]
    print(f"[agenda] {len(todas)} agendas, {len(nuevas)} nuevas o cambiadas")
    avisos = []
    for pais in ("PE", "EC"):
        cola = [s for s in nuevas if s["pais"] == pais]
        for i in range(0, len(cola), LOTE):
            lote = cola[i:i + LOTE]
            previos = {s["clave"]: guardado[s["clave"]][1] for s in lote if s["clave"] in guardado}
            try:
                veredictos = juzgar(lote, previos, generar)
            except Exception as e:  # cupo o JSON roto: la proxima corrida reintenta
                print(f"[agenda] {pais}: {e}")
                continue
            for j, s in enumerate(lote, 1):
                puntos = veredictos.get(j, [])
                if puntos:
                    avisos.append((s, puntos, s["clave"] in guardado))
                anteriores = previos.get(s["clave"], [])
                cerebro.execute("INSERT OR REPLACE INTO agenda_avisada VALUES (?,?,?,datetime('now'))",
                                (s["clave"], s["hash"], json.dumps(anteriores + [p["texto"] for p in puntos], ensure_ascii=False)))
            cerebro.commit()
    if not avisos:
        return None
    texto = mensaje(avisos)
    if enviar:
        from alerts.que_paso_hoy import partir
        from congreso_live.notify import enviar_whatsapp
        for trozo in partir(texto):
            enviar_whatsapp(trozo)
    return texto


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("accion", choices=["run"])
    ap.add_argument("--no-enviar", action="store_true")
    a = ap.parse_args()
    print(run(enviar=not a.no_enviar) or "[agenda] nada de interes")
