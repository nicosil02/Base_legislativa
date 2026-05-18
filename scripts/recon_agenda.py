"""Recon: descubre endpoints REST del backend del Congreso que las SPAs
adlp-visor y visor-sesiones consumen para mostrar agendas y sesiones.

Carga las dos SPAs en Chromium headless, intercepta TODAS las requests al
backend (`service-portal-publico-ext`, `service-alfresco`, etc), guarda URL
+ método + headers + status + sample del body, e intenta interactuar con
los dropdowns/filtros para disparar más calls.

Salida: dos JSON con el catálogo de calls (uno por SPA).

Uso:
    python scripts/recon_agenda.py [--headless]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout


BACKEND_HOSTS = ("wb2server.congreso.gob.pe", "api.congreso.gob.pe", "svr-appserver2.congreso.net")
SPAS = [
    {"name": "visor-sesiones", "url": "https://wb2server.congreso.gob.pe/visor-sesiones/"},
    {"name": "adlp-visor",     "url": "https://wb2server.congreso.gob.pe/adlp-visor/"},
]


def _is_backend(url: str) -> bool:
    if any(h in url for h in BACKEND_HOSTS):
        # Excluir los static assets (.js, .css, fuentes, imágenes)
        if any(url.endswith(ext) for ext in (".js", ".css", ".woff", ".woff2",
                                              ".png", ".jpg", ".svg", ".ico",
                                              ".map", ".html")):
            return False
        # Excluir las propias rutas de los visores (assets cargados como JSON pero del propio bundle)
        if "/visor-sesiones/" in url or "/adlp-visor/" in url:
            return False
        return True
    return False


def recon_spa(pw, spa_url: str, spa_name: str, headless: bool) -> dict:
    """Carga la SPA, captura todas las calls al backend e intenta interactuar."""
    print(f"\n{'='*70}\n  RECON: {spa_name}  ({spa_url})\n{'='*70}")
    browser = pw.chromium.launch(headless=headless)
    context = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
    )
    page = context.new_page()
    page.set_default_timeout(20000)

    calls: list[dict] = []

    def on_request(req):
        if _is_backend(req.url):
            calls.append({
                "_phase": "request",
                "url": req.url,
                "method": req.method,
                "headers": dict(req.headers),
                "post_data": req.post_data,
                "response_status": None,
                "response_ct": None,
                "response_sample": None,
            })

    def on_response(resp):
        if _is_backend(resp.url):
            # Buscar la call request correspondiente (la más reciente con misma URL)
            for c in reversed(calls):
                if c["url"] == resp.url and c["response_status"] is None:
                    c["response_status"] = resp.status
                    c["response_ct"] = resp.headers.get("content-type", "")
                    try:
                        body = resp.text()
                        # Solo guardamos un sample (primeros 500 chars) para no
                        # inflar el JSON.
                        c["response_sample"] = body[:500] if body else None
                    except Exception as e:
                        c["response_sample"] = f"<error reading body: {e}>"
                    break

    context.on("request", on_request)
    context.on("response", on_response)

    # 1. Carga inicial
    try:
        page.goto(spa_url, wait_until="networkidle", timeout=30000)
        print(f"  HTML cargado, esperando 4s para que Angular hidrate...")
        page.wait_for_timeout(4000)
    except PWTimeout:
        print(f"  WARN: networkidle timeout, intento seguir igual")

    print(f"  Calls al backend tras carga inicial: {len(calls)}")
    n_initial = len(calls)

    # 2. Intentar interactuar con la SPA para disparar más calls.
    #    Approach: encontrar todos los <mat-select>, <select>, dropdowns y abrirlos.
    #    Esto suele disparar llamadas para llenar los options.
    try:
        # Click en cualquier mat-select o select del DOM
        selectors_to_try = [
            "mat-select", "select", "[role=combobox]",
            "button:has-text('Comision')", "button:has-text('Buscar')",
            "[aria-label*='Comision']", "[aria-label*='comision']",
        ]
        for sel in selectors_to_try:
            try:
                loc = page.locator(sel)
                count = loc.count()
                if count == 0:
                    continue
                print(f"  Intentando interactuar con '{sel}' ({count} matches)")
                # Click primero para abrir
                loc.first.click(timeout=2000)
                page.wait_for_timeout(800)
                # Apretar Escape para cerrar
                page.keyboard.press("Escape")
                page.wait_for_timeout(300)
                # Solo el primer selector que matche
                break
            except Exception:
                continue
    except Exception as e:
        print(f"  WARN: interaccion fallo: {e}")

    page.wait_for_timeout(2000)

    print(f"  Calls totales tras interaccion: {len(calls)}  (nuevas tras interactuar: {len(calls) - n_initial})")

    # Cerrar
    context.close()
    browser.close()

    return {
        "spa_name": spa_name,
        "spa_url": spa_url,
        "calls": calls,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-headless", action="store_true", help="ver el browser")
    ap.add_argument("--out", default="scripts/recon_agenda_output.json")
    args = ap.parse_args()

    headless = not args.no_headless
    print(f"Headless: {headless}")

    results = []
    with sync_playwright() as pw:
        for spa in SPAS:
            try:
                r = recon_spa(pw, spa["url"], spa["name"], headless)
                results.append(r)
            except Exception as e:
                print(f"  ERROR procesando {spa['name']}: {type(e).__name__}: {e}")
                results.append({"spa_name": spa["name"], "spa_url": spa["url"],
                                "error": f"{type(e).__name__}: {e}"})

    # Resumen ejecutivo en stdout
    print(f"\n{'='*70}\n  RESUMEN\n{'='*70}")
    for r in results:
        if "error" in r:
            print(f"\n{r['spa_name']}: ERROR {r['error']}")
            continue
        calls = r["calls"]
        print(f"\n{r['spa_name']}: {len(calls)} calls al backend")
        # Agrupar por URL base (sin query) y mostrar
        seen = set()
        for c in calls:
            url_base = c["url"].split("?")[0]
            key = (c["method"], url_base)
            if key in seen:
                continue
            seen.add(key)
            print(f"  {c['method']:5s} {c['response_status'] or '?':4} {url_base}")
        # Mostrar headers de la primera call al backend con status 200
        ok = [c for c in calls if c.get("response_status") == 200]
        if ok:
            c = ok[0]
            print(f"\n  Sample headers de request OK ({c['url'].split('?')[0]}):")
            for k, v in c["headers"].items():
                # Recortar Authorization/Cookie por seguridad
                if k.lower() in ("authorization", "cookie", "x-csrf-token"):
                    print(f"    {k}: {v[:60]}..." if len(v) > 60 else f"    {k}: {v}")
                else:
                    print(f"    {k}: {v}")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nDetalle completo guardado en: {out_path}")


if __name__ == "__main__":
    sys.exit(main() or 0)
