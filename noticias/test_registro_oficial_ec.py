import pytest

import noticias.registro_oficial_ec as ro


def test_parse_norms():
    norms = ro.parse_norms([
        "FUNCIÓN EJECUTIVA",
        "RESOLUCIONES:",
        "SERVICIO DE RENTAS INTERNAS:",
        "NAC-DGERCGC26-00000028 Se reforma la Resolución NAC-DGERCGC26-00000024",
        "FUNCIÓN DE TRANSPARENCIA Y CONTROL SOCIAL",
        "CONSEJO DE PARTICIPACIÓN CIUDADANA Y CONTROL SOCIAL:",
        "CPCCS-PLE-SG-029-O-2026-0225 Se convoca a la ciudadanía",
    ])
    assert len(norms) == 2
    assert norms[0]["funcion"] == "FUNCIÓN EJECUTIVA"
    assert norms[0]["entidad"] == "SERVICIO DE RENTAS INTERNAS"
    assert norms[0]["codigo"] == "NAC-DGERCGC26-00000028"
    assert "reforma" in norms[0]["titulo"].lower()
    assert norms[1]["entidad"] == "CONSEJO DE PARTICIPACIÓN CIUDADANA Y CONTROL SOCIAL"


def test_skip_metadata():
    assert ro._skip_metadata(["Por", "Moises Gutierrez", "3 Ago 2026", "Suplemento",
                              "FUNCIÓN EJECUTIVA"]) == ["FUNCIÓN EJECUTIVA"]


def test_parse_pdf_widget():
    """Snippet calcado del widget real; el PDF generico del Manual se descarta."""
    html_sample = (
        '<div class="row_post_imagen_texto"> Registro Oficial '
        '<span>Año II - Nº 367</span> viernes, 11 septiembre 2026 69 PÁGINAS '
        '<a href="https://esacc.corteconstitucional.gob.ec/storage/api/v1/'
        '10_DWL_FL/eyJjYXJwZXRhIjoicm8iLCJ1dWlkIjoiYWJjLnBkZiJ9">Descargar</a></div>'
        '<div class="row_post_imagen_texto"> Registro Oficial '
        '<span>Año II - Nº 366</span> jueves, 10 septiembre 2026 60 PÁGINAS '
        '<a href="https://esacc.corteconstitucional.gob.ec/storage/api/v1/'
        '10_DWL_FL/eyJjYXJwZXRhIjoicm8iLCJ1dWlkIjoiZGVmLnBkZiJ9">Descargar</a></div>'
        '<a href="https://esacc.corteconstitucional.gob.ec/storage/api/v1/'
        '10_DWL_FL/eyJjYXJwZXRhIjoid2Jwcm92MjAyMyIsInV1aWQiOiJtYW51YWwtZ2VuZXJpY28ucGRmIn0=">'
        'Descargar</a>'  # Manual generico (carpeta=wbprov2023)
    )
    items = ro._parse_pdf_widget(html_sample)
    assert len(items) == 2
    assert items[0]["numero"] == "367" and items[0]["paginas"] == 69
    assert items[1]["numero"] == "366" and items[1]["paginas"] == 60
    assert all(ro._PDF_MANUAL_MARKER not in i["url"] for i in items)


def test_extract_pdf_text_ocr_solo_en_pagina_vacia(monkeypatch):
    fitz = pytest.importorskip("pymupdf")
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "Texto real de una norma, con contenido de sobra.")
    doc.new_page()  # sin texto: simula una pagina escaneada
    pdf_bytes = doc.tobytes()
    doc.close()

    calls = []
    monkeypatch.setattr(ro, "_ocr_page", lambda page: (calls.append(page.number), "TEXTO-OCR-SIMULADO")[1])
    text = ro.extract_pdf_text(pdf_bytes)
    assert "Texto real de una norma" in text
    assert "TEXTO-OCR-SIMULADO" in text
    assert calls == [1]
