"""Checks de noticias/db.py. Correr: python -m noticias.test_db"""
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from noticias.db import Database


def _iso_hace(dias: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=dias)).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_purge_usa_first_seen_at_no_fecha_pub():
    # Bug real 2026-09-16: purge_noticias_antiguas() borraba por fecha_pub
    # (fecha del articulo). Fuentes de publicacion lenta (CONVEAGRO, CEPES,
    # etc - verificado en vivo contra el log de produccion) traen articulos
    # ya publicados hace semanas cuando los visitamos - se insertaban y se
    # purgaban en la MISMA corrida (sync -> purge --dias 7), nunca
    # llegaban a mostrarse en la UI. Una noticia recien descubierta debe
    # sobrevivir al menos 'dias' dias sin importar que tan vieja diga ser.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        db_path = Path(td) / "test.db"
        with Database(db_path) as db:
            db.init_schema()
            fuente_id = db.upsert_fuente({
                "categoria": "Institucion", "pais": "PE", "nombre": "CONVEAGRO",
                "tipo": "rss",
            })
            # Articulo publicado hace 30 dias, pero recien lo vimos HOY.
            db.upsert_noticia(fuente_id, {
                "url": "https://conveagro.org.pe/vieja",
                "titulo": "Articulo publicado hace 30 dias, descubierto hoy",
                "fecha_pub": _iso_hace(30),
            })
            # Noticia que SI vimos hace 10 dias (debe purgarse con --dias 7).
            db.conn.execute(
                "UPDATE noticias SET first_seen_at=? WHERE url=?",
                (_iso_hace(10), "https://conveagro.org.pe/vieja"),
            )
            db.upsert_noticia(fuente_id, {
                "url": "https://conveagro.org.pe/nueva-y-vista-hoy",
                "titulo": "Articulo publicado hoy mismo, visto hoy",
                "fecha_pub": _iso_hace(0),
            })
            assert db.count_noticias() == 2

            eliminadas = db.purge_noticias_antiguas(7)
            assert eliminadas == 1, f"esperaba purgar 1 (la vista hace 10 dias), purgo {eliminadas}"
            assert db.count_noticias() == 1

            quedan = [r["url"] for r in db.conn.execute("SELECT url FROM noticias")]
            assert quedan == ["https://conveagro.org.pe/nueva-y-vista-hoy"]
    print("OK purge_noticias_antiguas: purga por first_seen_at, no por fecha_pub")


def test_deactivate_fuentes_huerfanas():
    # Bug real 2026-09-16: seed() solo hace upsert de lo que SI esta en
    # fuentes.py - una fuente renombrada ahi (ej. "Ministerio de Salud"
    # -> "MINSA") deja huerfana la fila vieja, activa=1 para siempre (36
    # asi, verificado contra la DB real). deactivate_fuentes_huerfanas
    # debe desactivar solo lo que NO esta en el set a mantener.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        db_path = Path(td) / "test.db"
        with Database(db_path) as db:
            db.init_schema()
            db.upsert_fuente({"categoria": "Institucion", "pais": "PE",
                              "nombre": "Ministerio de Salud", "tipo": "manual"})
            db.upsert_fuente({"categoria": "Institucion", "pais": "PE",
                              "nombre": "MINSA", "tipo": "gobpe"})
            n = db.deactivate_fuentes_huerfanas({("PE", "MINSA")})
            assert n == 1, f"esperaba desactivar 1 huerfana, desactivo {n}"
            activas = {(r["pais"], r["nombre"]) for r in
                       db.conn.execute("SELECT pais, nombre FROM noticias_fuentes WHERE activa=1")}
            assert activas == {("PE", "MINSA")}, activas
    print("OK deactivate_fuentes_huerfanas: desactiva solo lo que ya no esta en el catalogo")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"OK {name}")
    print("todos los checks pasaron")
