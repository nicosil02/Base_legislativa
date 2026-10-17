"""Sesion HTTP con reintentos (urllib3 Retry) y un User-Agent de navegador."""
from __future__ import annotations

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def session(reintentos: int = 3, backoff: float = 1.0, ua: str = UA,
            metodos: frozenset[str] = frozenset({"GET", "HEAD", "POST"})) -> requests.Session:
    """Reintenta errores de conexion y 429/5xx con espera exponencial."""
    s = requests.Session()
    s.headers["User-Agent"] = ua
    retry = Retry(total=reintentos, backoff_factor=backoff, allowed_methods=metodos,
                  status_forcelist=(429, 500, 502, 503, 504), raise_on_status=False)
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.mount("http://", HTTPAdapter(max_retries=retry))
    return s
