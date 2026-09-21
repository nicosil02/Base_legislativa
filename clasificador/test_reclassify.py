"""Self-check minimo de clasificador/reclassify.py::aplicar_decisiones.

Uso: python -m clasificador.test_reclassify
"""
import sqlite3

from clasificador.reclassify import aplicar_decisiones, init_schema


def _db_de_prueba() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("""CREATE TABLE proyectos (
        pley_num INTEGER, per_par_id INTEGER, cod_tipo_parl TEXT,
        tema TEXT, tema_manual INTEGER DEFAULT 0)""")
    conn.execute("INSERT INTO proyectos VALUES (1, 2026, 'C', 'Otros', 0)")
    conn.execute("INSERT INTO proyectos VALUES (2, 2026, 'C', 'Otros', 0)")
    init_schema(conn)
    conn.execute("""INSERT INTO clasificacion_sugerencias
        (id, pley_num, per_par_id, cod_tipo_parl, tema_anterior, tema_sugerido,
         confidence, estado, created_at)
        VALUES (10, 1, 2026, 'C', 'Otros', 'Salud', 0.8, 'pendiente', '2026-01-01T00:00:00Z')""")
    conn.execute("""INSERT INTO clasificacion_sugerencias
        (id, pley_num, per_par_id, cod_tipo_parl, tema_anterior, tema_sugerido,
         confidence, estado, created_at)
        VALUES (11, 2, 2026, 'C', 'Otros', 'Trabajo', 0.75, 'pendiente', '2026-01-01T00:00:00Z')""")
    conn.commit()
    return conn


def test_aceptar_actualiza_tema_y_marca_manual():
    conn = _db_de_prueba()
    stats = aplicar_decisiones(conn, [{"sugerencia_id": 10, "decision": "aceptar",
                                        "decided_by": "nico"}])
    assert stats["aceptadas"] == 1
    assert stats["procesadas"] == [10]
    tema, manual = conn.execute(
        "SELECT tema, tema_manual FROM proyectos WHERE pley_num=1").fetchone()
    assert tema == "Salud", tema
    assert manual == 1, "aceptar debe marcar tema_manual=1 (revision humana real)"
    estado, decided_by = conn.execute(
        "SELECT estado, decided_by FROM clasificacion_sugerencias WHERE id=10").fetchone()
    assert estado == "aplicado"
    assert decided_by == "nico"


def test_rechazar_no_toca_tema():
    conn = _db_de_prueba()
    aplicar_decisiones(conn, [{"sugerencia_id": 11, "decision": "rechazar"}])
    tema = conn.execute("SELECT tema FROM proyectos WHERE pley_num=2").fetchone()[0]
    assert tema == "Otros", "rechazar no debe cambiar el tema del PL"
    estado = conn.execute(
        "SELECT estado FROM clasificacion_sugerencias WHERE id=11").fetchone()[0]
    assert estado == "rechazado"


def test_sugerencia_inexistente_o_ya_resuelta_se_marca_procesada_sin_romper():
    """Nunca debe reintentarse para siempre - ni una id que no existe, ni
    una que ya se resolvio por otra via (ej. el reclassify semanal)."""
    conn = _db_de_prueba()
    conn.execute("UPDATE clasificacion_sugerencias SET estado='aplicado' WHERE id=11")
    conn.commit()
    stats = aplicar_decisiones(conn, [
        {"sugerencia_id": 999, "decision": "aceptar"},
        {"sugerencia_id": 11, "decision": "aceptar"},
    ])
    assert stats["no_encontradas"] == 1
    assert stats["ya_resueltas"] == 1
    assert set(stats["procesadas"]) == {999, 11}


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"OK {name}")
    print("todos los checks pasaron")
