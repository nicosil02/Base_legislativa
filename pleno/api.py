"""Cliente HTTP del backend adp-portal-service del Congreso (Agenda
Documentada del Pleno).

A diferencia del visor-sesiones de comisiones, esta API es publica y no
requiere Basic Auth. Endpoints relevantes:

  GET /visor/publicado              -> lista todas las agendas del Pleno
                                       (desde 2011 hasta hoy, agrupadas por
                                       periodo parlamentario).
  GET /visor/publicado/{codAgenda}  -> detalle completo de una agenda con
                                       secciones, subsecciones y temas. Cada
                                       tema referencia 1+ Proyecto de Ley con
                                       URL canonica al portal y resumen.

Base URL hardcoded en main.bundle.js del adp-portal:
  AppSettings.API_ENDPOINT = 'https://wb2server.congreso.gob.pe/adp-portal-service/api/'
"""
from __future__ import annotations

import logging
import time
from typing import Any

import requests

log = logging.getLogger(__name__)

API_BASE = "https://wb2server.congreso.gob.pe/adp-portal-service/api"

DEFAULT_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://wb2server.congreso.gob.pe/adp-portal/",
    "Origin": "https://wb2server.congreso.gob.pe",
    "User-Agent": "Mozilla/5.0 (radar-legislativo-pleno)",
}


class ApiClient:
    def __init__(self, timeout: float = 30.0, request_delay: float = 0.20,
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

    def list_agendas(self, periodo_filtro: str | None = "2021-2026") -> list[dict]:
        """Devuelve la lista plana de agendas del Pleno. Por default filtra al
        periodo parlamentario 2021-2026 (177 agendas) para coherencia con el
        resto de la app. Pasar `periodo_filtro=None` trae todo el historico
        desde 2011 (571 agendas, ~234 MB si se fetchea cada detalle).

        Cada item: {codAgenda, dPeriodo, dLegis, fecSesion, dTitulo, dUrl}.
        """
        body = self._request("GET", "/visor/publicado")
        grupos = body.get("data") or []
        result: list[dict] = []
        for g in grupos:
            periodo = g.get("periodo", "")
            if periodo_filtro and periodo_filtro not in periodo:
                continue
            for ag in (g.get("agendas") or []):
                result.append(ag)
        return result

    def get_agenda(self, cod_agenda: int) -> dict:
        """Detalle completo de una agenda del Pleno. Incluye secciones,
        subsecciones y temas (cada tema = 1 punto del orden del dia, con su
        PL referenciado y HTML rich de descripcion)."""
        body = self._request("GET", f"/visor/publicado/{cod_agenda}")
        return body.get("data") or {}
