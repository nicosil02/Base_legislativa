"""Scrapeo del flag 'Unificado' del listado del portal Ppless v2.

Reusa el flow de navegacion de playwright_detail.py (que SI llega al
tab CONSULTA DE PROYECTOS DE LEY 2.0). Diferencia: en lugar de filtrar
por N. Tramite y abrir cada modal, itera todas las paginas y lee la
columna "Unificado" de cada fila.

Uso:
  python -m scraper_ec.cli scrapear-unificados [--no-headless] [--limit N]
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

from scraper_ec.db import Database

log = logging.getLogger(__name__)

PORTAL_URL = "https://proyectosdeley.asambleanacional.gob.ec/report"

# Selectores (mismos que playwright_detail.py para consistencia)
SEL_TAB_20 = "text=CONSULTA DE PROYECTOS DE LEY 2.0"
SEL_BTN_LIMPIAR = 'button:has-text("Limpiar"):not(:has-text("Buscar"))'

# Patron del N. Tramite: numerico (480824) o alfanumerico (AN-XXX-2024-1234-M)
PAT_N_TRAMITE = re.compile(r"^(?:\d{6}|AN-[A-Z]+-\d{4}-\d{4,5}-[A-Z])$")


def _click_tab_y_esperar(page) -> bool:
    """Navega al portal y entra al tab 2.0. Devuelve True si llego OK."""
    loaded = False
    for attempt in (1, 2, 3):
        try:
            page.goto(PORTAL_URL, timeout=60000, wait_until="domcontentloaded")
            loaded = True
            break
        except PWTimeout as e:
            log.warning("[goto retry %d/3] %s", attempt, e)
    if not loaded:
        return False

    try:
        page.wait_for_selector(SEL_TAB_20, timeout=20000)
        page.click(SEL_TAB_20)
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except PWTimeout:
            page.wait_for_timeout(3000)
    except PWTimeout:
        log.error("Timeout esperando tab 2.0")
        return False

    # Limpiar filtros previos si quedaron de una corrida anterior
    try:
        if page.locator(SEL_BTN_LIMPIAR).count() > 0:
            page.click(SEL_BTN_LIMPIAR)
            page.wait_for_timeout(500)
    except Exception:
        pass

    # Esperar que la tabla cargue
    page.wait_for_timeout(2500)
    return True


def _detectar_columna_unificado(page) -> int | None:
    """Inspecciona el thead para encontrar el indice de la columna
    'Unificado'. Devuelve el index (0-based) o None si no la encuentra."""
    try:
        headers = page.locator("table thead th").all()
        for i, h in enumerate(headers):
            txt = (h.inner_text() or "").strip().lower()
            if "unif" in txt:
                log.info("columna 'Unificado' encontrada en posicion %d (texto: %r)", i, txt)
                return i
    except Exception as e:
        log.warning("error inspeccionando headers: %s", e)
    return None


def _leer_pagina(page, col_unif_idx: int) -> list[tuple[str, bool]]:
    """Lee todas las filas visibles de la tabla. Devuelve list de
    (n_tramite, marcado_unificado)."""
    out: list[tuple[str, bool]] = []
    rows = page.locator("table tbody tr").all()
    if not rows:
        # Fallback: a veces mat-table usa tr.mat-mdc-row sin tbody
        rows = page.locator("tr.mat-mdc-row, tr.mat-row").all()
    for row in rows:
        try:
            cells = row.locator("td").all()
            if len(cells) <= col_unif_idx:
                continue
            # Buscar n_tramite en alguna celda
            n_tramite = None
            for cell in cells:
                txt = (cell.inner_text() or "").strip()
                if PAT_N_TRAMITE.match(txt):
                    n_tramite = txt
                    break
            if not n_tramite:
                continue
            # Estado del checkbox en la celda de "Unificado"
            unif_cell = cells[col_unif_idx]
            html = unif_cell.inner_html()
            # Multiples indicadores posibles segun como Angular Material renderice
            marcado = (
                "mat-checkbox-checked" in html
                or "mat-mdc-checkbox-checked" in html
                or 'aria-checked="true"' in html
                or 'class="checked"' in html
                or "checkbox checked" in html.lower()
            )
            # Tambien probar el input directo
            if not marcado:
                inputs = unif_cell.locator("input[type='checkbox']").all()
                for inp in inputs:
                    checked = inp.evaluate("el => el.checked")
                    if checked:
                        marcado = True
                        break
            out.append((n_tramite, marcado))
        except Exception as e:
            log.warning("error fila: %s", e)
    return out


def _ir_a_siguiente_pagina(page) -> bool:
    """Click en el boton 'Next' del paginator Angular Material. Devuelve
    True si avanzo, False si no hay mas paginas."""
    selectors = [
        'button.mat-mdc-paginator-navigation-next:not([disabled])',
        'button.mat-paginator-navigation-next:not([disabled])',
        'button[aria-label="Next page"]:not([disabled])',
        'button[aria-label="Página siguiente"]:not([disabled])',
        'button[aria-label="Siguiente página"]:not([disabled])',
    ]
    for sel in selectors:
        btn = page.locator(sel)
        if btn.count() > 0:
            try:
                btn.first.click()
                page.wait_for_timeout(1200)
                return True
            except Exception as e:
                log.warning("click next fallo (%s): %s", sel, e)
                continue
    return False


def _seleccionar_max_rows(page) -> None:
    """Intenta cambiar el page size al maximo disponible para minimizar
    cantidad de paginas a iterar."""
    try:
        # Abrir el selector
        ps_sel = page.locator(
            ".mat-mdc-paginator-page-size-select, mat-form-field:has-text('Items per page')"
        )
        if ps_sel.count() == 0:
            return
        ps_sel.first.click()
        page.wait_for_timeout(400)
        # Elegir la opcion mayor
        opts = page.locator("mat-option").all()
        max_val = 0
        max_opt = None
        for o in opts:
            txt = (o.inner_text() or "").strip()
            try:
                v = int(txt)
                if v > max_val:
                    max_val = v
                    max_opt = o
            except ValueError:
                continue
        if max_opt:
            max_opt.click()
            page.wait_for_timeout(1500)
            log.info("page size cambiado a %d", max_val)
    except Exception as e:
        log.debug("no pude cambiar page size: %s", e)


def scrapear_unificados(
    db_path: str = "proyectos_ec.db",
    headless: bool = True,
    limit: int | None = None,
    sleep_ms: int = 600,
) -> dict:
    db = Database(db_path)
    db.init_schema()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    stats = {"vistas": 0, "marcados": 0, "paginas": 0, "errores": 0,
             "pls_unificados": []}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        ctx = browser.new_context()
        page = ctx.new_page()

        log.info("Cargando portal Ppless v2 y navegando al tab 2.0...")
        if not _click_tab_y_esperar(page):
            log.error("No pude llegar al tab 2.0")
            browser.close()
            stats["errores"] = 1
            return stats

        # Cambiar a max page size para iterar menos
        _seleccionar_max_rows(page)

        # Detectar columna Unificado en el thead
        col_idx = _detectar_columna_unificado(page)
        if col_idx is None:
            log.error("No encontre la columna 'Unificado' en el thead. "
                      "Headers visibles:")
            headers = page.locator("table thead th").all()
            for i, h in enumerate(headers):
                log.error("  [%d] %r", i, (h.inner_text() or "")[:50])
            log.error("Aborto. Corre con --no-headless para inspeccionar.")
            browser.close()
            stats["errores"] = 1
            return stats

        # Iterar paginas
        while True:
            stats["paginas"] += 1
            filas = _leer_pagina(page, col_idx)
            if not filas and stats["paginas"] == 1:
                log.warning("Primera pagina sin filas. Tabla puede estar vacia "
                            "o los selectores estan mal.")
            log.info("[pagina %d] leidas %d filas", stats["paginas"], len(filas))

            for n_tramite, marcado in filas:
                stats["vistas"] += 1
                if limit and stats["vistas"] > limit:
                    break
                try:
                    with db.tx() as c:
                        c.execute(
                            "UPDATE proyectos SET es_unificado=?, "
                            "unificado_at=? WHERE n_tramite=?",
                            (1 if marcado else 0,
                             now if marcado else None,
                             n_tramite),
                        )
                    if marcado:
                        stats["marcados"] += 1
                        stats["pls_unificados"].append(n_tramite)
                except Exception as e:
                    log.warning("UPDATE fallo para %s: %s", n_tramite, e)
                    stats["errores"] += 1

            if limit and stats["vistas"] >= limit:
                break
            if not _ir_a_siguiente_pagina(page):
                log.info("No hay mas paginas.")
                break
            if sleep_ms:
                page.wait_for_timeout(sleep_ms)

        browser.close()

    db.close()
    log.info(
        "Terminado: paginas=%d vistas=%d marcados=%d errores=%d",
        stats["paginas"], stats["vistas"], stats["marcados"], stats["errores"],
    )
    if stats["pls_unificados"]:
        muestra = stats["pls_unificados"][:30]
        log.info("PLs unificados (%d, muestra): %s",
                 len(stats["pls_unificados"]), ", ".join(muestra))
    return stats
