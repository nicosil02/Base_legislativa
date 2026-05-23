"""Scrapeo del flag 'Unificado' del listado del portal Ppless v2.

El portal de la Asamblea muestra una columna 'Unificado' al final de la
tabla con un checkbox por cada PL. Este script abre el portal, itera
todas las paginas, lee el estado del checkbox (marcado/no marcado), y
actualiza el flag `es_unificado` en proyectos.

NO captura "con cuales PLs esta unificado" porque esa info no esta en
la tabla — solo el sí/no. Para la vinculacion se usa el CLI manual
`marcar-unificacion`.

Uso:
  python -m scraper_ec.cli scrapear-unificados [--no-headless] [--limit N]
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

from scraper_ec.db import Database

log = logging.getLogger(__name__)

PORTAL_URL = "https://proyectosdeley.asambleanacional.gob.ec/report"
SEL_TAB_20 = "text=CONSULTA DE PROYECTOS DE LEY 2.0"
# Selector de las filas del listado (mat-table de Angular Material)
SEL_TABLE_ROWS = "table tr.mat-mdc-row, table tr.mat-row"
# Selector del paginator
SEL_NEXT_PAGE = 'button[aria-label="Next page"]:not([disabled])'
SEL_PAGINATOR_ITEM_RANGE = ".mat-mdc-paginator-range-label, .mat-paginator-range-label"


def scrapear_unificados(
    db_path: str = "proyectos_ec.db",
    headless: bool = True,
    limit: int | None = None,
    sleep_ms: int = 500,
) -> dict:
    """Itera todas las paginas del portal y actualiza es_unificado en la DB.

    Returns dict con stats: {vistas, marcados, paginas, errores}.
    """
    db = Database(db_path)
    db.init_schema()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    vistas = 0
    marcados = 0
    paginas = 0
    errores = 0
    pl_unificados: list[str] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        ctx = browser.new_context()
        page = ctx.new_page()

        log.info("Cargando portal Ppless v2...")
        loaded = False
        for attempt in (1, 2, 3):
            try:
                page.goto(PORTAL_URL, timeout=60000, wait_until="domcontentloaded")
                loaded = True
                break
            except PWTimeout as e:
                log.warning("[goto retry %d/3] %s", attempt, e)
        if not loaded:
            log.error("No pude cargar el portal. Abortando.")
            browser.close()
            return {"vistas": 0, "marcados": 0, "paginas": 0, "errores": 1}

        try:
            page.wait_for_selector(SEL_TAB_20, timeout=20000)
        except PWTimeout:
            log.error("No encontre el tab 'CONSULTA DE PROYECTOS DE LEY 2.0'")
            browser.close()
            return {"vistas": 0, "marcados": 0, "paginas": 0, "errores": 1}

        # Esperar a que la tabla se renderice
        page.wait_for_timeout(2000)

        while True:
            paginas += 1
            try:
                # Obtener todas las filas visibles
                rows = page.query_selector_all(SEL_TABLE_ROWS)
                if not rows:
                    log.warning("Pagina %d: sin filas detectadas", paginas)
                    break

                for row in rows:
                    vistas += 1
                    if limit and vistas > limit:
                        break
                    try:
                        # Extraer N. Tramite (columna 3 segun screenshot)
                        # Como las celdas pueden cambiar de orden, buscamos por
                        # ancho o por contenido tipo numero. Mejor: buscar la
                        # celda que matchee patron de n_tramite.
                        cells = row.query_selector_all("td")
                        n_tramite = None
                        # n_tramite es numerico (480824) o alfanumerico (AN-XXX-YYYY-NNNN-M)
                        import re
                        pat = re.compile(r"^(?:\d{6}|AN-[A-Z]+-\d{4}-\d{4}-[A-Z])$")
                        for cell in cells:
                            txt = (cell.inner_text() or "").strip()
                            if pat.match(txt):
                                n_tramite = txt
                                break
                        if not n_tramite:
                            continue

                        # Buscar checkbox de la columna "Unificado" (ultima col)
                        # La columna tiene mat-checkbox dentro
                        checkbox = row.query_selector(
                            'td:last-child input[type="checkbox"], '
                            'td:last-child mat-checkbox, '
                            'td.mat-column-unificado input, '
                            'td.mat-column-unificado'
                        )
                        if checkbox is None:
                            # Fallback: tomar el ultimo td y ver si tiene clase aria-checked=true
                            last_td = cells[-1] if cells else None
                            if last_td:
                                html = last_td.inner_html()
                                marcado = (
                                    'mat-checkbox-checked' in html
                                    or 'aria-checked="true"' in html
                                    or 'mat-mdc-checkbox-checked' in html
                                )
                            else:
                                marcado = False
                        else:
                            # Intentar leer estado
                            attr = (
                                checkbox.get_attribute("aria-checked")
                                or checkbox.get_attribute("checked")
                                or ""
                            )
                            marcado = attr.lower() in ("true", "checked")
                            if not marcado:
                                # Fallback por class
                                cls = checkbox.get_attribute("class") or ""
                                marcado = "checked" in cls.lower()

                        # Actualizar DB
                        with db.tx() as c:
                            c.execute(
                                "UPDATE proyectos SET es_unificado=?, unificado_at=? "
                                "WHERE n_tramite=?",
                                (1 if marcado else 0, now if marcado else None, n_tramite),
                            )
                        if marcado:
                            marcados += 1
                            pl_unificados.append(n_tramite)
                    except Exception as e:
                        errores += 1
                        log.warning("error fila: %s", e)

                # Avanzar a la siguiente pagina
                if limit and vistas >= limit:
                    break
                next_btn = page.query_selector(SEL_NEXT_PAGE)
                if not next_btn:
                    log.info("No hay mas paginas (boton Next disabled).")
                    break
                next_btn.click()
                page.wait_for_timeout(sleep_ms)

            except Exception as e:
                errores += 1
                log.warning("error pagina %d: %s", paginas, e)
                break

        browser.close()

    db.close()
    log.info(
        "Terminado: paginas=%d vistas=%d marcados=%d errores=%d",
        paginas, vistas, marcados, errores,
    )
    if pl_unificados:
        log.info("PLs marcados como unificados (%d): %s", len(pl_unificados),
                 ", ".join(pl_unificados[:20]))
    return {
        "vistas": vistas,
        "marcados": marcados,
        "paginas": paginas,
        "errores": errores,
        "pls_unificados": pl_unificados,
    }
