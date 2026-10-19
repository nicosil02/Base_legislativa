from alerts import que_paso_hoy as q


def test_partir_respeta_parrafos():
    texto = "\n\n".join(["a" * 2000, "b" * 2000, "c" * 100])
    partes = q.partir(texto, largo=3500)
    assert len(partes) == 2 and partes[0] == "a" * 2000 and partes[1].startswith("b")


def test_prompt_solo_secciones_con_material():
    m = {"noticias": ["[PE] algo"], "normas": [], "pls": [], "sesiones": [], "tv": []}
    assert "NOTICIAS" in q.prompt(m) and "NORMAS" not in q.prompt(m)


def test_fresca_descarta_notas_viejas():
    assert not q._fresca({"fecha_pub": "2016-07-18T10:00:00Z"})
    from datetime import datetime, timezone
    assert q._fresca({"fecha_pub": datetime.now(timezone.utc).isoformat()})
