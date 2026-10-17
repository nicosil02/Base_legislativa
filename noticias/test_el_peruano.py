from datetime import timedelta
from pathlib import Path

import noticias.el_peruano as ep
from core.tiempo import ahora_lima
from noticias.db import Database


def test_run_sync_guarda_todo_sin_filtrar_tema(tmp_path: Path, monkeypatch):
    """Guarda tambien la norma que no matchea ningun tema, y la fuente queda
    con clientes='todos' (si no, alerts/relevancia.py no la ve)."""
    items = [
        {"sector": "MIDAGRI", "url": "https://x/1", "id_dispositivo": "1-2026",
         "tipo": "RESOLUCIÓN MINISTERIAL", "numero": "N° 1-2026-MIDIAGRI",
         "titulo": "Aprueban norma agraria sobre semillas"},
        {"sector": "VIVIENDA", "url": "https://x/2", "id_dispositivo": "2-2026",
         "tipo": "RESOLUCIÓN SUPREMA", "numero": "N° 2-2026-VIVIENDA",
         "titulo": "Designan miembro del Directorio de la SUNARP"},
    ]
    monkeypatch.setattr(ep, "fetch_range", lambda *a, **k: items)
    with Database(tmp_path / "test.db") as db:
        db.init_schema()
        stats = ep.run_sync(db, dias=1)
        assert stats["items_totales"] == 2, stats
        assert stats["nuevas"] == 2, stats
        row = db.conn.execute(
            "SELECT clientes FROM noticias_fuentes WHERE nombre=?", (ep.FUENTE_NOMBRE,)).fetchone()
        assert row["clientes"] == "todos"


def test_fecha_es_la_del_dia_de_publicacion(tmp_path: Path, monkeypatch):
    """Una norma de ayer queda con fecha de ayer aunque se vuelva a ver hoy."""
    ayer = (ahora_lima().date() - timedelta(days=1)).strftime("%Y%m%d")
    norma = {"sector": "MIDAGRI", "url": "https://x/9", "id_dispositivo": "9-2026",
             "tipo": "DECRETO SUPREMO", "numero": "N° 011-2026-MIDAGRI",
             "titulo": "Reglamento de residuos"}
    monkeypatch.setattr(ep, "fetch_range", lambda s, ini, fin, **k: [norma] if ini == ayer else [])
    with Database(tmp_path / "t.db") as db:
        db.init_schema()
        ep.run_sync(db, dias=2)
        ep.run_sync(db, dias=2)
        f = db.conn.execute("SELECT fecha_pub FROM noticias").fetchone()[0]
    assert f == ep._fecha_a_iso(ayer)


def test_parse_page():
    html = ('<p class="text-sm font-semibold text-primary">SALUD</p><div>'
            '<a href="/dispositivo/NL/2539838-9"><p>RESOLUCIÓN MINISTERIAL</p>'
            '<p>N° 152-2026-MINSA</p></a></div><div>'
            '<a href="/dispositivo/NL/2539838-9">Aprueban la  Directiva &amp; anexos</a>'
            ' 1 <!-- --> <!-- --> dispositivos')
    items, total = ep.parse_page(html)
    assert total == 1
    assert items == [{"sector": "SALUD", "url": ep.BASE_URL + "/dispositivo/NL/2539838-9",
                      "id_dispositivo": "2539838-9", "tipo": "RESOLUCIÓN MINISTERIAL",
                      "numero": "N° 152-2026-MINSA", "titulo": "Aprueban la Directiva & anexos"}]
