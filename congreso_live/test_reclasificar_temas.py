"""Tests de congreso_live/reclasificar_temas.py."""
import json
import sqlite3

from congreso_live.reclasificar_temas import run


def test_resumen_limpio_quita_falsos_positivos(tmp_path):
    # Sesion real de Salud: el texto crudo daba KYC/Crop por apellidos.
    db_path = tmp_path / "test.db"
    resumenes_path = tmp_path / "resumenes.json"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE sesiones_transcripciones (video_id TEXT PRIMARY KEY, titulo TEXT, temas TEXT)")
    conn.execute("INSERT INTO sesiones_transcripciones VALUES (?,?,?)",
                 ("uawItrs3E9U", "Sesión de la Comisión de Salud de la Cámara de Diputados",
                  "Coyuntura política,KYC / AML / Financiero"))
    conn.commit()
    conn.close()
    resumenes_path.write_text(json.dumps([{
        "video_id": "uawItrs3E9U",
        "resumen": "Sesion de la Comision de Salud sobre crisis en hospitales de EsSalud.",
        "ideas_clave": [
            "Redes de salud de Loreto denuncian que el SIS les nego presupuesto para medicamentos",
            "Hospital Carlos Seguin Escobedo: el acelerador lineal esta inoperativo, se contrata clinica privada",
        ],
    }]), encoding="utf-8")

    assert run(db_path, resumenes_path) == {"con_resumen": 1, "actualizadas": 1}
    conn = sqlite3.connect(db_path)
    temas = conn.execute("SELECT temas FROM sesiones_transcripciones").fetchone()[0]
    conn.close()
    assert "Salud" in temas and "Crop" not in temas
