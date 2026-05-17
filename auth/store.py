"""Almacenamiento de usuarios registrados — backend GitHub Contents API.

El archivo `data/users.json` es la fuente de verdad. La app lee la copia
local en disk (snapshot del ultimo deploy). Cuando un usuario nuevo se
registra, la app:
  1. Append a la copia local en memoria.
  2. PUT a la GitHub Contents API → commit del nuevo users.json.
  3. Streamlit Cloud detecta el commit y redeploya.

Variables de entorno requeridas:
  GH_TOKEN     - PAT con permisos contents:write sobre el repo
  GH_REPO      - "owner/repo" del repo (ej: "nicosil02/Base_legislativa")
  GH_BRANCH    - rama default (ej: "main")
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


USERS_PATH = "data/users.json"
CACHE_TTL_SECONDS = 300
_cache = {"users": None, "fetched_at": 0}


def _local_path():
    return Path(__file__).resolve().parent.parent / USERS_PATH


def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _gh_config():
    return {
        "token": os.environ.get("GH_TOKEN"),
        "repo": os.environ.get("GH_REPO"),
        "branch": os.environ.get("GH_BRANCH", "main"),
    }


def _fetch_remote():
    """Lee users.json desde GitHub via la Contents API."""
    cfg = _gh_config()
    if not cfg["token"] or not cfg["repo"]:
        return None
    url = (
        "https://api.github.com/repos/" + cfg["repo"]
        + "/contents/" + USERS_PATH
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
        content_b64 = data.get("content", "")
        sha = data.get("sha")
        body = base64.b64decode(content_b64).decode("utf-8")
        return {"users": json.loads(body), "sha": sha}
    except Exception:
        return None


def _read_local():
    p = _local_path()
    if not p.exists():
        return {"users": [], "sha": None}
    try:
        return {"users": json.loads(p.read_text(encoding="utf-8")), "sha": None}
    except Exception:
        return {"users": [], "sha": None}


def list_users():
    """Devuelve la lista actual de usuarios. Cache 5 min."""
    now = time.time()
    if _cache["users"] is not None and (now - _cache["fetched_at"]) < CACHE_TTL_SECONDS:
        return _cache["users"]["users"]
    state = _fetch_remote() or _read_local()
    _cache["users"] = state
    _cache["fetched_at"] = now
    return state["users"]


def is_registered(email):
    email = email.lower().strip()
    return any(u.get("email", "").lower() == email for u in list_users())


def register(email):
    """Agrega un usuario nuevo a users.json. Devuelve True si commiteo."""
    email = email.lower().strip()
    if is_registered(email):
        return False
    cfg = _gh_config()
    if not cfg["token"] or not cfg["repo"]:
        # Sin creds GH — escribimos local (util en dev)
        p = _local_path()
        users = []
        if p.exists():
            try:
                users = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                pass
        users.append({"email": email, "registered_at": _now_iso()})
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(users, ensure_ascii=False, indent=2), encoding="utf-8")
        _cache["users"] = {"users": users, "sha": None}
        _cache["fetched_at"] = time.time()
        return True

    remote = _fetch_remote()
    sha = remote["sha"] if remote else None
    users = remote["users"] if remote else []
    if any(u.get("email", "").lower() == email for u in users):
        return False
    users.append({"email": email, "registered_at": _now_iso()})
    new_content = json.dumps(users, ensure_ascii=False, indent=2)
    body = {
        "message": "auth: registro de " + email,
        "content": base64.b64encode(new_content.encode("utf-8")).decode("ascii"),
        "branch": cfg["branch"],
    }
    if sha:
        body["sha"] = sha
    url = "https://api.github.com/repos/" + cfg["repo"] + "/contents/" + USERS_PATH
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        method="PUT",
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
    _cache["users"] = None
    _cache["fetched_at"] = 0
    return True
