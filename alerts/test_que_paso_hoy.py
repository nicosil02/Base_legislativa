from alerts import que_paso_hoy as q


def test_partir_respeta_parrafos():
    texto = "\n\n".join(["a" * 2000, "b" * 2000, "c" * 100])
    partes = q.partir(texto, largo=3500)
    assert len(partes) == 2 and partes[0] == "a" * 2000 and partes[1].startswith("b")


def test_prompt_solo_secciones_con_material():
    m = {"noticias": ["[PE] algo"], "normas": [], "pls": [], "sesiones": [], "tv": []}
    assert "NOTICIAS" in q.prompt(m) and "NORMAS" not in q.prompt(m)


def test_pdf_viejo_mira_la_fecha_del_documento(monkeypatch):
    from datetime import datetime, timezone
    fechas = {"https://x.ec/2026/10/r117.pdf": datetime(2016, 6, 7, tzinfo=timezone.utc),
              "https://x.ec/2026/10/manual.pdf": datetime.now(timezone.utc),
              "https://x.ec/ilegible.pdf": None}
    monkeypatch.setattr(q, "_fecha_pdf", fechas.get)
    assert q._pdf_viejo("https://x.ec/2026/10/r117.pdf")
    assert not q._pdf_viejo("https://x.ec/2026/10/manual.pdf")
    assert not q._pdf_viejo("https://x.ec/ilegible.pdf")
    assert not q._pdf_viejo("https://x.ec/nota.html")


def test_fresca_descarta_notas_viejas():
    assert not q._fresca({"fecha_pub": "2016-07-18T10:00:00Z"})
    from datetime import datetime, timezone
    assert q._fresca({"fecha_pub": datetime.now(timezone.utc).isoformat()})


def test_etapas_de_tramite_validas():
    from core import legislativo
    for estados in legislativo.ETAPA_ESTADO.values():
        assert set(estados.values()) <= set(range(len(legislativo.ETAPAS)))
    assert "ARCHIVADO" not in legislativo.ETAPA_ESTADO["EC"]


def test_reparar_titulo_mal_codificado():
    assert q.reparar("MarÃ­a plantea transiciÃ³n democrÃ¡tica") == "María plantea transición democrática"
    assert q.reparar("Sin problema") == "Sin problema"


def test_titular_norma():
    from alerts.que_paso_hoy import titular_norma
    assert titular_norma("MINISTERIO PÚBLICO — RESOLUCIÓN N° 34-2026-MP-FN: Nombran fiscal") == (
        "Nombran fiscal", "Ministerio público, RESOLUCIÓN N° 34-2026-MP-FN")
    assert titular_norma("Agrocalidad - Documentos publicados: Manual Aprobado(1) signed signed") == (
        "Agrocalidad - Documentos publicados: Manual Aprobado", None)
    assert titular_norma("634-2026-OA-CENARES-MINSA — APROBAR la baja de productos") == (
        "Aprobar la baja de productos", "634-2026-OA-CENARES-MINSA")
    assert titular_norma("Sexto Suplemento No. 401") == ("Sexto Suplemento No. 401", None)
