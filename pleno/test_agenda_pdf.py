"""Tests de pleno/agenda_pdf.py y pleno/from_agenda_pdf.py (sin red)."""
import sqlite3

from pleno.agenda_pdf import _fecha_a_iso, _filas, init_schema
from pleno.db import Database
from pleno.from_agenda_pdf import sync_from_agenda_pdf


def test_regex_fila_distingue_filas_con_pdf():
    html = '''
    <tr data-periodo="2026-2027">
        <td data-search="10/09/2026">10/09/2026</td>
        <td data-search="AGENDA-PLENO-DIPUTADOS-10-09-2026.pdf">
            <a class="fsm-pub-doc" href="https://diputados.congreso.gob.pe/wp-content/uploads/2026/09/AGENDA-PLENO-DIPUTADOS-10-09-2026.pdf">ver</a>
        </td>
        <td data-search="">&mdash;</td>
    </tr>
    <tr data-periodo="2026-2027">
        <td data-search="10/09/2026">10/09/2026</td>
        <td data-search="">&mdash;</td>
    </tr>
    '''
    filas = _filas(html)
    assert len(filas) == 1  # la 2da fila no tiene PDF de agenda
    periodo, fecha, pdf_url = filas[0]
    assert pdf_url.endswith("AGENDA-PLENO-DIPUTADOS-10-09-2026.pdf")
    assert _fecha_a_iso(fecha) == "2026-09-10"


def test_senado_con_columna_sesion_y_agenda_vacia_no_toma_el_diario():
    # Fila real del Senado (07/10/2026): columna "Sesion" y Agenda vacia; antes
    # se guardaba el Diario de los Debates como si fuera la agenda.
    html = '''<tr data-periodo="2026-2027"> <td data-search="07/10/2026">07/10/2026</td>
     <td class="snp26-sesion-celda" data-search="Sesion Solemne"><span>Sesion Solemne</span></td>
     <td data-search=""><span class="fsm-pub-sin">-</span></td> <td data-search=""><span>-</span></td>
     <td data-search="PLO-2026-8-SENADO.pdf"><a class="fsm-pub-doc" href="https://s/PLO-2026-8-SENADO.pdf">x</a></td></tr>
    <tr data-periodo="2026-2027"> <td data-search="30/09/2026">30/09/2026</td>
     <td class="snp26-sesion-celda" data-search="Sesion"><span>Sesion</span></td>
     <td data-search="AGENDA.pdf"><a class="fsm-pub-doc" href="https://s/AGENDA-PLENO-SENADO-30-09-2026.pdf">x</a></td></tr>'''
    assert [f[2] for f in _filas(html)] == ["https://s/AGENDA-PLENO-SENADO-30-09-2026.pdf"]


def test_pk_admite_varios_pdf_por_fecha_y_varias_fechas_por_pdf(tmp_path):
    conn = sqlite3.connect(tmp_path / "t.db")
    init_schema(conn)
    filas = [("diputados", "2026-07-26", "https://x/a.pdf"), ("diputados", "2026-07-26", "https://x/b.pdf"),
             ("diputados", "2026-07-27", "https://x/a.pdf")]
    conn.executemany("INSERT INTO pleno_agenda_pdf VALUES (?,?,?,'t','f')", filas)
    assert conn.execute("SELECT COUNT(*) FROM pleno_agenda_pdf").fetchone()[0] == 3
    conn.close()


def test_sync_from_agenda_pdf(tmp_path):
    dbpath = tmp_path / "test.db"
    conn = sqlite3.connect(dbpath)
    init_schema(conn)
    conn.execute("INSERT INTO pleno_agenda_pdf VALUES (?,?,?,?,?)",
                 ("diputados", "2026-09-17", "https://x/a.pdf",
                  "CÁMARA DE DIPUTADOS\nSesión del 17 de septiembre de 2026.\nresto...", "2026-09-22T00:00:00Z"))
    conn.commit()
    conn.close()
    with Database(dbpath) as db:
        db.init_schema()
        assert sync_from_agenda_pdf(db) == {"vistos": 1, "nuevos": 1, "actualizados": 0}
        row = db.conn.execute("SELECT titulo, camara, fecha_sesion FROM pleno_sesiones "
                              "WHERE fuente='agenda_pdf'").fetchone()
        assert tuple(row) == ("Sesión del 17 de septiembre de 2026", "D", "2026-09-17")
        # Idempotente: sin cambios no re-actualiza.
        assert sync_from_agenda_pdf(db) == {"vistos": 1, "nuevos": 0, "actualizados": 0}
