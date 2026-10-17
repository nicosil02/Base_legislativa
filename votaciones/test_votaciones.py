"""Tests del parser OCR de votaciones y del cruce de nombres (sin OCR ni red)."""
from votaciones.ocr_pleno import _fila, normalizar_voto
from votaciones.unificar import canonizador, clave


def test_normalizar_voto():
    assert normalizar_voto("5I +++") == "SI"  # el OCR lee "5I"
    assert normalizar_voto("N0 ---") == "NO"
    assert normalizar_voto("Abst.") == "ABSTENCION"
    assert normalizar_voto("ACUÑA") is None


def test_fila_con_voto_pegado():
    fila = _fila([(10, 5, "APP"), (10, 40, "ACUÑA PERALTA, MARIA GRIMANEZA SI +++")])
    assert fila[:3] == ("ACUÑA PERALTA, MARIA GRIMANEZA", "APP", "SI")


def test_canonizador():
    f = canonizador(["BAZÁN CALDERÓN, DIEGO ALONSO", "MONTOYA MANRIQUE, JORGE"])
    assert clave("Bazán, Diego") == "BAZANDIEGO"
    assert f("BAZAN CALDERON, DIEGO") == "BAZÁN CALDERÓN, DIEGO ALONSO"  # nombre truncado
    assert f("MONTOYA MANRIQUE, JORGE JPP-VP") == "MONTOYA MANRIQUE, JORGE"  # sigla pegada
    assert f("PEREZ LOPEZ, JUAN") is None
