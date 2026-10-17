"""Archivos JSON del repo leidos y escritos con la Contents API de GitHub.

La app de Streamlit no puede escribir en disco de forma duradera (se borra en
cada redeploy), asi que lo que marca la gente desde la UI se guarda como un
commit. Sin GH_TOKEN/GH_REPO (desarrollo local) se usa el archivo local."""
from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.request
from typing import Any, Callable

from core.db import ROOT

_cache: dict[str, tuple[float, Any]] = {}


def _cfg() -> tuple[str, str, str] | None:
    token, repo = os.environ.get("GH_TOKEN"), os.environ.get("GH_REPO")
    return (token, repo, os.environ.get("GH_BRANCH", "main")) if token and repo else None


def _pedir(url: str, token: str, data: dict | None = None, timeout: int = 10):
    req = urllib.request.Request(
        url, data=json.dumps(data).encode() if data is not None else None,
        method="PUT" if data is not None else "GET",
        headers={"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json",
                 "Content-Type": "application/json", "User-Agent": "ValiIntelligence/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read() or b"{}")


def _leer_local(path: str, default: Any) -> Any:
    p = ROOT / path
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default
    except (OSError, ValueError):
        return default


def leer(path: str, default: Any) -> tuple[Any, str | None]:
    """(contenido, sha). Archivo que no existe en GitHub -> default. Si
    GitHub falla por otra razon, la copia local del repo."""
    cfg = _cfg()
    if cfg:
        token, repo, branch = cfg
        try:
            d = _pedir(f"https://api.github.com/repos/{repo}/contents/{path}?ref={branch}", token)
            return json.loads(base64.b64decode(d.get("content", "")).decode("utf-8")), d.get("sha")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return default, None
        except Exception:
            pass
    return _leer_local(path, default), None


def cargar(path: str, default: Any, ttl: float = 300) -> Any:
    """leer() con cache de `ttl` segundos (Streamlit relee en cada rerun)."""
    hit = _cache.get(path)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    data, _ = leer(path, default)
    _cache[path] = (time.time(), data)
    return data


def actualizar(path: str, cambio: Callable[[Any], Any], mensaje: str, default: Any) -> Any:
    """Lee lo ultimo, aplica `cambio(datos)` y lo guarda. Si `cambio`
    devuelve None no se escribe nada. Devuelve los datos finales.
    Levanta RuntimeError si GitHub rechaza la escritura."""
    data, sha = leer(path, default)
    nuevo = cambio(data)
    if nuevo is None:
        return data
    texto = json.dumps(nuevo, ensure_ascii=False, indent=2)
    cfg = _cfg()
    if cfg:
        token, repo, branch = cfg
        body = {"message": mensaje, "branch": branch,
                "content": base64.b64encode(texto.encode("utf-8")).decode("ascii")}
        if sha:
            body["sha"] = sha
        try:
            _pedir(f"https://api.github.com/repos/{repo}/contents/{path}", token, body, timeout=15)
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"GitHub PUT fallo: {e.code} "
                               f"{e.read().decode('utf-8', 'replace')[:300]}") from None
    else:
        p = ROOT / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(texto, encoding="utf-8")
    _cache[path] = (time.time(), nuevo)
    return nuevo
