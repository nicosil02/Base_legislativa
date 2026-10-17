import json
from pathlib import Path

from noticias.videos import PEDIDOS_DIR, es_relevante, pedidos, tipo_de


def test_es_relevante():
    assert es_relevante({"title": "#Entrevista | Marco Vinelli - Ministro", "duration": 990,
                         "channel": "Catequil Televisión | Cuarto Poder"}, "Marco Vinelli")  # re-sube Cuarto Poder
    assert es_relevante({"title": "MINISTRO VINELLI EN CUARTO PODER", "duration": 900,
                         "channel": "América Noticias"}, "Marco Vinelli")
    assert not es_relevante({"title": "¿CARLOS ESPÁ PROTAGONIZA...?", "duration": 900,
                             "channel": "Pitucos Marrones"}, "Carlos Espá")
    assert not es_relevante({"title": "Marco Vinelli: El Niño", "duration": 35}, "Marco Vinelli")
    assert not es_relevante({"title": "KEIKO'S PLAN B", "duration": 118}, "Marco Vinelli")
    assert not es_relevante({"title": "César Astudillo en vivo", "duration": 900, "live_status": "is_live"},
                            "César Astudillo")
    assert not es_relevante({"title": "Marco Vinelli (PE) - Casa Lunario", "duration": 3492,
                             "channel": "Marco Vinelli"}, "Marco Vinelli")


def test_tipo_y_pedidos(tmp_path: Path):
    assert tipo_de("Daniel Noboa", "EC") == "Entrevista: Daniel Noboa (EC)"
    d = tmp_path / PEDIDOS_DIR
    d.mkdir(parents=True)
    (d / "abc.json").write_text(json.dumps(
        {"video_id": "abc", "autoridad": "Marco Vinelli", "pais": "PE", "titulo": "t"}), encoding="utf-8")
    assert pedidos(tmp_path) == [{"id": "abc", "titulo": "t", "tipo": "Entrevista: Marco Vinelli"}]
