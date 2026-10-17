"""Usuarios registrados en data/users.json, guardado vía core.store (commit
por la Contents API de GitHub con GH_TOKEN/GH_REPO/GH_BRANCH; sin ellos, el
archivo local)."""
from __future__ import annotations

from core import store
from core.db import now_iso

USERS_PATH = "data/users.json"
CACHE_TTL_SECONDS = 300


def list_users():
    """Lista actual de usuarios (cache de 5 min)."""
    return store.cargar(USERS_PATH, [], ttl=CACHE_TTL_SECONDS)


def is_registered(email):
    email = email.lower().strip()
    return any(u.get("email", "").lower() == email for u in list_users())


def register(email):
    """Agrega un usuario nuevo. True si lo guardó, False si ya estaba."""
    email = email.lower().strip()
    if is_registered(email):
        return False
    agregado = False

    def cambio(users):
        nonlocal agregado
        if any(u.get("email", "").lower() == email for u in users):
            return None
        agregado = True
        return users + [{"email": email, "registered_at": now_iso()}]

    store.actualizar(USERS_PATH, cambio, "auth: registro de " + email, [])
    return agregado
