import sqlite3

import clientes.alertas_pl as ap

PL = "00098-2026-2031-CD"


def test_primera_vez_silencio_luego_cambio_real(tmp_path, monkeypatch):
    tracked = [{"pl_numero": PL, "titulo_matriz": "Ley de facultades",
                "tema_matriz": "x", "estado_matriz": "Activo"}]
    monkeypatch.setattr(ap, "matriz_bayer_crop", lambda pais: tracked if pais == "PE" else [])
    monkeypatch.setattr(ap, "ESTADO_PATH", tmp_path / "estado.json")
    db = tmp_path / "test.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE proyectos (proyecto_ley TEXT PRIMARY KEY, estado TEXT, url_portal TEXT)")
    conn.execute("INSERT INTO proyectos VALUES (?, 'EN COMISION', 'http://x')", (PL,))
    conn.commit()

    assert ap.detectar_cambios(db) == []  # visto por primera vez: no avisa
    assert ap.detectar_cambios(db) == []  # sin cambio

    conn.execute("UPDATE proyectos SET estado='DICTAMEN APROBADO'")
    conn.commit()
    conn.close()
    cambios = ap.detectar_cambios(db)
    assert len(cambios) == 1
    assert cambios[0]["estado_anterior"] == "EN COMISION"
    assert cambios[0]["estado_actual"] == "DICTAMEN APROBADO"

    assert ap.detectar_cambios(db) == []  # no repite el aviso
