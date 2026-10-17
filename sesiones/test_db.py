"""Tests de sesiones/db.py y del parser de agenda (DB en tmp)."""
from sesiones.agenda_parser import extract_pls, to_text
from sesiones.db import Database
from sesiones.sync import _extract_pls_from_detalle


def test_upsert_y_detalle(tmp_path):
    fila = {"idSesion": 7, "fecha": "05/10/2026", "estado": "Convocada", "nombreComision": "Salud"}
    with Database(tmp_path / "t.db") as db:
        db.init_schema()
        db.init_schema()  # idempotente
        assert db.upsert_from_lista(fila, 3, "Senado", "t0") == (True, True)
        assert db.upsert_from_lista(fila, 3, "Senado", "t1") == (False, False)
        assert db.upsert_from_lista({**fila, "estado": "Realizada"}, 3, "Senado", "t2") == (False, True)
        detalle = {"idSesion": 7, "agenda": {"ordenesDia": [
            {"idAgendaOrdenDia": 1, "descripcion": "<p>Dictamen del <b>Proyecto de Ley 14586/2025-CR</b></p>"}]}}
        db.upsert_detalle(detalle, _extract_pls_from_detalle(detalle), "t3")
        r = db.conn.execute("SELECT fecha, camara, estado, last_changed_at FROM sesiones").fetchone()
        assert tuple(r) == ("2026-10-05", "Senado", "Realizada", "t2")
        assert db.conn.execute("SELECT descripcion_texto FROM sesion_agenda_punto").fetchone()[0] == \
            "Dictamen del Proyecto de Ley 14586/2025-CR"
        assert [x[0] for x in db.conn.execute("SELECT pley_num FROM sesion_pl_referenciado")] == [14586]


def test_parser_agenda():
    assert to_text("<p>Hola&nbsp;&Oacute;scar</p><ul><li>uno</li></ul>") == "Hola Óscar\nuno"
    assert to_text("<![bogus x]><p>a</p>") == "a"  # HTMLParser falla: fallback regex
    pls = extract_pls("PL N° 02554/2025-CR y Proyectos de Ley 2554/2025-CR, 99999/2025-CR")
    assert [p["pley_num"] for p in pls] == [2554]  # dedupe; 99999 fuera de rango
