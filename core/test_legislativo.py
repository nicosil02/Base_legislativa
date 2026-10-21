import sqlite3
from datetime import datetime, timezone

from core import legislativo


def _bases(tmp_path):
    pe = sqlite3.connect(tmp_path / "proyectos.db")
    pe.executescript("""
        CREATE TABLE proyectos (per_par_id, cod_tipo_parl, pley_num, proyecto_ley, titulo, tema, tema_manual,
                                estado, fec_presentacion, url_portal);
        CREATE TABLE seguimientos (per_par_id, cod_tipo_parl, pley_num, fecha, estado, comisiones);
        INSERT INTO proyectos VALUES (1, 'PL', 571, '00571-2026', 'Ley del RENIEC', 'Tecnología', 1,
                                      'EN COMISION', '2026-10-15', 'u');
        INSERT INTO seguimientos VALUES (1, 'PL', 571, '2026-10-16T10:00:00', 'EN COMISION', 'Ciencia');
    """)
    pe.commit()
    ec = sqlite3.connect(tmp_path / "proyectos_ec.db")
    ec.executescript("""
        CREATE TABLE proyectos (n_tramite, titulo, tema, tema_manual, estado, fec_presentacion, url_portal);
        CREATE TABLE historial_cambios (n_tramite, changed_at, campo, valor_antes, valor_despues);
        INSERT INTO proyectos VALUES (486109, 'Ley de fomento agropecuario', 'Agricultura', 0, 'AVOCO', '2026-10-14', NULL);
        INSERT INTO historial_cambios VALUES (486109, '2026-10-17T15:00:00', 'estado', 'X', 'AVOCO');
    """)
    ec.commit()


def test_mismas_columnas_en_los_dos_paises(tmp_path, monkeypatch):
    _bases(tmp_path)
    monkeypatch.setattr(legislativo, "db_path", lambda n: tmp_path / n)
    desde = datetime(2026, 10, 1, tzinfo=timezone.utc)
    pe, ec = legislativo.cambios("PE", desde), legislativo.cambios("EC", desde)
    assert pe[0].keys() == ec[0].keys()
    # categoria es el tema, no la marca tema_manual (0/1)
    assert pe[0]["categoria"] == "Tecnología" and ec[0]["categoria"] == "Agricultura"
    assert legislativo.proyectos("PE", desde)[0]["numero"] == "571"
    assert legislativo.cambios("PE", datetime(2026, 10, 20, tzinfo=timezone.utc)) == []
