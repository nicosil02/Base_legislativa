"""Scrapeo de grupos de unificacion del portal Ppless v2.

El portal expone los grupos de unificacion de forma estructurada cuando
se activa el toggle "Unificados" en los filtros del tab 2.0. La tabla
filtrada muestra 7 columnas:

  Fecha de unificacion | Proyecto de Ley Unificado | N. Tramite |
  Proyectos que dan origen al unificado | Comision | Estado | Docs

Donde "Proyectos que dan origen al unificado" lista los N. Tramite de
todos los PLs miembros, con formato:
  "Tramite:472651/PROYECTO DE LEY .../ APELLIDO NOMBRE(ASAMBLEISTA)
   Tramite:476644/PROYECTO DE LEY .../ APELLIDO NOMBRE(ASAMBLEISTA)"

Este script automatiza el mismo flow que Claude in Chrome MCP hacia
manualmente:
  1. Goto portal Ppless v2
  2. Click tab "CONSULTA DE PROYECTOS DE LEY 2.0"
  3. Click toggle "Unificados"
  4. Click "Buscar"
  5. Iterar todas las paginas, extraer grupos y miembros
  6. Upsert en unificacion_grupos + unificacion_pl con source='portal'

Uso:
  python -m scraper_ec.cli scrapear-unificados [--no-headless] [--max-pages N]
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

from scraper_ec.db import Database

log = logging.getLogger(__name__)

PORTAL_URL = "https://proyectosdeley.asambleanacional.gob.ec/report"

# Selectores
SEL_TAB_20 = "text=CONSULTA DE PROYECTOS DE LEY 2.0"
# Toggle "Unificados" — mat-slide-toggle de Angular Material
SEL_TOGGLE_UNIFICADOS = 'mat-slide-toggle:has-text("Unificados"), label:has-text("Unificados")'
SEL_BTN_BUSCAR = 'button:has-text("Buscar"):not(:has-text("Limpiar"))'
SEL_BTN_LIMPIAR = 'button:has-text("Limpiar"):not(:has-text("Buscar"))'
SEL_PAGINATOR_NEXT = (
    'mat-paginator button.mat-paginator-navigation-next:not([disabled]), '
    'mat-paginator button.mat-mdc-paginator-navigation-next:not([disabled])'
)

# Regex para extraer n_tramite de "Tramite:472651/..."
TRAMITE_PAT = re.compile(r"Tr[áa]mite:\s*(\d+)", re.IGNORECASE)


def _click_y_esperar(page, selector: str, timeout: int = 15000) -> bool:
    """Click + wait for stable. Devuelve True si fue exitoso."""
    try:
        page.wait_for_selector(selector, timeout=timeout)
        page.click(selector)
        return True
    except PWTimeout:
        log.error("timeout clickeando selector: %s", selector)
        return False


def _navegar_a_unificados(page) -> bool:
    """Carga el portal, entra al tab 2.0 y activa el filtro Unificados."""
    # 1. Goto con retry
    for attempt in (1, 2, 3):
        try:
            page.goto(PORTAL_URL, timeout=60000, wait_until="domcontentloaded")
            break
        except PWTimeout as e:
            log.warning("[goto retry %d/3] %s", attempt, e)
    else:
        log.error("no pude cargar el portal")
        return False

    # 2. Click tab 2.0
    if not _click_y_esperar(page, SEL_TAB_20, timeout=20000):
        return False
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except PWTimeout:
        page.wait_for_timeout(3000)

    # 3. Limpiar filtros previos
    try:
        if page.locator(SEL_BTN_LIMPIAR).count() > 0:
            page.click(SEL_BTN_LIMPIAR)
            page.wait_for_timeout(500)
    except Exception:
        pass

    # 4. Click toggle Unificados (puede estar en varios formatos)
    toggle_selectors = [
        'mat-slide-toggle:has-text("Unificados")',
        'label:has-text("Unificados")',
        'span:has-text("Unificados")',
    ]
    toggled = False
    for sel in toggle_selectors:
        try:
            if page.locator(sel).count() > 0:
                page.locator(sel).first.click()
                toggled = True
                break
        except Exception as e:
            log.debug("toggle selector %s fallo: %s", sel, e)
    if not toggled:
        log.error("no encontre el toggle 'Unificados' en la pagina")
        return False

    page.wait_for_timeout(500)

    # 5. Click Buscar
    if not _click_y_esperar(page, SEL_BTN_BUSCAR, timeout=10000):
        return False

    # 6. Esperar a que la tabla unificados cargue
    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except PWTimeout:
        pass
    page.wait_for_timeout(2500)
    return True


def _extraer_pagina_actual(page) -> list[dict]:
    """Extrae los grupos visibles en la pagina actual de la tabla unificados.

    La tabla tiene 7 td por fila:
      [0] fecha_unif, [1] titulo, [2] n_tramite_principal,
      [3] miembros (texto multiline), [4] comision, [5] estado, [6] docs
    """
    # Usar evaluate para extraer todo via JS — mas robusto que iterar locators
    js = """
    (() => {
      const rows = document.querySelectorAll('table tbody tr');
      const visibles = Array.from(rows).filter(r => {
        const cells = r.querySelectorAll('td');
        return cells.length === 7 && r.offsetParent !== null;
      });
      return visibles.map(r => {
        const c = Array.from(r.querySelectorAll('td'));
        return {
          fecha_unif: c[0]?.innerText?.trim() || '',
          titulo: c[1]?.innerText?.trim() || '',
          n_tramite_principal: c[2]?.innerText?.trim() || '',
          miembros_raw: c[3]?.innerText || '',
          comision: c[4]?.innerText?.trim() || '',
          estado: c[5]?.innerText?.trim() || '',
        };
      });
    })()
    """
    grupos = page.evaluate(js)
    # Parsear miembros via regex
    for g in grupos:
        g["miembros"] = TRAMITE_PAT.findall(g.get("miembros_raw") or "")
        g.pop("miembros_raw", None)  # ya no la necesitamos
    return grupos


def _ir_a_siguiente_pagina(page) -> bool:
    """Click Next en el paginator. False si no hay mas paginas."""
    try:
        btn = page.locator(SEL_PAGINATOR_NEXT)
        if btn.count() == 0:
            return False
        btn.first.click()
        page.wait_for_timeout(900)
        return True
    except Exception as e:
        log.warning("click next fallo: %s", e)
        return False


def _upsert_grupo(db: Database, grupo: dict, existentes: set[str]) -> tuple[bool, int]:
    """Crea o re-crea un grupo source='portal'. Devuelve (creado_bool, n_miembros)."""
    principal = (grupo.get("n_tramite_principal") or "").strip()
    miembros = [str(m).strip() for m in (grupo.get("miembros") or []) if str(m).strip()]
    if not principal or not miembros:
        return False, 0

    # Solo incluir miembros que existan en proyectos (FK constraint)
    n_tramites = list(dict.fromkeys([principal] + miembros))
    n_validos = [n for n in n_tramites if n in existentes]
    if len(n_validos) < 2:
        return False, 0

    nombre = (grupo.get("titulo") or "")[:200]
    descripcion = (
        f"Estado: {grupo.get('estado', '?')} | "
        f"Comision: {grupo.get('comision', '?')} | "
        f"Fecha unif: {grupo.get('fecha_unif', '?')}"
    )
    db.crear_grupo_unificacion(
        n_tramites=n_validos,
        nombre=nombre,
        descripcion=descripcion,
        n_tramite_principal=principal if principal in existentes else n_validos[0],
        source="portal",
    )
    return True, len(n_validos)


def scrapear_unificados(
    db_path: str = "proyectos_ec.db",
    headless: bool = True,
    max_pages: int = 100,
) -> dict:
    """Itera el portal con el toggle Unificados activo y guarda los grupos.

    Antes de insertar nuevos grupos, BORRA todos los source='portal'
    anteriores. Asi el resultado refleja siempre el estado actual del portal.
    """
    db = Database(db_path)
    db.init_schema()

    # PLs existentes para validar FK
    existentes = {r[0] for r in db.conn.execute("SELECT n_tramite FROM proyectos")}
    log.info("PLs en DB: %d", len(existentes))

    # Borrar grupos source='portal' previos (re-import limpio)
    with db.tx() as c:
        old_ids = [r[0] for r in c.execute(
            "SELECT id FROM unificacion_grupos WHERE source = 'portal'"
        )]
        if old_ids:
            c.execute(
                f"DELETE FROM unificacion_grupos WHERE id IN ({','.join('?'*len(old_ids))})",
                old_ids,
            )
            c.execute(
                f"DELETE FROM unificacion_pl WHERE grupo_id IN ({','.join('?'*len(old_ids))})",
                old_ids,
            )
            log.info("borrados %d grupos source='portal' previos", len(old_ids))

    stats = {"paginas": 0, "grupos_creados": 0, "memberships": 0,
             "miembros_no_existentes": 0, "errores": 0}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        ctx = browser.new_context()
        page = ctx.new_page()

        log.info("Navegando al portal y activando filtro Unificados...")
        if not _navegar_a_unificados(page):
            log.error("no llegue a la vista de unificados")
            browser.close()
            db.close()
            stats["errores"] = 1
            return stats

        while stats["paginas"] < max_pages:
            stats["paginas"] += 1
            grupos = _extraer_pagina_actual(page)
            if not grupos and stats["paginas"] == 1:
                log.warning("primera pagina sin grupos — pude no estar en la vista correcta")
                break
            log.info("[pagina %d] %d grupos visibles", stats["paginas"], len(grupos))

            for g in grupos:
                try:
                    creado, n_miembros = _upsert_grupo(db, g, existentes)
                    if creado:
                        stats["grupos_creados"] += 1
                        stats["memberships"] += n_miembros
                        # Contar miembros que vinieron del portal pero no estan
                        # en la DB local (escaparon al sync de CSV)
                        miembros_raw = [g.get("n_tramite_principal")] + (g.get("miembros") or [])
                        stats["miembros_no_existentes"] += sum(
                            1 for m in miembros_raw if m and m not in existentes
                        )
                except Exception as e:
                    log.warning("error upsert grupo %s: %s",
                                g.get("n_tramite_principal"), e)
                    stats["errores"] += 1

            if not _ir_a_siguiente_pagina(page):
                log.info("no hay mas paginas (Next disabled)")
                break

        browser.close()

    db.close()
    log.info(
        "Terminado: paginas=%d grupos=%d memberships=%d "
        "miembros_no_en_db=%d errores=%d",
        stats["paginas"], stats["grupos_creados"], stats["memberships"],
        stats["miembros_no_existentes"], stats["errores"],
    )
    return stats
