"""Tests de la limpieza de VTT."""
from congreso_live.transcripciones import _limpiar_vtt as L


def test_deduplica_roll_up():
    # Formato real de YouTube: cada bloque repite la linea asentada y
    # agrega la que se esta "tipeando" - nos quedamos solo con lo nuevo.
    vtt = """WEBVTT
Kind: captions
Language: es

00:00:01.800 --> 00:00:03.750 align:start position:0%

En<00:00:01.920><c> nuestras</c><00:00:02.240><c> otras</c>

00:00:03.750 --> 00:00:03.760 align:start position:0%
En nuestras otras


00:00:03.760 --> 00:00:06.349 align:start position:0%
En nuestras otras
observamos<00:00:04.400><c> tambien</c>
"""
    assert L(vtt) == "En nuestras otras observamos tambien"


def test_vacio():
    assert L("WEBVTT\n") == ""
    assert L("") == ""
