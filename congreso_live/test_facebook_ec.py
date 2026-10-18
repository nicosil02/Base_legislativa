"""Tests de congreso_live/facebook_ec.py (sin red)."""
import io
import sqlite3
import threading

import congreso_live.facebook_ec as fb
from congreso_live.facebook_ec import ids_en_vivo, parsear_tarjetas, tipo_de, url_video


def test_parsear_tarjetas_y_urls():
    # Texto real de las tarjetas de la pagina.
    tarjetas = [
        ["111", "EN DIRECTO\nSesión No. 193-2025-2027 Comisión de Desarrollo Económico\n12 espectadores"],
        ["222", "23:20\nSesión Nro. 192-2025-2027 Comisión de Desarrollo Económico\n528 visualizaciones\n · hace 2 días"],
        ["333", "1:09:24\nSESIÓN No. 191-2025-2027 Comisión de Desarrollo Económico\n504 visualizaciones"],
        ["444", "1:46:23\nSesión No. 190-2025-2027 Comisión de Desarrollo Económico\n1,1 mil visualizaciones"],
        ["555", "42:47\nSesión Nro. 189-2025-2027\n678 visualizaciones"],
    ]
    s = parsear_tarjetas(tarjetas, max_n=3)
    assert [x["fb_id"] for x in s] == ["222", "333", "444"]  # salta EN DIRECTO, respeta el tope
    assert s[0]["titulo"].startswith("Sesión Nro. 192")
    assert [x["duracion_seg"] for x in s] == [1400, 4164, 6383]
    assert url_video("fb_222") == "https://www.facebook.com/watch/?v=222"
    assert url_video("ZEUaL91M6D4").startswith("https://www.youtube.com/")
    assert tipo_de("Justicia") == "Comision: Justicia (EC)"


def test_ids_en_vivo():
    # Recortes reales (rppnoticias/live_videos, 2026-10-18): el aro "VIVO" de
    # la foto de perfil apunta al directo; un VOD con "#ENVIVO" en el titulo
    # (Ecuavisa) no es un directo.
    tarjetas = [
        ["2578004636033584", "VIVO\nRPP Noticias\xa0\n7,8\xa0mill. seguidores • 77 seguidos\nMás"],
        ["2578004636033584", "VIVO\n4\n🟡 #ENVIVO | Siempre en Casa - 18/10/2026"],
        ["111", "EN DIRECTO\nSesión No. 193-2025-2027 Comisión de Desarrollo Económico"],
        ["1436651718655198", "33:57\n#ENVIVO 🔴| CONTACTO DIRECTO - Más información\n8,8\xa0mil"],
        ["999", "Programado\nSesión No. 194"],
        ["888", ""],
    ]
    assert ids_en_vivo(tarjetas) == ["2578004636033584", "111"]


def test_es_directo():
    assert fb.es_directo("https://video.fbcdn.net/hvideo/v/x/live-dash/dash-abr-ibr-audio/1.mpd?oh=1")
    assert not fb.es_directo("https://video.fbcdn.net/o1/v/t29/f2/m311/AQOj.mp4?_nc_cat=109")


def test_listar_en_vivo(monkeypatch):
    # Formato de vivos_de_interes; solo lo que Facebook confirma en vivo, sin repetir.
    monkeypatch.setattr(fb, "_tarjetas_de_paginas", lambda paginas, espera_ms, timeout_ms: [
        ("Justicia", [["1", "VIVO\nJusticia AN"], ["1", "EN DIRECTO\nSesion 141"], ["2", "40:30\nSesion 140"]]),
        ("Educación", [["3", "EN DIRECTO\nSesion 50"]]),  # ya termino entre la pagina y la confirmacion
        ("Biodiversidad", [["4", "VIVO\nx"]]),  # error de red al confirmar: se salta
    ])

    def info(fb_id):
        if fb_id == "4":
            raise OSError("timeout")
        return {"titulo": "Sesión No. 141"} if fb_id == "1" else None

    monkeypatch.setattr(fb, "info_en_vivo", info)
    assert fb.listar_en_vivo() == [{"id": "fb_1", "titulo": "Sesión No. 141", "tipo": "Comision: Justicia (EC)",
                                    "pais": "EC", "url": "https://www.facebook.com/watch/?v=1"}]


_MPD = """<?xml version="1.0"?>
<MPD type="{tipo}" xmlns="urn:mpeg:dash:schema:mpd:2011"><Period>
<AdaptationSet><Representation id="v" mimeType="video/mp4" bandwidth="231140"><SegmentTemplate
 initialization="../v/1_0-init.m4v" media="../v/1_0-$Time$.m4v"><SegmentTimeline>
 <S t="100" d="2000"/></SegmentTimeline></SegmentTemplate></Representation></AdaptationSet>
<AdaptationSet>
<Representation id="md-a" mimeType="audio/mp4" bandwidth="99000"><SegmentTemplate
 initialization="../md-a/1_0-init.m4a?ms=m_C" media="../md-a/1_0-$Time$.m4a?ms=m_C"><SegmentTimeline>
 {segs}</SegmentTimeline></SegmentTemplate></Representation>
<Representation id="qd-a" mimeType="audio/mp4" bandwidth="64000"><SegmentTemplate
 initialization="../qd-a/1_0-init.m4a?ms=m_C" media="../qd-a/1_0-$Time$.m4a?ms=m_C"><SegmentTimeline>
 {segs}</SegmentTimeline></SegmentTemplate></Representation>
</AdaptationSet></Period></MPD>"""


def _mpd(tipo, tiempos):
    return _MPD.format(tipo=tipo, segs="".join(f'<S t="{t}" d="2000"/>' for t in tiempos)).encode()


def test_alimentar_directo(monkeypatch):
    # Arranca en el borde en vivo (ultimo segmento), despues solo los nuevos,
    # del audio mas liviano, y cierra cuando el manifiesto deja de ser dynamic.
    base = "https://video.fbcdn.net/x/live-dash/dash-abr-ibr-audio/1.mpd?oh=firma"
    manifiestos = iter([_mpd("dynamic", [0, 2000, 4000]), _mpd("dynamic", [2000, 4000, 6000, 8000]),
                        _mpd("static", [])])
    pedidos = []

    def bajar(url):
        if url == base:
            return next(manifiestos)
        pedidos.append(url.removeprefix("https://video.fbcdn.net/x/live-dash/"))
        return url.encode()

    monkeypatch.setattr(fb, "_bajar", bajar)
    monkeypatch.setattr("time.sleep", lambda s: None)
    destino = io.BytesIO()
    destino.close = lambda: setattr(destino, "cerrado", True)
    fb.alimentar_directo(base, destino, threading.Event())
    assert pedidos == ["qd-a/1_0-init.m4a?ms=m_C", "qd-a/1_0-4000.m4a?ms=m_C",
                       "qd-a/1_0-6000.m4a?ms=m_C", "qd-a/1_0-8000.m4a?ms=m_C"]
    assert getattr(destino, "cerrado", False)


def test_procesar_pendientes_no_repite_directo_completo(monkeypatch, tmp_path):
    # Un directo ya transcrito casi entero no se baja de nuevo como VOD; uno
    # tomado tarde (poca duracion frente al video) si.
    from congreso_live.transcripciones import guardar_transcripcion, init_schema

    db = tmp_path / "t.db"
    conn = sqlite3.connect(db)
    init_schema(conn)
    guardar_transcripcion(conn, "fb_1", "Comision: Justicia (EC)", "S1", "2026-10-15", 3000, "texto", [])
    guardar_transcripcion(conn, "fb_2", "Comision: Justicia (EC)", "S2", "2026-10-15", 600, "texto", [])
    conn.close()
    monkeypatch.setattr(fb, "listar_terminadas", lambda: [
        {"fb_id": "1", "titulo": "S1", "duracion_seg": 3600, "comision": "Justicia"},
        {"fb_id": "2", "titulo": "S2", "duracion_seg": 3600, "comision": "Justicia"},
        {"fb_id": "3", "titulo": "S3", "duracion_seg": 1200, "comision": "Justicia"},
    ])
    monkeypatch.setattr(fb, "_fecha_real", lambda url: None)
    hechos = []
    monkeypatch.setattr("congreso_live.live_transcribe.transcribir_vod",
                        lambda vid, tipo, titulo, **kw: hechos.append((vid, kw["duracion"])) or {"ok": True})
    r = fb.procesar_pendientes(db, max_n=5)
    assert hechos == [("fb_2", 3600), ("fb_3", 1200)]
    assert r["pendientes_totales"] == 2


def test_paginas_en_agenda_solo_las_que_sesionan_ahora(tmp_path):
    from datetime import datetime

    from congreso_live.facebook_ec import PAGINAS, paginas_en_agenda
    db = tmp_path / "ec.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE sesiones_ec (nombre_comision TEXT, fecha TEXT, hora_inicio TEXT, hora_fin TEXT, status TEXT)")
    c.executemany("INSERT INTO sesiones_ec VALUES (?,?,?,?,?)", [
        ("Justicia", "2026-10-14", "11:00", "13:30", "CONFIRMED"),
        ("Biodiversidad", "2026-10-14", "15:00", "16:30", "CONFIRMED"),
        ("Educación", "2026-10-14", "10:00", "12:00", "CANCELLED"),
        ("Pleno", "2026-10-14", "10:30", "13:00", "CONFIRMED"),
    ])
    c.commit(); c.close()
    # 15:40: Justicia ya paso su margen de 2 h (13:30 + 2 h); Biodiversidad
    # en curso; Educacion cancelada; Pleno no es pagina de Facebook.
    assert paginas_en_agenda(datetime(2026, 10, 14, 15, 40), db) == {"Biodiversidad": PAGINAS["Biodiversidad"]}
    assert "Justicia" in paginas_en_agenda(datetime(2026, 10, 14, 10, 50), db)
    assert paginas_en_agenda(datetime(2026, 10, 15, 12, 0), db) == {}
    assert paginas_en_agenda(db=tmp_path / "no.db") is None
