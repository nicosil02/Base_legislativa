"""HTML email template para el alerta diaria. Estilo Vali / Quals."""
from __future__ import annotations

import html
from itertools import groupby

# Color "dot" por tipo. Verde = nuevos dictamenes (relevancia alta).
# Amarillo = nuevos proyectos presentados.
DOT_DICTAMEN = "#21A179"
DOT_PROYECTO = "#F4B942"


def _escape(s):
    return html.escape(str(s or ""), quote=True)


def _group_by_tema(items):
    items_sorted = sorted(items, key=lambda x: (x.get("tema") or "Otros"))
    return [(tema, list(g)) for tema, g in groupby(items_sorted, key=lambda x: x.get("tema") or "Otros")]


def _items_html(items, dot_color):
    if not items:
        return ""
    chunks = []
    for tema, group in _group_by_tema(items):
        chunks.append(
            f'<h3 style="margin:24px 0 8px 0;font-size:15px;font-weight:700;color:#0A294D;letter-spacing:-0.01em;">{_escape(tema)}</h3>'
        )
        for it in group:
            url = _escape(it.get("url", "#"))
            titulo = _escape(it.get("titulo", ""))
            id_ = _escape(it.get("id", ""))
            estado = _escape(it.get("estado", ""))
            fecha = _escape(it.get("fecha", ""))
            chunks.append(
                f'<table cellpadding="0" cellspacing="0" border="0" width="100%" '
                f'style="margin:10px 0 14px 0;font-family:Inter,Segoe UI,Arial,sans-serif;">'
                f'<tr><td valign="top" width="14" style="padding-top:6px;">'
                f'<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:{dot_color};"></span>'
                f'</td><td valign="top" style="padding-left:6px;">'
                f'<a href="{url}" target="_blank" rel="noopener" '
                f'style="color:#0A294D;text-decoration:underline;font-size:14px;font-weight:600;line-height:1.4;">{titulo}</a>'
                f'<div style="font-size:11px;color:#869FB2;margin-top:4px;letter-spacing:0.04em;">'
                f'{id_} &middot; {estado} &middot; {fecha}</div>'
                f'</td></tr></table>'
            )
    return "".join(chunks)


def _country_section(country_label, country_data):
    dictamenes = country_data.get("dictamenes", [])
    proyectos = country_data.get("proyectos", [])
    if not dictamenes and not proyectos:
        return ""
    parts = [
        f'<table cellpadding="0" cellspacing="0" border="0" width="100%" '
        f'style="margin-top:30px;border-top:2px solid #0A294D;padding-top:8px;">'
        f'<tr><td style="font-family:Inter,Segoe UI,Arial,sans-serif;font-size:11px;'
        f'font-weight:800;letter-spacing:0.22em;text-transform:uppercase;color:#0A294D;padding-bottom:6px;">'
        f'{country_label}</td></tr></table>'
    ]
    if dictamenes:
        parts.append(
            '<h2 style="margin:18px 0 6px 0;font-size:18px;font-weight:800;color:#0A294D;'
            'letter-spacing:-0.015em;font-family:Inter,Segoe UI,Arial,sans-serif;">'
            'Nuevos dictamenes</h2>' + _items_html(dictamenes, DOT_DICTAMEN)
        )
    if proyectos:
        parts.append(
            '<h2 style="margin:24px 0 6px 0;font-size:18px;font-weight:800;color:#0A294D;'
            'letter-spacing:-0.015em;font-family:Inter,Segoe UI,Arial,sans-serif;">'
            'Nuevos Proyectos de Ley</h2>' + _items_html(proyectos, DOT_PROYECTO)
        )
    return "".join(parts)


def render_html(payload):
    fecha = _escape(payload.get("fecha", ""))
    peru_html = _country_section("Peru &middot; Congreso de la Republica", payload.get("peru", {}))
    ec_html = _country_section("Ecuador &middot; Asamblea Nacional", payload.get("ecuador", {}))
    body = (peru_html or "") + (ec_html or "")
    if not body:
        body = '<p style="color:#869FB2;font-size:14px;">No hay novedades en las ultimas 24 horas.</p>'
    return (
        '<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">'
        '<title>Radar Legislativo - Alerta diaria</title></head>'
        '<body style="margin:0;padding:0;background:#F4F6F8;font-family:Inter,Segoe UI,Arial,sans-serif;">'
        '<table cellpadding="0" cellspacing="0" border="0" width="100%" style="background:#F4F6F8;">'
        '<tr><td align="center" style="padding:30px 0;">'
        '<table cellpadding="0" cellspacing="0" border="0" width="640" '
        'style="max-width:640px;background:#FFFFFF;border-radius:14px;border:1px solid #CFD9E0;padding:32px 36px;">'
        '<tr><td>'
        '<table cellpadding="0" cellspacing="0" border="0" width="100%" '
        'style="border-bottom:1px solid #E3E9ED;padding-bottom:14px;margin-bottom:6px;">'
        '<tr><td><div style="display:inline-block;padding:6px 14px;background:#0A294D;color:#FFFFFF;'
        'border-radius:6px;font-size:14px;font-weight:700;letter-spacing:0.02em;">Alertas</div></td>'
        f'<td align="right" style="font-size:12px;color:#435D74;border-bottom:1px solid #0A294D;padding-bottom:4px;">{fecha}</td></tr>'
        '</table>'
        '<p style="font-size:14px;color:#0A294D;margin:18px 0 2px 0;">Hola,</p>'
        '<p style="font-size:14px;color:#435D74;margin:0 0 6px 0;">'
        'Te presentamos las alertas regulatorias de las ultimas 24 horas.</p>'
        + body +
        '<div style="margin-top:36px;padding-top:14px;border-top:1px solid #E3E9ED;'
        'font-size:11px;color:#869FB2;letter-spacing:0.12em;text-transform:uppercase;font-weight:700;">'
        'Radar Legislativo &middot; Vali Consultores</div>'
        '</td></tr></table></td></tr></table></body></html>'
    )


def render_subject(payload):
    from alerts.build import count_items
    n = count_items(payload)
    fecha = payload.get("fecha", "")
    if n == 0:
        return f"Radar Legislativo - {fecha} - sin novedades"
    return f"Radar Legislativo - {fecha} - {n} alerta(s) nueva(s)"
