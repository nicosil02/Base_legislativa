"""proyectos.db publicada en partes, una por dueño (rama `datos`).

Antes cada workflow subia la base entera y merge_db rescataba de la version
publicada solo las tablas de una lista fija: una tabla nueva fuera de la
lista se perdia sin aviso. Ahora cada workflow publica solo las partes que
escribe y quien necesita la base la arma de nuevo, igual que siempre:

  transcripciones  sesiones_transcripciones (vigilante, backfills, refrescar-pe)
  tv               tv_* y videos_autoridades (workflows de TV)
  base             todo lo demas (solo refrescar-pe); una tabla nueva cae aca

Las partes con varios escritores se unen fila por fila al publicar (union):
nunca se pisa una fila ajena, y en transcripciones gana el texto mas largo.

    python -m core.partes armar DESTINO.db PARTES_DIR      # parte.db.gz -> base completa
    python -m core.partes extraer ORIGEN.db PARTE SALIDA.db
    python -m core.partes unir LOCAL_PARTE.db REMOTO_PARTE.db PARTE
"""
from __future__ import annotations

import shutil
import sqlite3
import sys
from pathlib import Path

PARTES = {
    "transcripciones": ["sesiones_transcripciones"],
    "tv": ["tv_vistos", "tv_menciones", "tv_avisos", "videos_autoridades"],
}
NOMBRES = ["base", *PARTES]


def archivo(parte: str) -> str:
    """Nombre del .gz de la parte en data/ de la rama `datos`."""
    return f"proyectos.{parte}.db.gz"


def _tablas(conn: sqlite3.Connection, esquema: str = "main") -> list[str]:
    return [r[0] for r in conn.execute(
        f"SELECT name FROM {esquema}.sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]


def _copiar_tabla(conn: sqlite3.Connection, desde: str, tabla: str) -> None:
    """Crea `tabla` (con indices) en main a partir del esquema `desde` y copia las filas."""
    for (sql,) in conn.execute(
            f"SELECT sql FROM {desde}.sqlite_master WHERE tbl_name=? AND sql IS NOT NULL "
            f"ORDER BY type='index'", (tabla,)):
        conn.execute(sql)
    conn.execute(f'INSERT INTO main."{tabla}" SELECT * FROM {desde}."{tabla}"')


def extraer(origen: Path, parte: str, salida: Path) -> None:
    """Deja en `salida` solo las tablas de `parte` de la base `origen`."""
    salida.unlink(missing_ok=True)
    if parte == "base":
        src = sqlite3.connect(origen)
        src.execute("VACUUM INTO ?", (str(salida),))
        src.close()
        conn = sqlite3.connect(salida)
        for partes in PARTES.values():
            for t in partes:
                conn.execute(f'DROP TABLE IF EXISTS "{t}"')
        conn.commit()
        conn.execute("VACUUM")
        conn.close()
        return
    conn = sqlite3.connect(salida)
    conn.execute("ATTACH DATABASE ? AS o", (str(origen),))
    hay = set(_tablas(conn, "o"))
    for t in PARTES[parte]:
        if t in hay:
            _copiar_tabla(conn, "o", t)
    conn.commit()
    conn.close()


def armar(destino: Path, partes: dict[str, Path]) -> None:
    """Base completa en `destino` = base + las otras partes. Atomico: se
    escribe al lado y se reemplaza (la app puede estar leyendo)."""
    tmp = destino.with_name(destino.name + ".armando")
    shutil.copyfile(partes["base"], tmp)
    conn = sqlite3.connect(tmp)
    for parte, path in partes.items():
        if parte == "base" or not path.exists():
            continue
        conn.execute("ATTACH DATABASE ? AS p", (str(path),))
        for t in _tablas(conn, "p"):
            conn.execute(f'DROP TABLE IF EXISTS main."{t}"')
            _copiar_tabla(conn, "p", t)
        conn.commit()
        conn.execute("DETACH DATABASE p")
    conn.close()
    tmp.replace(destino)


def unir(local: Path, remoto: Path, parte: str) -> int:
    """Suma a `local` las filas de `remoto` (lo que publicaron otros
    workflows) sin pisar las propias. Devuelve cuantas filas cambiaron."""
    conn = sqlite3.connect(local)
    conn.execute("ATTACH DATABASE ? AS r", (str(remoto),))
    propias = set(_tablas(conn))
    for t in _tablas(conn, "r"):
        info = list(conn.execute(f'PRAGMA table_info("{t}")'))
        if t not in propias:
            _copiar_tabla(conn, "r", t)
        elif "texto" in {c[1] for c in info}:
            # transcripciones y TV en vivo crecen mientras dura la sesion:
            # la version con mas texto es la mas nueva.
            cols = ", ".join(f'"{c[1]}"' for c in info)
            misma = " AND ".join(f'b."{c[1]}" = d."{c[1]}"' for c in info if c[5])
            conn.execute(f"""
                INSERT OR REPLACE INTO "{t}" ({cols}) SELECT {cols} FROM r."{t}" AS d
                WHERE NOT EXISTS (SELECT 1 FROM "{t}" b
                                  WHERE {misma} AND length(coalesce(b.texto, '')) >= length(coalesce(d.texto, '')))""")
        else:
            conn.execute(f'INSERT OR IGNORE INTO "{t}" SELECT * FROM r."{t}"')
    conn.commit()
    n = conn.total_changes
    conn.close()
    return n


if __name__ == "__main__":
    cmd, *args = sys.argv[1:]
    if cmd == "armar":
        destino, carpeta = Path(args[0]), Path(args[1])
        armar(destino, {p: carpeta / archivo(p).removesuffix(".gz") for p in NOMBRES})
    elif cmd == "extraer":
        extraer(Path(args[0]), args[1], Path(args[2]))
    elif cmd == "unir":
        print(f"[partes] {unir(Path(args[0]), Path(args[1]), args[2])} fila(s) de otros workflows")
    else:
        raise SystemExit(__doc__)
