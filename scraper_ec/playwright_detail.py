"""Enriquecedor de documentos (PDFs) via Playwright.

Phase 0 mostró que la SPA Ppless v2 expone los PDFs vía:

  https://proyectosdeley.asambleanacional.gob.ec/fileservice/file/download
      ?fileName=<NOMBRE>.pdf&system=ppless&subDirectory=<NNNN>_task

Ese endpoint es PÚBLICO (HTTP 200 sin cookies/auth/CORS issues). Verificado
con `curl -I`. Una vez construido, el URL se puede linkear directamente
desde el dashboard y bajar el PDF en un click.

El catálogo `pplessservice2/` que la SPA usa para listar los archivos sí
requiere autenticación (zone.js + cookie de sesión). Por eso necesitamos
Playwright: abrimos el modal, capturamos los responses JSON del catálogo,
extraemos (filename, subDirectory) por archivo y construimos las URLs
del fileservice.

Uso:
    from scraper_ec.db import Database
    from scraper_ec.playwright_detail import enrich_documentos

    db = Database("proyectos_ec.db"); db.init_schema()
    enrich_documentos(db, n_tramites=["480824"], headless=True)

CLI:
    python -m scraper_ec.cli enriquecer-documentos --limit 20
"""
from __future__ import annotations

import json
import re
from typing import Callable, Iterable
from urllib.parse import quote

PORTAL_URL = "https://proyectosdeley.asambleanacional.gob.ec/report"
FILESERVICE = "https://proyectosdeley.asambleanacional.gob.ec/fileservice/file/download"

# Selectores reales del DOM de Ppless v2 (Streamlit 1.57 / Angular ~10)
# verificados con `playwright eval_on_selector_all`.
SEL_TAB_20 = "text=CONSULTA DE PROYECTOS DE LEY 2.0"
SEL_FILTER_TRAMITE = "input#procedure"
SEL_BTN_BUSCAR = 'button:has-text("Buscar"):not(:has-text("Limpiar"))'
SEL_BTN_LIMPIAR = 'button:has-text("Limpiar"):not(:has-text("Buscar"))'
SEL_FIND_IN_PAGE_ICON = 'mat-icon:has-text("find_in_page")'
SEL_MODAL = "mat-dialog-container"
SEL_MODAL_ATTACH = 'mat-dialog-container mat-icon:has-text("attach_file")'
SEL_MODAL_CLOSE = 'mat-dialog-container mat-icon:has-text("cancel")'

# URL pattern del API que retorna los archives (PDF metadata)
ARCHIVE_API_RE = re.compile(r"/archive/search/findAllByAttachment_Id\?id=\d+")


def _build_download_url(filename: str, subdir: str) -> str:
    """Construye la URL pública directa al PDF."""
    return (
        f"{FILESERVICE}"
        f"?fileName={quote(filename)}"
        f"&system=ppless"
        f"&subDirectory={quote(subdir)}"
    )


def _parse_archives_response(body: str) -> list[dict]:
    """Parsea la respuesta del API `archive/search/findAllByAttachment_Id`
    y devuelve una lista de dicts con {filename, subDirectory, attachment_id, fase_desc}."""
    try:
        data = json.loads(body)
    except Exception:
        return []
    items = (data.get("_embedded") or {}).get("pplessservices") or []
    out: list[dict] = []
    for it in items:
        filename = it.get("filename")
        url_path = (it.get("url") or "").strip("/")
        if not filename or not url_path:
            continue
        # url_path es típicamente "ppless/2343_task". Extraemos sólo subDirectory.
        parts = url_path.split("/", 1)
        subdir = parts[1] if len(parts) == 2 else url_path
        # La descripción / tipo de documento vive en attachment.description
        attachment = it.get("attachment") or {}
        descripcion = attachment.get("description") or it.get("description") or None
        out.append({
            "filename": filename,
            "subdirectory": subdir,
            "url": _build_download_url(filename, subdir),
            "descripcion": descripcion,
        })
    return out


def enrich_documentos(
    db,
    n_tramites: Iterable[str],
    *,
    headless: bool = True,
    skip_with_docs: bool = True,
    on_progress: Callable[[str, int, int], None] | None = None,
    timeout_ms: int = 30000,
    sleep_between_ms: int = 800,
) -> dict:
    """Itera sobre `n_tramites` y captura los PDFs de cada proyecto.

    Args:
        db: scraper_ec.db.Database (ya inicializada con init_schema)
        n_tramites: iterable de N. Trámite a enriquecer
        headless: True para producción, False para debug visual
        skip_with_docs: salta proyectos que ya tienen >=1 doc en la DB
        on_progress: callback(n_tramite, idx, total) por cada item
        timeout_ms: timeout por operación
        sleep_between_ms: pausa entre proyectos (rate limit)

    Returns:
        {"procesados", "con_docs", "sin_docs", "errores"}
    """
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    targets = list(n_tramites)
    if skip_with_docs:
        existing = {
            r[0]
            for r in db.conn.execute(
                "SELECT DISTINCT n_tramite FROM documentos"
            ).fetchall()
        }
        targets = [t for t in targets if t not in existing]

    stats = {"procesados": 0, "con_docs": 0, "sin_docs": 0, "errores": 0}
    if not targets:
        print("Nada que enriquecer (todos los proyectos ya tienen documentos).")
        return stats

    print(f"Enriquecer {len(targets)} proyectos (headless={headless})…")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()
        page.set_default_timeout(timeout_ms)

        # Buffer compartido de archives capturados desde el API. Cada response
        # del endpoint `archive/search/...` se agrega acá. Lo limpiamos entre
        # proyectos para que cada uno tenga su propio conjunto de docs.
        archives_buffer: list[dict] = []

        def on_response(resp):
            if ARCHIVE_API_RE.search(resp.url):
                try:
                    body = resp.text()
                except Exception:
                    return
                archives_buffer.extend(_parse_archives_response(body))

        context.on("response", on_response)

        # 1. Cargar portal, switchear a tab 2.0
        page.goto(PORTAL_URL)
        try:
            page.wait_for_selector(SEL_TAB_20, timeout=15000)
            page.click(SEL_TAB_20)
            page.wait_for_load_state("networkidle", timeout=15000)
        except PWTimeout:
            print("Timeout esperando tab 2.0 — abortando.")
            context.close()
            browser.close()
            stats["errores"] = len(targets)
            return stats

        # 2. Loop por proyecto
        for idx, ntr in enumerate(targets):
            if on_progress:
                on_progress(ntr, idx + 1, len(targets))
            archives_buffer.clear()
            try:
                docs = _enrich_single(page, ntr, archives_buffer)
                if docs:
                    db.replace_documentos(ntr, docs)
                    stats["con_docs"] += 1
                else:
                    stats["sin_docs"] += 1
                stats["procesados"] += 1
            except Exception as e:
                print(f"  [error] {ntr}: {type(e).__name__}: {e}")
                stats["errores"] += 1

            if sleep_between_ms:
                page.wait_for_timeout(sleep_between_ms)

        context.close()
        browser.close()

    return stats


def _enrich_single(page, n_tramite: str, archives_buffer: list[dict]) -> list[dict]:
    """Captura los documentos de UN proyecto.

    Pasos:
    1. Limpiar filtros previos.
    2. Filtrar por N. Trámite, buscar.
    3. Click find_in_page del único resultado → abre modal de fases.
    4. Click cada attach_file (uno por fase con docs) → dispara llamadas al
       API que pueblan `archives_buffer` (a través del response listener).
    5. Cerrar modal, devolver los docs acumulados.
    """
    # 1. Limpiar filtros
    try:
        if page.locator(SEL_BTN_LIMPIAR).count() > 0:
            page.click(SEL_BTN_LIMPIAR)
            page.wait_for_timeout(300)
    except Exception:
        pass

    # 2. Filtrar
    page.locator(SEL_FILTER_TRAMITE).first.fill(str(n_tramite))
    page.click(SEL_BTN_BUSCAR)
    page.wait_for_timeout(1500)

    icons = page.locator(SEL_FIND_IN_PAGE_ICON)
    if icons.count() == 0:
        return []

    # 3. Abrir modal de detalle
    icons.first.click()
    page.wait_for_selector(SEL_MODAL, timeout=10000)
    page.wait_for_timeout(700)

    # 4. Por cada attach_file en el modal: click + esperar respuesta API.
    #    En cada click, captura las fases y archivos asociados.
    attaches = page.locator(SEL_MODAL_ATTACH)
    n_attach = attaches.count()
    if n_attach == 0:
        _close_modal(page)
        return []

    # Recolectar el texto de cada fila de fase para asociar attach → fase
    fase_per_index: list[str] = []
    rows = page.locator(f"{SEL_MODAL} mat-row, {SEL_MODAL} tr.mat-row")
    for i in range(rows.count()):
        try:
            txt = rows.nth(i).inner_text(timeout=1500)
            fase = txt.split("\t")[0].split("\n")[0].strip()
            fase_per_index.append(fase)
        except Exception:
            fase_per_index.append("")

    # Click cada attach_file via dispatch_event('click'), que envia el evento
    # directamente al elemento sin chequear visibilidad/oclusion. Es el unico
    # approach que funciona cuando el primer click abre un sub-panel que cubre
    # a los siguientes attach_files de la lista. El response listener corre
    # async y captura las archives sin importar si el click "visual" funciona.
    #
    # Para asociar correctamente cada archivo capturado a su fase: antes de
    # cada click, leemos el texto del row padre del attach (que contiene el
    # nombre de la fase). Marcamos el size del buffer pre-click; los archives
    # que aparezcan después pertenecen a este click. Asi evitamos el bug del
    # fallback `fase_per_index[i]`, que fallaba cuando una fase generaba >1
    # archivo y los indices del buffer dejaban de calzar con los rows.
    for i in range(n_attach):
        try:
            current = page.locator(SEL_MODAL_ATTACH)
            if i >= current.count():
                break

            attach = current.nth(i)

            # Leer fase del row padre ANTES del click (despues del click el
            # DOM puede cambiar). xpath: el primer mat-row o tr.mat-row hacia
            # arriba en el arbol.
            fase_i: str | None = None
            try:
                row = attach.locator(
                    "xpath=ancestor::mat-row[1] | ancestor::tr[1]"
                ).first
                if row.count() > 0:
                    txt = row.inner_text(timeout=1500)
                    raw = txt.split("\t")[0].split("\n")[0].strip()
                    # El inner_text incluye el texto del icono Material
                    # ("attach_file") cuando la fuente no carga. Lo removemos
                    # para no contaminar el nombre de la fase.
                    if raw.endswith("attach_file"):
                        raw = raw[: -len("attach_file")].rstrip()
                    fase_i = raw or None
            except Exception:
                pass
            # Fallback: si no se pudo leer el row, usar el indice por fila
            # del modal recolectado al principio (sirve cuando hay 1:1).
            if not fase_i and i < len(fase_per_index):
                fase_i = fase_per_index[i] or None

            # Marcar el buffer antes del click; los archives que aparezcan
            # despues son los de este click.
            start = len(archives_buffer)
            # dispatch_event('click') bypassa actionability + overlays.
            attach.dispatch_event("click", timeout=4000)
            page.wait_for_timeout(1500)

            # Etiquetar los archives recien capturados con la fase del click.
            for a in archives_buffer[start:]:
                a["_fase_click"] = fase_i
        except Exception as e:
            print(f"    [warn] attach {i+1}/{n_attach}: {type(e).__name__}: {str(e)[:80]}")
            continue

    _close_modal(page)
    # ESC adicional por si quedó un overlay flotante
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(200)
    except Exception:
        pass

    # 5. Devolver los archives acumulados. Si hay duplicados por (filename, subdirectory),
    # quedarse solo con uno.
    # Prioridad para la fase: fase del click (asociada en el loop) > descripcion
    # del API (a veces tiene la fase) > None.
    seen: set[tuple[str, str]] = set()
    docs: list[dict] = []
    for a in archives_buffer:
        key = (a["filename"], a["subdirectory"])
        if key in seen:
            continue
        seen.add(key)
        fase = a.get("_fase_click") or a.get("descripcion") or None
        docs.append({
            "fase": fase,
            "descripcion": a["filename"],
            "url": a["url"],
        })
    return docs


def _close_modal(page) -> None:
    try:
        close_btn = page.locator(SEL_MODAL_CLOSE).first
        if close_btn.count() > 0:
            close_btn.click(timeout=2000)
            page.wait_for_timeout(300)
            return
    except Exception:
        pass
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
    except Exception:
        pass
