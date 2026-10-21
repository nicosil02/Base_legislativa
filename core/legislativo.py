"""Contrato comun por pais: proyectos de ley, cambios de estado y agendas con
las mismas columnas, vengan de la base que vengan.

Peru (proyectos.db) y Ecuador (proyectos_ec.db) guardan lo mismo con tablas
y nombres distintos. El motor (avisos, alta de clientes, cerebro) lee de aca,
no de las tablas: un pais nuevo es escribir sus tres funciones y sumarlo a
PAISES, sin tocar a quien las usa.

  proyectos(pais, desde)  [{pais, numero, titulo, categoria, estado, fecha, url}]
  cambios(pais, desde)    [{pais, numero, titulo, categoria, fecha, campo, valor, url}]
  agendas(pais, desde, hasta)  [{clave, pais, nombre, fecha, hora, texto}]

`desde`/`hasta` son datetimes con zona (o fechas para agendas); cada pais
los pasa a como guarda sus fechas (PE en hora de Lima, EC changed_at en UTC).
`categoria` es la de scraper/categorias (la que piden los clientes en
categorias_pl)."""
from __future__ import annotations

import gzip
import shutil
import sqlite3
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

from core.db import ROOT, db_path
from core.tiempo import LIMA

BASES = {"PE": "proyectos.db", "EC": "proyectos_ec.db"}


def conectar(pais: str) -> sqlite3.Connection | None:
    """Solo lectura; None si no hay base. Sin la base pero con su .gz en
    data/ (PC local tras git pull), la abre desde un temporal."""
    p = db_path(BASES[pais])
    if not p.exists():
        gz = ROOT / "data" / f"{BASES[pais]}.gz"
        if not gz.exists():
            return None
        p = Path(tempfile.gettempdir()) / f"legislativo_{BASES[pais]}"
        if not p.exists() or p.stat().st_mtime < gz.stat().st_mtime:
            with gzip.open(gz) as f, open(p, "wb") as out:
                shutil.copyfileobj(f, out)
    c = sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    return c


def _lima(d: datetime) -> str:
    return d.astimezone(LIMA).strftime("%Y-%m-%dT%H:%M:%S")


def _utc(d: datetime) -> str:
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


# ------------------------------------------------------------------ Peru
def _proyectos_pe(c: sqlite3.Connection, desde: datetime) -> list[dict]:
    return [{"pais": "PE", "numero": str(r["pley_num"]), "titulo": r["titulo"], "categoria": r["cat"],
             "estado": r["estado"], "fecha": (r["fec_presentacion"] or "")[:10], "url": r["url_portal"]}
            for r in c.execute(
                "SELECT pley_num, titulo, tema AS cat, estado, fec_presentacion, "
                "url_portal FROM proyectos WHERE fec_presentacion >= ? ORDER BY fec_presentacion DESC",
                (_lima(desde)[:10],))]


def _cambios_pe(c: sqlite3.Connection, desde: datetime) -> list[dict]:
    return [{"pais": "PE", "numero": str(r["proyecto_ley"]), "titulo": r["titulo"], "categoria": r["cat"],
             "fecha": (r["fecha"] or "")[:10], "campo": "estado",
             "valor": f"{r['estado']} {r['comisiones'] or ''}".strip(), "url": r["url_portal"]}
            for r in c.execute(
                """SELECT p.proyecto_ley, p.titulo, p.tema AS cat, p.url_portal,
                          s.estado, s.comisiones, s.fecha
                   FROM seguimientos s JOIN proyectos p USING (per_par_id, cod_tipo_parl, pley_num)
                   WHERE s.fecha >= ? ORDER BY s.fecha DESC""", (_lima(desde),))]


def _agendas_pe(c: sqlite3.Connection, desde: date, hasta: date) -> list[dict]:
    from congreso_live.agenda_preview import agenda_texto
    d, h = desde.isoformat(), hasta.isoformat()
    out = []
    for s in c.execute(
            "SELECT id_sesion, nombre_comision, camara, fecha, hora_inicio FROM sesiones "
            "WHERE fecha BETWEEN ? AND ? AND UPPER(COALESCE(estado,'')) = 'CONVOCADA'", (d, h)).fetchall():
        puntos = [t for (t,) in c.execute(
            "SELECT descripcion_texto FROM sesion_agenda_punto WHERE id_sesion = ? ORDER BY orden",
            (s["id_sesion"],)) if t]
        if puntos:
            out.append({"clave": f"pe:{s['id_sesion']}", "pais": "PE", "fecha": s["fecha"],
                        "hora": s["hora_inicio"],
                        "nombre": s["nombre_comision"] + (f" ({s['camara']})" if s["camara"] else ""),
                        "texto": "\n".join(f"- {p}" for p in puntos)})
    for camara, fecha in c.execute(
            "SELECT DISTINCT camara, fecha FROM pleno_agenda_pdf WHERE fecha BETWEEN ? AND ? "
            "AND upper(pdf_url) LIKE '%AGENDA%'", (d, h)).fetchall():
        texto = agenda_texto(f"Pleno: {camara.capitalize()}", "", fecha)
        if texto:
            out.append({"clave": f"pleno:{camara}:{fecha}", "pais": "PE", "fecha": fecha, "hora": None,
                        "nombre": "Pleno del Senado" if camara == "senado" else "Pleno de la Cámara de Diputados",
                        "texto": texto})
    return out


# ------------------------------------------------------------------ Ecuador
def _categoria_ec(r) -> str:
    # tema del scraper EC; si falta, la misma clasificacion que Peru.
    if r["cat"]:
        return r["cat"]
    from scraper.categorias import classify
    return classify(r["titulo"])


def _proyectos_ec(c: sqlite3.Connection, desde: datetime) -> list[dict]:
    return [{"pais": "EC", "numero": str(r["n_tramite"]), "titulo": r["titulo"], "categoria": _categoria_ec(r),
             "estado": r["estado"], "fecha": (r["fec_presentacion"] or "")[:10], "url": r["url_portal"]}
            for r in c.execute(
                "SELECT n_tramite, titulo, tema AS cat, estado, fec_presentacion, "
                "url_portal FROM proyectos WHERE fec_presentacion >= ? ORDER BY fec_presentacion DESC",
                (_lima(desde)[:10],))]


def _cambios_ec(c: sqlite3.Connection, desde: datetime) -> list[dict]:
    return [{"pais": "EC", "numero": str(r["n_tramite"]), "titulo": r["titulo"], "categoria": _categoria_ec(r),
             "fecha": (r["changed_at"] or "")[:10], "campo": "comision" if r["campo"] == "comision_asignada" else "estado",
             "valor": r["valor_despues"], "url": r["url_portal"]}
            for r in c.execute(
                """SELECT h.n_tramite, p.titulo, p.tema AS cat, p.url_portal,
                          h.campo, h.valor_despues, h.changed_at
                   FROM historial_cambios h JOIN proyectos p USING (n_tramite)
                   WHERE h.changed_at >= ? AND h.campo IN ('estado', 'comision_asignada')
                   ORDER BY h.changed_at DESC""", (_utc(desde),))]


def _agendas_ec(c: sqlite3.Connection, desde: date, hasta: date) -> list[dict]:
    return [{"clave": f"ec:{r['uid']}", "pais": "EC", "fecha": r["fecha"], "hora": r["hora_inicio"],
             "nombre": f"{'Pleno' if r['nombre_comision'] == 'Pleno' else 'Comisión de ' + (r['nombre_comision'] or '?')} (Asamblea EC)",
             "texto": r["descripcion"]}
            for r in c.execute(
                "SELECT uid, nombre_comision, fecha, hora_inicio, descripcion FROM sesiones_ec "
                "WHERE fecha BETWEEN ? AND ? AND COALESCE(status,'') != 'CANCELLED'",
                (desde.isoformat(), hasta.isoformat()))
            if (r["descripcion"] or "").strip()]


PAISES = {
    "PE": {"proyectos": _proyectos_pe, "cambios": _cambios_pe, "agendas": _agendas_pe},
    "EC": {"proyectos": _proyectos_ec, "cambios": _cambios_ec, "agendas": _agendas_ec},
}


def _correr(pais: str, que: str, *args) -> list[dict]:
    c = conectar(pais)
    if c is None:
        return []
    try:
        return PAISES[pais][que](c, *args)
    finally:
        c.close()


def proyectos(pais: str, desde: datetime) -> list[dict]:
    return _correr(pais, "proyectos", desde)


def cambios(pais: str, desde: datetime) -> list[dict]:
    return _correr(pais, "cambios", desde)


def agendas(pais: str, desde: date, hasta: date) -> list[dict]:
    return _correr(pais, "agendas", desde, hasta)
