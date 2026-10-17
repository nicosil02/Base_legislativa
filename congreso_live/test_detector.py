"""Tests de congreso_live/detector.py (sin red)."""
import os
from unittest.mock import patch

import congreso_live.detector as det
from congreso_live.detector import TIPO_PLENO_EC
from congreso_live.detector import clasificar_titulo as C


def test_pleno():
    assert C("🔴EN VIVO: Sesión del Pleno de la Cámara de Diputados | 10 DE "
             "SEPTIEMBRE DEL 2026") == "Pleno: Diputados"
    assert C("🔴EN VIVO: Sesión del Pleno del Senado de la República | 9 DE "
             "SEPTIEMBRE DEL 2026") == "Pleno: Senado"
    # Sesion conjunta (sin "senado" ni "diputados") - fallback.
    assert C("🔴 EN VIVO: Pleno del Congreso | 19 DE JUNIO") == "Pleno: Congreso"


def test_ordinarias():
    assert C("EN VIVO: Comisión de Economía, Banca y Finanzas") == "Comision: Economia"
    assert C("Comisión Agraria - sesión ordinaria") == "Comision: Agraria"
    assert C("🔴 Comisión de Salud y Población") == "Comision: Salud"
    assert C("Comisión de Energía y Minas") == "Comision: Energia Y Minas"


def test_excluye_especiales_y_noticias():
    assert C("🔴 EN VIVO: Comisión Especial proyecto Puyango – Tumbes") is None
    assert C("Comisión Especial Multipartidaria Pro-Inversión") is None
    assert C("Comisión Investigadora sobre ...") is None
    assert C("🔴 EN VIVO: Congreso Noticias – Edición Central") is None
    assert C("CONGRESO TV DIGITAL EN VIVO") is None
    assert C("Distinción Nacional al Emprendimiento") is None


def test_las_25_comisiones_ordinarias_reales():
    # Comisiones reales (tabla `sesiones`) que antes no tenian keyword.
    assert C("EN VIVO: Comisión de Desarrollo Agrario") == "Comision: Agrario"
    assert C("EN VIVO: Comisión de Asuntos de Gestión del Estado y "
             "Contraloría") == "Comision: Gestion Del Estado"
    assert C("EN VIVO: Comisión de Control Político sobre los Actos "
             "Normativos del Poder Ejecutivo y Regímenes de Excepción"
             ) == "Comision: Regimenes De Excepcion"
    assert C("EN VIVO: Comisión de Medio Ambiente y Sostenibilidad"
             ) == "Comision: Medio Ambiente"
    assert C("EN VIVO: Comisión de Ordenamiento y Seguimiento Legislativo"
             ) == "Comision: Seguimiento Legislativo"
    assert C("EN VIVO: Comisión de Ética Parlamentaria") == "Comision: Etica Parlamentaria"
    # "Procedimientos Especiales" es ordinaria; las especiales de verdad no.
    assert C("EN VIVO: Comisión de Procedimientos Especiales"
             ) == "Comision: Procedimientos Especiales"
    assert C("🔴 EN VIVO: Comisión Especial encargada de investigar...") is None


def test_vacio_y_no_relacionado():
    assert C("") is None
    assert C(None) is None
    assert C("Concierto en el auditorio") is None


def test_clasificar_ec():
    # Titulos reales del canal de la Asamblea, incluidos los que vienen en ingles.
    for t in ("Sesión No. 126-AN-2025-2029 del pleno de la Asamblea Nacional",
              "National Assembly Plenary Session No. 120-AN-2025-2029",
              "Virtual Session No. 119-AN-2025-2029 of the National Assembly Plenary",
              "Continuación de la Sesión No. 113-AN-2025-2029 del pleno de la Asamblea Nacional"):
        assert C(t, "EC") == TIPO_PLENO_EC, t
    assert C("Sesión Solemne de la Asamblea Nacional - Día de la Fundación", "EC") is None
    assert C("Comisión de Salud - Asamblea", "EC") is None
    assert C("Sesion del Pleno del Senado de la Republica") == "Pleno: Senado"


def test_clasificar_mesas():
    # Mesas/foros sin "comision" en el titulo: solo pasan si el tema es de Bayer.
    assert C("🔴EN VIVO: Mesa de trabajo “Proposición Legislativa Acceso a Medicamentos” l 23/09/2026"
             ) == "Comision: Mesa de trabajo Salud"
    assert C("EN VIVO: Foro sanidad agraria y plaguicidas") == "Comision: Mesa de trabajo Agro"
    assert C("EN VIVO: Mesa de trabajo “Sindicato SUNAFIL”") is None
    assert C("Mesa de trabajo “Validación del proyecto de Ley de acoso”") is None
    assert C("Campaña de vacunación en el Congreso") is None


class _FakeYdl:
    def __init__(self, extract):
        self.extract_info = extract

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_esta_en_vivo_cachea_fallo_corto_y_exito_largo(monkeypatch):
    llamadas = {"n": 0}

    def extract(url, download=False):
        llamadas["n"] += 1
        if llamadas["n"] == 1:
            raise RuntimeError("Sign in to confirm you're not a bot")
        return {"is_live": True}

    monkeypatch.setattr(det, "_ydl", lambda opts: _FakeYdl(extract))
    det._cache_en_vivo.clear()
    assert det._esta_en_vivo("X1") is False and llamadas["n"] == 1
    # Vencido el TTL de fallo (corto), reintenta.
    ts, res, ok = det._cache_en_vivo["X1"]
    det._cache_en_vivo["X1"] = (ts - det.FAIL_CACHE_TTL_SEG - 1, res, ok)
    assert det._esta_en_vivo("X1") is True and llamadas["n"] == 2
    # Un exito reciente sale del cache.
    assert det._esta_en_vivo("X1") is True and llamadas["n"] == 2
    det._cache_en_vivo.clear()


def test_vivos_de_interes_usa_live_status_del_flat(monkeypatch):
    # Solo cae al extract completo si el entry no trae live_status.
    c = {"title": "Comision de Salud en vivo", "_tipo": "Comision: Salud", "_pais": "PE"}
    entries = [
        {**c, "id": "A", "live_status": "is_live"},
        {**c, "id": "B", "live_status": "is_upcoming"},
        {**c, "id": "C", "live_status": "was_live"},
        {**c, "id": "D", "live_status": None},
    ]
    llamadas = []
    monkeypatch.setattr(det, "_streams_recientes", lambda: entries)
    monkeypatch.setattr(det, "_esta_en_vivo", lambda vid: llamadas.append(vid) or vid == "D")
    vivos = det.vivos_de_interes()
    assert llamadas == ["D"]
    assert {v["id"] for v in vivos} == {"A", "D"}


def test_rotar_warp_respeta_tope(monkeypatch):
    assert det.es_bloqueo_bot("ERROR: Sign in to confirm you're not a bot")
    assert det.es_bloqueo_bot("HTTP Error 429: Too Many Requests")
    assert not det.es_bloqueo_bot("Video unavailable")
    monkeypatch.setattr(det, "_rotaciones_warp", 0)
    with patch.dict(os.environ, {}, clear=True):
        assert det.rotar_warp() is False
    llamadas = []
    monkeypatch.setenv("YT_DLP_PROXY", "socks5://127.0.0.1:40000")
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/warp-cli")
    monkeypatch.setattr("subprocess.run", lambda args, **kw: llamadas.append(args))
    monkeypatch.setattr(det.time, "sleep", lambda s: None)
    rotaciones = [det.rotar_warp() for _ in range(det.MAX_ROTACIONES_WARP + 2)]
    assert rotaciones == [True] * det.MAX_ROTACIONES_WARP + [False, False]
    assert ["warp-cli", "--accept-tos", "proxy", "port", "40000"] in llamadas


def test_con_rotacion_warp_reintenta_solo_bloqueos(monkeypatch):
    rotaciones = iter([True, False])
    monkeypatch.setattr(det, "rotar_warp", lambda: next(rotaciones))
    resultados = iter(["not a bot", "not a bot"])
    # Reintenta una vez (rota), la segunda ya no puede rotar y devuelve lo que hay.
    assert det.con_rotacion_warp(lambda: next(resultados), error_de=lambda r: r) == "not a bot"
    # Un error que no es bloqueo se devuelve sin reintentar.
    assert det.con_rotacion_warp(lambda: "Video unavailable", error_de=lambda r: r) == "Video unavailable"
