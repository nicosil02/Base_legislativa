"""Grupos de unificacion del portal Ppless v2 (toggle "Unificados" del tab
2.0). La columna "Proyectos que dan origen al unificado" trae los miembros
como "Tramite:472651/PROYECTO DE LEY .../ ...".

    python -m scraper_ec.cli scrapear-unificados [--no-headless] [--max-pages N]
"""
from __future__ import annotations

import logging
import re

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

from scraper_ec.db import Database, now_iso as _now_iso
from scraper_ec.playwright_detail import SEL_BTN_BUSCAR, SEL_BTN_LIMPIAR, abrir_portal, esperar_red

log = logging.getLogger(__name__)

SEL_PAGINATOR_NEXT = (
    'mat-paginator button.mat-paginator-navigation-next:not([disabled]), '
    'mat-paginator button.mat-mdc-paginator-navigation-next:not([disabled])'
)

TRAMITE_PAT = re.compile(r"Tr[áa]mite:\s*(\d+)", re.IGNORECASE)


def _click_y_esperar(page, selector: str, timeout: int = 15000) -> bool:
    """True si el selector aparecio y se pudo clickear."""
    try:
        page.wait_for_selector(selector, timeout=timeout)
        page.click(selector)
        return True
    except PWTimeout:
        log.error("timeout clickeando selector: %s", selector)
        return False


def _navegar_a_unificados(page) -> bool:
    """Carga el portal, entra al tab 2.0 y activa el filtro Unificados."""
    if not abrir_portal(page):
        return False
    esperar_red(page)

    try:
        if page.locator(SEL_BTN_LIMPIAR).count() > 0:
            page.click(SEL_BTN_LIMPIAR)
            page.wait_for_timeout(500)
    except Exception:
        pass

    # El toggle aparece con distintas marcas segun la version del portal.
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

    if not _click_y_esperar(page, SEL_BTN_BUSCAR, timeout=10000):
        return False

    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except PWTimeout:
        pass
    page.wait_for_timeout(2500)
    return True


def _extraer_pagina_actual(page) -> list[dict]:
    """Grupos visibles en la pagina actual (filas de 7 celdas)."""
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
    for g in grupos:
        g["miembros"] = TRAMITE_PAT.findall(g.get("miembros_raw") or "")
        g.pop("miembros_raw", None)
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


def _upsert_grupo(db: Database, grupo: dict, existentes: set[str],
                   now_iso: str) -> tuple[bool, int, int]:
    """Crea un grupo source='portal'. Los miembros que no estan en la DB
    (PLs pre-2025) entran como filas stub para respetar la FK.
    Devuelve (creado, n_miembros, n_stubs)."""
    principal = (grupo.get("n_tramite_principal") or "").strip()
    miembros = [str(m).strip() for m in (grupo.get("miembros") or []) if str(m).strip()]
    if not principal or not miembros:
        return False, 0, 0

    n_tramites = list(dict.fromkeys([principal] + miembros))
    faltantes = [n for n in n_tramites if n not in existentes]

    stubs_creados = 0
    if faltantes:
        with db.tx() as c:
            for n in faltantes:
                c.execute(
                    """INSERT OR IGNORE INTO proyectos
                       (n_tramite, titulo, estado, fec_presentacion,
                        periodo, first_seen_at, last_seen_at, last_changed_at,
                        tema, tema_manual)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Otros', 0)""",
                    (n,
                     "(PL externo unificado - no en DB local)",
                     "EXTERNO",
                     "1900-01-01",
                     "pre-2025",
                     now_iso, now_iso, now_iso),
                )
                existentes.add(n)
                stubs_creados += 1

    nombre = (grupo.get("titulo") or "")[:200]
    descripcion = (
        f"Estado: {grupo.get('estado', '?')} | "
        f"Comision: {grupo.get('comision', '?')} | "
        f"Fecha unif: {grupo.get('fecha_unif', '?')}"
    )
    db.crear_grupo_unificacion(
        n_tramites=n_tramites,
        nombre=nombre,
        descripcion=descripcion,
        n_tramite_principal=principal,
        source="portal",
    )
    return True, len(n_tramites), stubs_creados


def scrapear_unificados(
    db_path: str = "proyectos_ec.db",
    headless: bool = True,
    max_pages: int = 100,
) -> dict:
    """Borra los grupos source='portal' y los vuelve a crear con lo que
    muestra hoy el portal."""
    db = Database(db_path)
    db.init_schema()

    existentes = {r[0] for r in db.conn.execute("SELECT n_tramite FROM proyectos")}
    log.info("PLs en DB: %d", len(existentes))

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
             "stubs_creados": 0, "errores": 0}
    now_iso = _now_iso()

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
                    creado, n_miembros, n_stubs = _upsert_grupo(
                        db, g, existentes, now_iso
                    )
                    if creado:
                        stats["grupos_creados"] += 1
                        stats["memberships"] += n_miembros
                        stats["stubs_creados"] += n_stubs
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
        "stubs_creados=%d errores=%d",
        stats["paginas"], stats["grupos_creados"], stats["memberships"],
        stats["stubs_creados"], stats["errores"],
    )
    return stats
