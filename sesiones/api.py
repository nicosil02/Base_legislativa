"""Cliente HTTP del backend service-portal-publico-ext del Congreso.

Auth: Basic dXNlck5hbWVQb3J0YWw6cGFzc3dvcmRQb3J0YWw= (= userNamePortal:passwordPortal,
literal hardcoded en el bundle de la SPA visor-sesiones). Sin AES ni token
dinamico. El header es lo unico que el WAF chequea para distinguir trafico
"legitimo" del visor de un scraper externo.

Endpoints expuestos:
  GET /sesiones/criterios            -> catalogo (periodos, comisiones, tipos)
  GET /sesiones/busqueda?...         -> lista sesiones por periodo
  GET /sesiones/{id}                 -> detalle (con agenda HTML rich)
"""
from __future__ import annotations

import logging
import time
from typing import Any

import requests

log = logging.getLogger(__name__)

API_BASE = "https://wb2server.congreso.gob.pe/service-portal-publico-ext"
# Basic auth literal del bundle JS de la SPA visor-sesiones. Decodea a
# "userNamePortal:passwordPortal" — credenciales publicas usadas por la
# SPA, no son secretos.
AUTH_HEADER = "Basic dXNlck5hbWVQb3J0YWw6cGFzc3dvcmRQb3J0YWw="

DEFAULT_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Authorization": AUTH_HEADER,
    "Referer": "https://wb2server.congreso.gob.pe/visor-sesiones/",
    "Origin": "https://wb2server.congreso.gob.pe",
    "User-Agent": "Mozilla/5.0 (radar-legislativo-sesiones)",
}


class ApiClient:
    def __init__(self, timeout: float = 30.0, request_delay: float = 0.15,
                 max_retries: int = 3):
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self.timeout = timeout
        self.request_delay = request_delay
        self.max_retries = max_retries

    def _request(self, method: str, path: str, **kwargs) -> dict:
        url = f"{API_BASE}{path}"
        last_err: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                resp = self.session.request(method, url, timeout=self.timeout, **kwargs)
                resp.raise_for_status()
                if self.request_delay:
                    time.sleep(self.request_delay)
                return resp.json()
            except (requests.RequestException, ValueError) as e:
                last_err = e
                wait = 2 ** attempt
                log.warning("Request %s %s fallo (intento %d/%d): %s — retry en %ss",
                            method, url, attempt + 1, self.max_retries, e, wait)
                time.sleep(wait)
        raise RuntimeError(f"Fallo {method} {url} tras {self.max_retries} intentos: {last_err}")

    def get_criterios(self) -> dict:
        """Devuelve el catalogo: periodos parlamentarios, comisiones (24 ordinarias
        + investigadoras + especiales + SCAC + Comision Permanente), tipos.
        El dict tiene keys: periodosParlamentarios, comisiones, periodosAnuales,
        tipoComisiones.
        """
        body = self._request("GET", "/sesiones/criterios")
        return body.get("result") or {}

    def list_sesiones(
        self,
        periodo_parlamentario: int = 2021,
        periodo_legislativo: int = 2025,
        tipo_comision: str = "",
        comision: str | int = "",
        sesion: str = "",
        descentralizada: str = "",
        conjunta: str = "",
        continuada: str = "",
        fecha_inicio: str = "",  # formato YYYY-MM-DD
        fecha_fin: str = "",
        fecha: str = "",
    ) -> list[dict]:
        """Lista sesiones del periodo legislativo. Sin filtros = todas las del año.
        Cada item: idSesion, fecha (DD/MM/YYYY), horaInicio, horaFin, nombreSesion,
        nombreComision, tipoComision, estado, flags (descentralizada, conjunta,
        continuacion), caracteristicas.
        """
        params = {
            "periodoParlamentario": periodo_parlamentario,
            "periodoLegislativo": periodo_legislativo,
            "tipoComision": tipo_comision,
            "comision": comision,
            "sesion": sesion,
            "descentralizada": descentralizada,
            "conjunta": conjunta,
            "continuada": continuada,
            "fechaInicio": fecha_inicio,
            "fechaFin": fecha_fin,
            "fecha": fecha,
        }
        body = self._request("GET", "/sesiones/busqueda", params=params)
        return body.get("result") or []

    def get_sesion(self, id_sesion: int) -> dict:
        """Detalle completo de una sesion. Incluye agenda (HTML rich) en
        result.agenda.ordenesDia[].descripcion, link de Teams, idsAlfresco
        (UUID 36 chars) para acta/asistencia/agenda PDFs, URL de video."""
        body = self._request("GET", f"/sesiones/{id_sesion}")
        return body.get("result") or {}
