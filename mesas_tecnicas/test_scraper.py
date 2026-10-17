"""Tests de mesas_tecnicas (parser de posts y DB, sin red)."""
from mesas_tecnicas.db import Database
from mesas_tecnicas.scraper import _coincide, _normalize_for_match, parse_post


def _html(*paras):
    return "<main>" + "".join(f"<p>{p}</p>" for p in paras) + "</main>"


def test_parse_post_mesa():
    d = parse_post(_html("Mesa de trabajo", "&#8220;Acceso a medicamentos&#8221;", "Comisión de Salud",
                         "Presidenta: Congresista Ana Pérez (Bancada X)", "Edificio Santos Atahualpa.",
                         "Sala 2", "Newsletter: ingrese un email"))
    assert d["tipo"] == "Mesa de trabajo" and d["comision"] == "Comisión de Salud"
    assert d["tema"] == "“Acceso a medicamentos”"
    assert (d["congresista"], d["bancada"]) == ("Congresista Ana Pérez", "Bancada X")
    assert d["lugar"] == "Edificio Santos Atahualpa. · Sala 2"
    # Sin Edificio/Sala: hasta 2 auditorios.
    assert parse_post(_html("Evento", "Tema", "Auditorio A", "Auditorio B", "Auditorio C"))["lugar"] == \
        "Auditorio A · Auditorio B"


def test_parse_post_pleno():
    d = parse_post(_html("Sesión del Pleno", "Primera Legislatura Ordinaria 2026 - 2027.",
                         "Preside: Presidente del Senado de la República", "Hemiciclo"), "Sesión del Pleno")
    assert (d["tipo"], d["camara"], d["lugar"]) == ("Pleno", "S", "Hemiciclo")


def test_coincide():
    largo = _normalize_for_match("“Mesa sobre el acceso universal a medicamentos oncologicos en el Peru”")
    assert _coincide(largo, "mesa de trabajo " + largo)
    assert _coincide(largo, largo[:40] + " otra cosa")
    assert not _coincide("tema corto", "otro tema")


def test_upsert(tmp_path):
    with Database(tmp_path / "t.db") as db:
        db.init_schema()
        row = {"url": "u1", "titulo": "Mesa", "tema": "T"}
        assert db.upsert(row) == (True, True)
        assert db.upsert(row) == (False, False)
        assert db.upsert({**row, "hora": "11:00 AM"}) == (False, True)
