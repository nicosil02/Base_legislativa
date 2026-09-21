"""Almacenamiento de descartes de noticias (boton "Descartar" en
pages/5_Noticias_PE.py y pages/6_Noticias_EC.py) - mismo backend (GitHub
Contents API) y mismo patron que clasificador/decisiones_store.py.

Por que existe: las paginas de Noticias abren proyectos.db en modo
READ-ONLY/immutable, y el descarte se escribia directo a una copia LOCAL
del archivo. En Streamlit Cloud ese proyectos.db es efimero - se
reconstruye desde data/proyectos.db.gz en cada redeploy (ver
_bootstrap_dbs_impl en app.py), y el repo recibe pushes automaticos cada
~10 min (refrescar-pe.yml corre cada hora via el trigger + los workflows
de auto-refresh de PLs corren mas seguido), asi que la tabla
noticias_feedback local se perdia en minutos - reproducido en vivo
2026-09-21 (Nicolas: "vengo descartando varias y nada"). En cambio: la UI
registra el descarte en este JSON chico, versionado en git (source of
truth), y load_noticias() lo lee para excluir esos ids del resultado.
"""
from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

FEEDBACK_PATH = "data/noticias_feedback.json"
CACHE_TTL_SECONDS = 30
_cache = {"descartes": None, "fetched_at": 0}


def _local_path() -> Path:
    return Path(__file__).resolve().parent.parent / FEEDBACK_PATH


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _gh_config() -> dict:
    return {
        "token": os.environ.get("GH_TOKEN"),
        "repo": os.environ.get("GH_REPO"),
        "branch": os.environ.get("GH_BRANCH", "main"),
    }


def _fetch_remote() -> dict | None:
    cfg = _gh_config()
    if not cfg["token"] or not cfg["repo"]:
        return None
    url = (
        "https://api.github.com/repos/" + cfg["repo"]
        + "/contents/" + FEEDBACK_PATH
        + "?ref=" + cfg["branch"]
    )
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": "Bearer " + cfg["token"],
            "Accept": "application/vnd.github+json",
            "User-Agent": "ValiIntelligence/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        body = base64.b64decode(data.get("content", "")).decode("utf-8")
        return {"descartes": json.loads(body), "sha": data.get("sha")}
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {"descartes": [], "sha": None}
        return None
    except Exception:
        return None


def _read_local() -> dict:
    p = _local_path()
    if not p.exists():
        return {"descartes": [], "sha": None}
    try:
        return {"descartes": json.loads(p.read_text(encoding="utf-8")), "sha": None}
    except Exception:
        return {"descartes": [], "sha": None}


def list_descartadas() -> set[int]:
    """IDs de noticias descartadas desde la UI. Cache corto (30s) para no
    golpear la API de GitHub en cada rerun de Streamlit."""
    now = time.time()
    if _cache["descartes"] is not None and (now - _cache["fetched_at"]) < CACHE_TTL_SECONDS:
        state = _cache["descartes"]
    else:
        state = _fetch_remote() or _read_local()
        _cache["descartes"] = state
        _cache["fetched_at"] = now
    return {int(d["noticia_id"]) for d in state["descartes"]}


def registrar_descarte(noticia_id: int, descartado_por: str | None = None) -> bool:
    """Idempotente - descartar 2 veces la misma noticia no duplica."""
    cfg = _gh_config()
    usar_gh = bool(cfg["token"] and cfg["repo"])
    remote = _fetch_remote() if usar_gh else None
    state = remote or _read_local()
    descartes = state["descartes"]

    if any(d.get("noticia_id") == noticia_id for d in descartes):
        return True
    descartes.append({
        "noticia_id": int(noticia_id), "created_at": _now_iso(),
        "descartado_por": descartado_por,
    })

    new_content = json.dumps(descartes, ensure_ascii=False, indent=2)

    if not usar_gh:
        p = _local_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(new_content, encoding="utf-8")
        _cache["descartes"] = {"descartes": descartes, "sha": None}
        _cache["fetched_at"] = time.time()
        return True

    body = {
        "message": f"noticias: descartar {noticia_id}",
        "content": base64.b64encode(new_content.encode("utf-8")).decode("ascii"),
        "branch": cfg["branch"],
    }
    if state.get("sha"):
        body["sha"] = state["sha"]
    url = "https://api.github.com/repos/" + cfg["repo"] + "/contents/" + FEEDBACK_PATH
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"), method="PUT",
        headers={
            "Authorization": "Bearer " + cfg["token"],
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "ValiIntelligence/1.0",
        },
    )
    try:
        urllib.request.urlopen(req, timeout=15)
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError("GitHub PUT failed: " + str(e.code) + " " + err_body[:300]) from None
    # Bug real 2026-09-21 (Nicolas: "el boton de descartar demora
    # muchisimo en aplicar"): invalidar el cache aca forzaba un TERCER
    # round-trip a la API de GitHub (GET) en el siguiente
    # list_descartadas(), que Streamlit dispara de inmediato via
    # st.rerun() - 3 llamadas de red seguidas por un solo click. Ya
    # tenemos el contenido posterior al PUT en memoria (`descartes`), asi
    # que lo cacheamos directo en vez de invalidar. El "sha" no hace
    # falta aca - list_descartadas() nunca lo usa, y registrar_descarte()
    # siempre pide uno fresco antes de escribir (no confia en el cache
    # para eso).
    _cache["descartes"] = {"descartes": descartes, "sha": None}
    _cache["fetched_at"] = time.time()
    return True


# ============================================================
# self-check (Ponytail: 1 chequeo ejecutable de la logica no trivial)
# ============================================================

def _demo():
    import tempfile

    global _local_path
    old_token = os.environ.pop("GH_TOKEN", None)
    old_local_path = _local_path
    tmpdir = tempfile.mkdtemp()
    fake_path = Path(tmpdir) / "data" / "noticias_feedback.json"
    _local_path = lambda: fake_path  # noqa: E731

    try:
        _cache["descartes"] = None
        _cache["fetched_at"] = 0

        assert registrar_descarte(101, descartado_por="nico")
        assert list_descartadas() == {101}
        print("OK registrar_descarte: crea un descarte nuevo")

        registrar_descarte(101, descartado_por="nico")  # repetido
        assert list_descartadas() == {101}, "no debe duplicar la misma noticia_id"
        print("OK registrar_descarte: idempotente, no duplica")

        registrar_descarte(202)
        assert list_descartadas() == {101, 202}
        print("OK list_descartadas: acumula varios ids")
    finally:
        _local_path = old_local_path
        if old_token is not None:
            os.environ["GH_TOKEN"] = old_token


def _test_registrar_descarte_gh_no_refetch_extra():
    """Bug real 2026-09-21 (Nicolas: "el boton de descartar demora
    muchisimo en aplicar"): un registrar_descarte() exitoso invalidaba el
    cache (ponia None) en vez de actualizarlo, forzando un GET extra en
    el list_descartadas() inmediato - que Streamlit dispara via
    st.rerun() apenas se descarta algo - 3 llamadas de red (GET+PUT+GET)
    por un solo click. Ahora el cache queda poblado directo con el
    resultado ya conocido tras el PUT: 2 llamadas por click, no 3."""
    from unittest.mock import patch

    old_token = os.environ.get("GH_TOKEN")
    old_repo = os.environ.get("GH_REPO")
    os.environ["GH_TOKEN"] = "fake-token"
    os.environ["GH_REPO"] = "fake/repo"
    _cache["descartes"] = None
    _cache["fetched_at"] = 0

    llamadas = []
    contenido_remoto = base64.b64encode(b"[]").decode("ascii")

    def _fake_urlopen(req, timeout=None):
        llamadas.append(req.get_method())
        if req.get_method() == "PUT":
            return type("R", (), {"__enter__": lambda s: s, "__exit__": lambda *a: None})()
        body = json.dumps({"content": contenido_remoto, "sha": "abc123"}).encode()
        return type("R", (), {
            "__enter__": lambda s: s, "__exit__": lambda *a: None,
            "read": lambda s: body,
        })()

    try:
        with patch("noticias.feedback_store.urllib.request.urlopen", side_effect=_fake_urlopen):
            assert registrar_descarte(303, descartado_por="nico")
            assert len(llamadas) == 2, f"esperaba GET+PUT, hubo {llamadas}"
            assert list_descartadas() == {303}
            assert len(llamadas) == 2, (
                "list_descartadas() no deberia pegarle a la red de nuevo - "
                "el cache ya tiene el resultado del PUT")
        print("OK registrar_descarte: no fuerza un 3er round-trip a GitHub en el rerun inmediato")
    finally:
        if old_token is None:
            os.environ.pop("GH_TOKEN", None)
        else:
            os.environ["GH_TOKEN"] = old_token
        if old_repo is None:
            os.environ.pop("GH_REPO", None)
        else:
            os.environ["GH_REPO"] = old_repo
        _cache["descartes"] = None
        _cache["fetched_at"] = 0


if __name__ == "__main__":
    _demo()
    _test_registrar_descarte_gh_no_refetch_extra()
