"""Cliente del API spley-portal-service del Congreso del Perú.

El endpoint de detalle (`/expediente/{enc(perParId)}/{enc(pleyNum)}`) requiere
cifrar ambos parámetros con AES-128-ECB + PKCS7, codificados en base64 url-safe
sin padding. La clave (`ENCRYPTION_KEY`) se extrajo del bundle Angular del SPA.
"""
from __future__ import annotations

import base64
import logging
import time
from typing import Any, Iterator

import requests
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

log = logging.getLogger(__name__)

API_BASE = "https://api.congreso.gob.pe/spley-portal-service"
PORTAL_BASE = "https://wb2server.congreso.gob.pe/spley-portal"
ENCRYPTION_KEY = b"ProdALg5ZrAsxBMD"  # 16 bytes -> AES-128

DEFAULT_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (proyectos-ley-scraper)",
    "Origin": "https://wb2server.congreso.gob.pe",
    "Referer": "https://wb2server.congreso.gob.pe/spley-portal/",
}


def _aes_encrypt(value: str | int) -> str:
    cipher = AES.new(ENCRYPTION_KEY, AES.MODE_ECB)
    ct = cipher.encrypt(pad(str(value).encode("utf-8"), AES.block_size))
    return (
        base64.b64encode(ct)
        .decode("ascii")
        .replace("+", "-")
        .replace("/", "_")
        .rstrip("=")
    )


PREFIJO_CAMARA = {"C": "congreso", "D": "diputados", "S": "senado"}


def portal_url(per_par_id: int, pley_num: int, cod_tipo_parl: str = "C") -> str:
    """URL del portal. Desde el período bicameral (2026-2031) el SPA usa rutas
    con prefijo de cámara (/congreso|diputados|senado/expediente/...) — sin el
    prefijo correcto, un PL de Diputados o Senado no resuelve. El período
    legacy (2021-2026, todo 'C') sigue usando la ruta plana sin prefijo, igual
    que siempre, para no romper links ya compartidos."""
    if per_par_id < 2026:
        return f"{PORTAL_BASE}/#/expediente/{per_par_id}/{pley_num}"
    prefijo = PREFIJO_CAMARA.get(cod_tipo_parl, "congreso")
    return f"{PORTAL_BASE}/#/{prefijo}/expediente/{per_par_id}/{pley_num}"


def pdf_url(proyecto_archivo_id: int) -> str:
    enc = base64.b64encode(str(proyecto_archivo_id).encode("ascii")).decode("ascii").rstrip("=")
    return f"{API_BASE}/archivo/{enc}/pdf"


class ApiClient:
    def __init__(self, timeout: float = 90.0, request_delay: float = 0.1, max_retries: int = 3):
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
                log.warning("Request %s %s falló (intento %d/%d): %s — retry en %ss",
                            method, url, attempt + 1, self.max_retries, e, wait)
                time.sleep(wait)
        raise RuntimeError(f"Falló {method} {url} tras {self.max_retries} intentos: {last_err}")

    def list_comisiones(self) -> list[dict]:
        body = self._request("GET", "/comisiones")
        return body.get("data") or []

    def list_all_proyectos(
        self,
        per_par_id: int,
        comision_id: int | None = None,
        cod_tipo_parl: str | None = None,
    ) -> list[dict]:
        """El API ignora `rows`/`first` y devuelve todos los proyectos del período
        en una sola respuesta. Hacemos una sola llamada.

        `cod_tipo_parl` filtra por cámara: 'C' (Congreso/general — Ejecutivo,
        Comisión Permanente), 'D' (Cámara de Diputados), 'S' (Senado). Período
        bicameral (perParId>=2026): SIN este filtro el API devuelve SOLO 'C'
        (verificado 2026-09-11: con {perParId:2026} pelado salían 4 PLs; con
        codTipoParl='D' salen 195, con 'S' salen 7 — se pierden casi todos los
        proyectos si no se pasa). Período legacy (2021-2026): todo es 'C',
        pasar cod_tipo_parl=None u omitirlo trae todo igual que antes."""
        payload: dict[str, Any] = {"perParId": per_par_id, "first": 0, "rows": 99999}
        if comision_id is not None:
            payload["comisionId"] = comision_id
        if cod_tipo_parl is not None:
            payload["codTipoParl"] = cod_tipo_parl
        body = self._request("POST", "/proyecto-ley/lista-con-filtro", json=payload)
        return (body.get("data") or {}).get("proyectos") or []

    def iter_proyectos(
        self,
        per_par_id: int,
        comision_id: int | None = None,
        cod_tipo_parl: str | None = None,
        **_,
    ) -> Iterator[dict]:
        yield from self.list_all_proyectos(per_par_id, comision_id=comision_id, cod_tipo_parl=cod_tipo_parl)

    def get_expediente(self, per_par_id: int, pley_num: int, cod_tipo_parl: str = "C") -> dict:
        """`cod_tipo_parl` es requerido por el API para expedientes del período
        bicameral (el SPA lo manda como query param, default 'C' si se omite —
        pedir el detalle de un PL de Diputados/Senado sin esto devuelve el
        expediente equivocado o vacío)."""
        a = _aes_encrypt(per_par_id)
        b = _aes_encrypt(pley_num)
        body = self._request(
            "GET", f"/expediente/{a}/{b}", params={"codTipoParl": cod_tipo_parl},
        )
        return body.get("data") or {}
