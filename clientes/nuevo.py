"""Alta de un cliente nuevo sin tocar codigo: crear la ficha y probarla.

  python -m clientes.nuevo crear <slug> --nombre "Nombre" --paises PE,EC
  python -m clientes.nuevo probar <slug> [--dias 30] [--muestra 15]

`crear` deja clientes/<slug>/cliente.json (campos en clientes/config.py) y
notas.md (el perfil que leen los jueces de Gemini: resumen en vivo, agendas,
TV, alerta final). Se llenan a mano o pidiendoselo a Claude con el bluebook.

`probar` es la calibracion: corre la ficha contra los ultimos dias de la
base y muestra que le habria llegado (noticias y PL), con ejemplos para ver
el ruido. Se ajusta la ficha y se vuelve a probar hasta que cierre.

Despues: `python -m clientes.privado cerrar` (necesita CLIENTES_CLAVE) y
commit de los .cifrado; el texto plano no se sube."""
from __future__ import annotations

import argparse
import gzip
import json
import shutil
import sqlite3
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from clientes import config

FICHA = {
    "nombre": "",
    "paises": [],
    "temas_noticias": [],
    "temas_propios": {},
    "categorias_pl": [],
    "categorias_fuente": [],
    "instituciones": [],
    "fuentes_con_perfil_estricto": [],
    "palabras_clave": [],
    "palabras_norma": [],
    "matriz_pl": {},
    "por_que": [],
}

NOTAS = """# {nombre}

## Negocio
Que hace la empresa y que lineas de negocio tiene en cada pais.

## Temas de interes
Por pais. Lo que SI quiere saber (proyectos, normas, reguladores, actores).

## Lo que NO quiere recibir
Ruido conocido: temas parecidos que no le sirven.

## Actores
Reguladores, ministerios, congresistas, gremios y competidores a vigilar.

## Proyectos y normas en seguimiento
Numero, nombre y por que le importa.

## Formato y canal de alertas
WhatsApp / correo, a quien, con que frecuencia.
"""


def crear(slug: str, nombre: str, paises: list[str]) -> Path:
    carpeta = config.CARPETA / slug
    if (carpeta / "cliente.json").exists():
        raise SystemExit(f"{carpeta / 'cliente.json'} ya existe; no lo piso.")
    carpeta.mkdir(parents=True, exist_ok=True)
    ficha = {**FICHA, "nombre": nombre, "paises": paises}
    (carpeta / "cliente.json").write_text(json.dumps(ficha, ensure_ascii=False, indent=2) + "\n",
                                          encoding="utf-8")
    (carpeta / "notas.md").write_text(NOTAS.format(nombre=nombre), encoding="utf-8")
    (carpeta / "historial_alertas.md").write_text(f"# Historial de alertas - {nombre}\n", encoding="utf-8")
    return carpeta


def _base_ec() -> Path | None:
    """proyectos_ec.db; si solo esta el .gz de data/, se abre en un temporal."""
    from core.db import ROOT, db_path
    p = db_path("proyectos_ec.db")
    if p.exists():
        return p
    gz = ROOT / "data" / "proyectos_ec.db.gz"
    if not gz.exists():
        return None
    destino = Path(tempfile.gettempdir()) / "proyectos_ec_probar.db"
    with gzip.open(gz) as f, open(destino, "wb") as out:
        shutil.copyfileobj(f, out)
    return destino


def noticias_de(slug: str, conn: sqlite3.Connection, desde: str) -> list[dict]:
    """Noticias de los paises del cliente que caen en sus temas o vienen de
    sus instituciones (el mismo criterio de fuentes/pagina, sin la UI)."""
    from noticias.fuentes import matchea_perfil
    from noticias.temas import clasificar
    c = config.todos()[slug]
    temas, inst = set(config.temas_de(slug)), set(c.get("instituciones", []))
    estrictas = set(c.get("fuentes_con_perfil_estricto", []))
    filas = conn.execute(
        "SELECT n.titulo, n.resumen, n.url, f.nombre, f.pais FROM noticias n "
        "JOIN noticias_fuentes f ON f.id = n.fuente_id WHERE n.first_seen_at >= ? "
        "ORDER BY n.first_seen_at DESC", (desde,)).fetchall()
    out = []
    for titulo, resumen, url, fuente, pais in filas:
        if pais not in c["paises"]:
            continue
        ts = set(clasificar(titulo, resumen, url)) & temas
        if not ts and fuente not in inst:
            continue
        if fuente in estrictas and not matchea_perfil(slug, titulo, resumen):
            continue
        out.append({"pais": pais, "fuente": fuente, "titulo": titulo, "temas": sorted(ts)})
    return out


def pls_de(slug: str, pais: str, conn: sqlite3.Connection, desde: str) -> list[dict]:
    """PL presentados desde `desde` cuya categoria (scraper/categorias) es del cliente."""
    from scraper.categorias import classify
    cats = set(config.todos()[slug].get("categorias_pl", []))
    if pais == "PE":
        q = "SELECT pley_num, titulo, sumilla FROM proyectos WHERE fec_presentacion >= ?"
    else:
        q = "SELECT n_tramite, titulo, '' FROM proyectos WHERE fec_presentacion >= ?"
    out = []
    for num, titulo, sumilla in conn.execute(q, (desde,)):
        cat = classify(titulo, sumilla)
        if cat in cats:
            out.append({"pais": pais, "numero": num, "titulo": titulo, "categoria": cat})
    return out


def probar(slug: str, dias: int = 30, muestra: int = 15) -> dict:
    from core.db import db_path
    if slug not in config.todos():
        raise SystemExit(f"No hay clientes/{slug}/cliente.json")
    desde = (datetime.now() - timedelta(days=dias)).date().isoformat()
    paises = config.todos()[slug]["paises"]
    pe = sqlite3.connect(db_path("proyectos.db"))
    notis = noticias_de(slug, pe, desde)
    pls = pls_de(slug, "PE", pe, desde) if "PE" in paises else []
    if "EC" in paises and (ec := _base_ec()):
        pls += pls_de(slug, "EC", sqlite3.connect(ec), desde)

    print(f"\n== {config.todos()[slug]['nombre']} · ultimos {dias} dias (desde {desde}) ==")
    print(f"Noticias: {len(notis)} (~{len(notis) / dias:.1f} por dia)")
    for n in notis[:muestra]:
        print(f"  [{n['pais']}] {n['titulo'][:110]}  ({n['fuente']}; {', '.join(n['temas']) or 'institucion'})")
    print(f"\nProyectos de ley: {len(pls)}")
    for p in pls[:muestra]:
        print(f"  [{p['pais']}] {p['numero']} {p['titulo'][:110]}  ({p['categoria']})")
    print("\nSi hay ruido: sumar exclusiones en notas.md, sacar temas o pasar fuentes a "
          "fuentes_con_perfil_estricto. Si falta algo: temas_propios, palabras_clave o instituciones.")
    return {"noticias": notis, "pls": pls}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("crear")
    c.add_argument("slug")
    c.add_argument("--nombre", required=True)
    c.add_argument("--paises", default="PE,EC")
    p = sub.add_parser("probar")
    p.add_argument("slug")
    p.add_argument("--dias", type=int, default=30)
    p.add_argument("--muestra", type=int, default=15)
    a = ap.parse_args()
    if a.cmd == "crear":
        carpeta = crear(a.slug, a.nombre, [x.strip().upper() for x in a.paises.split(",")])
        print(f"Creado {carpeta}. Llenar cliente.json y notas.md, despues: python -m clientes.nuevo probar {a.slug}")
    else:
        probar(a.slug, a.dias, a.muestra)


if __name__ == "__main__":
    main()
