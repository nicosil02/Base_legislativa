"""Tests de congreso_live/agenda_preview.py (DB en memoria)."""
import sqlite3
from datetime import datetime, timedelta

import pytest

from congreso_live.agenda_preview import (
    LIMA, _una_linea_corta, camara_de_agenda, formatear_para_whatsapp,
    puntos_agenda, puntos_agenda_comision, puntos_agenda_pleno,
)

PUNTOS_JUSTICIA = ["Dictamen sobre reforma penal", "Informe de la subcomision"]
PUNTOS_PLENO = ["I. Concurrencia de ministro de Estado", "II. Oficios del Poder Ejecutivo"]


@pytest.fixture
def hoy():
    return datetime.now(LIMA).date().isoformat()


@pytest.fixture
def conn(hoy):
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE sesiones (id_sesion INTEGER PRIMARY KEY, nombre_comision TEXT, camara TEXT, fecha TEXT)")
    c.execute("CREATE TABLE sesion_agenda_punto (id_sesion INTEGER, orden INTEGER, descripcion_texto TEXT)")
    c.execute("INSERT INTO sesiones VALUES (1, 'Justicia y Derechos Humanos', 'Senado', ?)", (hoy,))
    c.execute("INSERT INTO sesiones VALUES (2, 'Energia y Minas', 'Diputados', ?)", (hoy,))
    c.executemany("INSERT INTO sesion_agenda_punto VALUES (1, ?, ?)", list(enumerate(PUNTOS_JUSTICIA, 1)))
    # Formato real del PDF: numerales romanos sueltos, encabezado de pagina
    # repetido que cierra el indice, numeros de pagina sueltos.
    c.execute("CREATE TABLE pleno_agenda_pdf (camara TEXT, fecha TEXT, texto TEXT)")
    texto_pdf = (
        "Agenda del Pleno del Senado\nSesión del jueves\n\n"
        "SENADO DE LA REPÚBLICA | Área de Relatoría y Agenda\n2\n"
        "ÍNDICE\nPág.\n\nÍndice\n2\n"
        "I.\nConcurrencia de ministro de Estado\n3\n"
        "II.\nOficios del Poder Ejecutivo\n4\n\n"
        "Agenda del Pleno del Senado\n"
        "SENADO DE LA REPÚBLICA | Área de Relatoría y Agenda\n3\n"
        "I. CONCURRENCIA DE MINISTRO DE ESTADO\n(cuerpo completo)..."
    )
    c.execute("INSERT INTO pleno_agenda_pdf VALUES ('senado', ?, ?)", (hoy, texto_pdf))
    return c


def test_puntos_agenda_comision(conn):
    assert puntos_agenda_comision(conn, "Comision: Justicia", "Comisión de Justicia y DDHH del Senado") == PUNTOS_JUSTICIA
    # Camara equivocada, sin sesion hoy o Pleno: no adivina.
    assert puntos_agenda_comision(conn, "Comision: Justicia", "Comisión de Justicia de la Cámara de Diputados") == []
    assert puntos_agenda_comision(conn, "Comision: Salud", "Comisión de Salud") == []
    assert puntos_agenda_comision(conn, "Pleno: Senado", "Sesión del Pleno del Senado") == []


def test_camara_de_agenda(conn, hoy):
    assert camara_de_agenda(conn, "Comision: Justicia", "sin fecha en el titulo", hoy) == "Senado"
    assert camara_de_agenda(conn, "Comision: Energia Y Minas", "sin fecha", hoy) == "Diputados"
    assert camara_de_agenda(conn, "Comision: Salud", "sin fecha", hoy) is None
    # Fecha UTC de captura del dia siguiente: tambien prueba el dia anterior.
    manana = (datetime.now(LIMA).date() + timedelta(days=1)).isoformat()
    assert camara_de_agenda(conn, "Comision: Justicia", "sin fecha", manana) == "Senado"
    assert camara_de_agenda(conn, "Pleno: Senado", "sin fecha", hoy) is None
    # La fecha del titulo alcanza sola aunque `fecha` no tenga nada que ver.
    titulo = f"Sesión de la Comisión | {hoy[8:10]}/{hoy[5:7]}/{hoy[:4]}"
    assert camara_de_agenda(conn, "Comision: Justicia", titulo, "2099-01-01") == "Senado"


def test_formato_y_linea_corta():
    assert formatear_para_whatsapp([]) == ""
    assert formatear_para_whatsapp(["A", "B"]) == "\n\nPuntos de agenda:\n- A\n- B"
    assert _una_linea_corta("Primera línea del punto\n\nDetalle largo despues") == "Primera línea del punto"
    assert _una_linea_corta("x" * 200) == "x" * 139 + "…"


def test_puntos_agenda_pleno_y_dispatcher(conn):
    assert puntos_agenda_pleno(conn, "Pleno: Senado") == PUNTOS_PLENO
    assert puntos_agenda_pleno(conn, "Pleno: Diputados") == []
    assert puntos_agenda_pleno(conn, "Pleno: Congreso") == []
    assert puntos_agenda(conn, "Pleno: Senado", "cualquier titulo") == PUNTOS_PLENO
    assert puntos_agenda(conn, "Comision: Justicia", "Comisión de Justicia y DDHH del Senado") == PUNTOS_JUSTICIA
