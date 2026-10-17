"""PDFs de cada proyecto EC via Playwright.

Los PDFs se bajan sin auth del fileservice publico, pero la lista de archivos
(pplessservice2/) pide sesion: se abre el modal de cada proyecto en la SPA y
se capturan las respuestas JSON del catalogo para armar las URLs.

    python -m scraper_ec.cli enriquecer-documentos --limit 20
"""
from __future__ import annotations

import json
import re
from typing import Callable, Iterable
from urllib.parse import quote

PORTAL_URL = "https://proyectosdeley.asambleanacional.gob.ec/report"
FILESERVICE = "https://proyectosdeley.asambleanacional.gob.ec/fileservice/file/download"
SEL_BTN_CSV = 'button:has-text("CSV")'

# Selectores del DOM de Ppless v2 (Angular Material).
SEL_TAB_20 = "text=CONSULTA DE PROYECTOS DE LEY 2.0"
SEL_FILTER_TRAMITE = "input#procedure"
SEL_BTN_BUSCAR = 'button:has-text("Buscar"):not(:has-text("Limpiar"))'
SEL_BTN_LIMPIAR = 'button:has-text("Limpiar"):not(:has-text("Buscar"))'
SEL_FIND_IN_PAGE_ICON = 'mat-icon:has-text("find_in_page")'
SEL_MODAL = "mat-dialog-container"
SEL_MODAL_ATTACH = 'mat-dialog-container mat-icon:has-text("attach_file")'
SEL_MODAL_CLOSE = 'mat-dialog-container mat-icon:has-text("cancel")'

ARCHIVE_API_RE = re.compile(r"/archive/search/findAllByAttachment_Id\?id=\d+")


def abrir_portal(page) -> bool:
    """Carga Ppless v2 (3 intentos: la red del runner a veces da timeout) y
    entra al tab 2.0. False si no pudo."""
    from playwright.sync_api import TimeoutError as PWTimeout
    for intento in (1, 2, 3):
        try:
            page.goto(PORTAL_URL, timeout=60000, wait_until="domcontentloaded")
            break
        except PWTimeout as e:
            print(f"[portal] goto intento {intento}/3: timeout: {e}")
    else:
        print("[portal] no cargo tras 3 intentos")
        return False
    try:
        page.wait_for_selector(SEL_TAB_20, timeout=20000)
        page.click(SEL_TAB_20)
    except PWTimeout:
        print("[portal] timeout esperando el tab 2.0")
        return False
    return True


def esperar_red(page, timeout: int = 15000, respaldo_ms: int = 3000) -> None:
    """networkidle con tope; si no llega, una pausa fija."""
    from playwright.sync_api import TimeoutError as PWTimeout
    try:
        page.wait_for_load_state("networkidle", timeout=timeout)
    except PWTimeout:
        page.wait_for_timeout(respaldo_ms)


def _build_download_url(filename: str, subdir: str) -> str:
    return (
        f"{FILESERVICE}"
        f"?fileName={quote(filename)}"
        f"&system=ppless"
        f"&subDirectory={quote(subdir)}"
    )


def download_csv(output_path, *, headless: bool = True, timeout_ms: int = 60000) -> bool:
    """Descarga el CSV del portal Ppless v2. True si quedo un archivo no vacio."""
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    from pathlib import Path

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        ctx = browser.new_context(accept_downloads=True)
        page = ctx.new_page()
        page.set_default_timeout(timeout_ms)
        # El CSV se arma como Blob en el navegador y en headless el evento de
        # descarga a veces no llega: se lee el Blob directo por JS.
        page.add_init_script(
            """
            window.__csvBlobText = null;
            const _orig = URL.createObjectURL.bind(URL);
            URL.createObjectURL = function(blob) {
                window.__csvBlobText = blob.text();
                return _orig(blob);
            };
            """
        )
        try:
            if not abrir_portal(page):
                return False
            page.wait_for_timeout(1500)
            # CSV exporta lo del ultimo "Buscar"; sin el, en CI sale vacio.
            page.wait_for_selector(SEL_BTN_BUSCAR, timeout=10000)
            page.click(SEL_BTN_BUSCAR)
            esperar_red(page)
            page.wait_for_timeout(1000)
            page.click(SEL_BTN_CSV, force=True)
            page.wait_for_function("window.__csvBlobText !== null", timeout=15000)
            texto = page.evaluate("async () => await window.__csvBlobText")
            output_path.write_text(texto, encoding="utf-8")
            size = output_path.stat().st_size
            print(f"[csv] descargado {output_path.name} ({size:,} bytes)")
            return size > 0
        except PWTimeout as e:
            print(f"[csv] timeout: {e}")
            return False
        except Exception as e:
            print(f"[csv] error: {type(e).__name__}: {e}")
            return False
        finally:
            ctx.close()
            browser.close()


def _parse_archives_response(body: str) -> list[dict]:
    """Respuesta de `archive/search/findAllByAttachment_Id` ->
    [{filename, subdirectory, url, descripcion}]."""
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
        # "ppless/2343_task" -> "2343_task"
        parts = url_path.split("/", 1)
        subdir = parts[1] if len(parts) == 2 else url_path
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
    on_progress: Callable[[str, int, int], None] | None = None,
    timeout_ms: int = 30000,
    sleep_between_ms: int = 800,
) -> dict:
    """Captura los PDFs de cada proyecto de `n_tramites`.
    Devuelve {"procesados", "con_docs", "sin_docs", "errores"}."""
    from playwright.sync_api import sync_playwright

    targets = list(n_tramites)

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

        # Lo que devuelve el catalogo; se vacia entre proyectos.
        archives_buffer: list[dict] = []

        def on_response(resp):
            if ARCHIVE_API_RE.search(resp.url):
                try:
                    body = resp.text()
                except Exception:
                    return
                archives_buffer.extend(_parse_archives_response(body))

        context.on("response", on_response)

        if not abrir_portal(page):
            context.close()
            browser.close()
            stats["errores"] = len(targets)
            return stats
        esperar_red(page)

        for idx, ntr in enumerate(targets):
            if on_progress:
                on_progress(ntr, idx + 1, len(targets))
            archives_buffer.clear()
            try:
                r = db.conn.execute(
                    "SELECT titulo FROM proyectos WHERE n_tramite = ?", (ntr,)
                ).fetchone()
                docs = _enrich_single(page, ntr, archives_buffer,
                                      titulo=r[0] if r else None)
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


def _enrich_single(page, n_tramite: str, archives_buffer: list[dict],
                   titulo: str | None = None) -> list[dict]:
    """Documentos de UN proyecto: filtra por tramite, abre el modal de fases
    y hace click en cada attach_file; el listener llena `archives_buffer`."""
    try:
        if page.locator(SEL_BTN_LIMPIAR).count() > 0:
            page.click(SEL_BTN_LIMPIAR)
            page.wait_for_timeout(300)
    except Exception:
        pass

    # "460570~a1b2c3" = segundo proyecto con el mismo tramite en el portal
    # (ver csv_importer.iter_rows): se busca por el numero real.
    page.locator(SEL_FILTER_TRAMITE).first.fill(str(n_tramite).split("~")[0])
    page.click(SEL_BTN_BUSCAR)
    page.wait_for_timeout(1500)

    icons = page.locator(SEL_FIND_IN_PAGE_ICON)
    if icons.count() == 0:
        return []

    # Con tramite repetido hay >1 resultado: se abre la fila con el mismo titulo.
    icon = icons.first
    if icons.count() > 1 and titulo:
        for i in range(icons.count()):
            fila = icons.nth(i).locator(
                "xpath=ancestor::mat-row[1] | ancestor::tr[1]").first
            if titulo[:80] in fila.inner_text(timeout=1500):
                icon = icons.nth(i)
                break
    icon.click()
    page.wait_for_selector(SEL_MODAL, timeout=10000)
    page.wait_for_timeout(700)

    # El modal pagina las fases de a 5 y las de debate quedan en la pagina 2+.
    # Tope de 10 por si el paginador no avanza.
    for _pagina in range(10):
        attaches = page.locator(SEL_MODAL_ATTACH)
        n_attach = attaches.count()
        if n_attach == 0 and not archives_buffer:
            _close_modal(page)
            return []

        # Fase de cada fila: respaldo si no se puede leer la fila del attach.
        fase_per_index: list[str] = []
        rows = page.locator(f"{SEL_MODAL} mat-row, {SEL_MODAL} tr.mat-row")
        for i in range(rows.count()):
            try:
                txt = rows.nth(i).inner_text(timeout=1500)
                fase = txt.split("\t")[0].split("\n")[0].strip()
                fase_per_index.append(fase)
            except Exception:
                fase_per_index.append("")

        # dispatch_event: el primer click abre un sub-panel que tapa a los
        # demas. Lo que entra al buffer tras cada click es de la fase de esa fila.
        for i in range(n_attach):
            try:
                current = page.locator(SEL_MODAL_ATTACH)
                if i >= current.count():
                    break

                attach = current.nth(i)

                # Antes del click: despues el DOM cambia.
                fase_i: str | None = None
                try:
                    row = attach.locator(
                        "xpath=ancestor::mat-row[1] | ancestor::tr[1]"
                    ).first
                    if row.count() > 0:
                        txt = row.inner_text(timeout=1500)
                        raw = txt.split("\t")[0].split("\n")[0].strip()
                        # Sin la fuente de iconos el texto trae "attach_file".
                        if raw.endswith("attach_file"):
                            raw = raw[: -len("attach_file")].rstrip()
                        fase_i = raw or None
                except Exception:
                    pass
                if not fase_i and i < len(fase_per_index):
                    fase_i = fase_per_index[i] or None

                start = len(archives_buffer)
                attach.dispatch_event("click", timeout=4000)
                page.wait_for_timeout(1500)

                for a in archives_buffer[start:]:
                    a["_fase_click"] = fase_i
            except Exception as e:
                print(f"    [warn] attach {i+1}/{n_attach}: {type(e).__name__}: {str(e)[:80]}")
                continue

        nxt = page.locator(
            # El paginador de las fases; hay otro dentro de la fila expandida
            # (lista de archivos) que no hay que tocar.
            f"{SEL_MODAL} .main-container-table-report > mat-paginator "
            "button.mat-paginator-navigation-next:not([disabled])"
        )
        if nxt.count() == 0:
            break
        nxt.first.dispatch_event("click")
        page.wait_for_timeout(1000)

    _close_modal(page)
    # ESC por si quedo un overlay
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(200)
    except Exception:
        pass

    # Sin duplicados; fase = la del click, si no la descripcion del API.
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
