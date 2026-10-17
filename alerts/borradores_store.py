"""Borradores de alertas en `data/alertas_borradores.json`, guardados con
core.store (commit via la Contents API de GitHub; archivo local sin GH_TOKEN).

El repo es publico y este archivo queda en el historial de git (a diferencia
de clientes/); Nicolas lo aprobo el 2026-09-12.
"""
from __future__ import annotations

from core import store
from core.db import now_iso

BORRADORES_PATH = "data/alertas_borradores.json"
CACHE_TTL_SECONDS = 30


def list_borradores(cliente: str | None = None) -> list[dict]:
    """Los borradores guardados, mas nuevos primero. Cache corto para no
    golpear la API de GitHub en cada rerun de Streamlit."""
    items = store.cargar(BORRADORES_PATH, [], ttl=CACHE_TTL_SECONDS)
    if cliente:
        items = [b for b in items if b.get("cliente") == cliente]
    return sorted(items, key=lambda b: b.get("updated_at", ""), reverse=True)


def _upsert(*, cliente: str, item_id: str, item_tipo: str, pais: str,
            item_titulo: str, item_url: str | None, item_resumen: str | None,
            texto: str, estado: str, fuentes_adicionales: list[dict] | None = None,
            creado_por: str | None = None) -> bool:
    """Crea o actualiza la entrada (cliente, item_id). Un marcado nuevo
    ('pendiente') no pisa un 'borrador' ya redactado, y `creado_por` solo se
    setea al crear, para que la pagina de Borradores filtre "lo mio"."""
    def cambio(borradores):
        now = now_iso()
        existente = next((b for b in borradores
                          if b.get("cliente") == cliente and b.get("item_id") == item_id), None)
        if existente:
            if estado == "pendiente" and existente.get("estado") == "borrador":
                return None
            existente["texto"] = texto
            existente["estado"] = estado
            existente["updated_at"] = now
            if item_resumen:
                existente["item_resumen"] = item_resumen
            if fuentes_adicionales:
                existente["fuentes_adicionales"] = fuentes_adicionales
        else:
            borradores.append({
                "cliente": cliente, "item_id": item_id, "item_tipo": item_tipo,
                "pais": pais, "item_titulo": item_titulo, "item_url": item_url,
                "item_resumen": item_resumen, "texto": texto, "estado": estado,
                "creado_por": creado_por,
                "fuentes_adicionales": fuentes_adicionales or [],
                "created_at": now, "updated_at": now,
            })
        return borradores

    store.actualizar(BORRADORES_PATH, cambio, f"alertas: {estado} {cliente}/{item_id}", [])
    return True


def guardar_borrador(*, cliente: str, item_id: str, item_tipo: str, pais: str,
                     item_titulo: str, item_url: str | None, texto: str,
                     item_resumen: str | None = None) -> bool:
    """Guarda un borrador YA REDACTADO (a mano en la UI, o por el agente
    programado) - estado='borrador'. Clave logica: (cliente, item_id)."""
    return _upsert(cliente=cliente, item_id=item_id, item_tipo=item_tipo,
                   pais=pais, item_titulo=item_titulo, item_url=item_url,
                   item_resumen=item_resumen, texto=texto, estado="borrador")


def marcar_pendiente(*, clientes: list[str], item_id: str, item_tipo: str, pais: str,
                     item_titulo: str, item_url: str | None,
                     item_resumen: str | None = None,
                     fuentes_adicionales: list[dict] | None = None,
                     creado_por: str | None = None) -> bool:
    """Marca un item como 'vale la pena redactar una alerta' para cada
    cliente (estado='pendiente', texto vacio). El agente programado los
    redacta y los pasa a 'borrador' con `guardar_borrador`.

    `creado_por`: email de quien marco (None sin login).
    `fuentes_adicionales`: [{"item_titulo", "item_url"}] de contexto extra
    para el agente; la alerta solo cita la fuente principal."""
    ok = True
    for cliente in clientes:
        ok = _upsert(cliente=cliente, item_id=item_id, item_tipo=item_tipo,
                     pais=pais, item_titulo=item_titulo, item_url=item_url,
                     item_resumen=item_resumen, texto="", estado="pendiente",
                     fuentes_adicionales=fuentes_adicionales,
                     creado_por=creado_por) and ok
    return ok
