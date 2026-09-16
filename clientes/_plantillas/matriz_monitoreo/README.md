# Matriz de Monitoreo

Excel de Nicolas (`Matriz de Monitoreo - PL's.xlsx`, recibido 2026-09-11), 12 hojas. Nicolas solo usa la
primera hoja (**"Links de interés_sin formato"**) — enlaces de referencia por país y categoría (Institución,
Coyuntura Política, Temas Agrarios, Temas Salud, Temas Tech, etc).

**Ojo:** `matriz_monitoreo_raw.md` (conversión directa vía anydoc) perdió las URLs reales — Excel las
guarda como hyperlink separado del texto mostrado, y anydoc solo trae el texto ("Enlace"). Las URLs
reales están en **`matriz_sheet1.json`** — usar ese archivo como fuente, no el `.md`.

## Estado: hecho (2026-09-12, segunda pasada)

**Alcance recortado a PE + EC** (Nicolas confirmó que solo esos dos países y fuentes internacionales que
les afectan importan) — se eliminó por completo la columna/sección Chile del archivo. Ningún cliente
actual (Google, Incode, Bayer, Syngenta) opera ahí.

**Cruce fuente × cliente aplicado** (el patrón de Dapper/Parlamento.ai investigado esta sesión: organizan
sus fuentes por tipo × relevancia-por-cliente, no como lista plana). Cada institución de
`instituciones_pe`/`instituciones_ec` trae ahora un campo `"clientes"` con los slugs de quién la usa,
armado leyendo de verdad cada `clientes/<cliente>/notas.md` — no inventado. `"todos"` se usa solo para el
backbone legislativo/político general (Congreso, Presidencia, diarios oficiales); una lista vacía `[]`
significa que hoy ningún cliente la reclama explícitamente (no que sea irrelevante — puede ser que falte
actualizar el notas.md correspondiente).

**Ecuador: ministerios corregidos por fusión real, no error de scraping.** Confirmado con búsqueda web
(no eran links rotos al azar, hubo reestructuración de gobierno real en 2025-2026):
- **Ministerio de Ambiente y Energía (MAE)** — Decreto Ejecutivo 94 (14/08/2025) fusionó el viejo
  Ministerio del Ambiente, Agua y Transición Ecológica con el de Energía y Minas. Dominio nuevo:
  `ambienteyenergia.gob.ec`.
- **Ministerio de Desarrollo Económico y Productivo (MDEP)** — Decreto Ejecutivo 425 (oficializado
  ~19/06/2026) unificó en una sola cartera lo que antes eran **3 ministerios separados**: Agricultura y
  Ganadería, Economía y Finanzas, y Producción/Comercio Exterior/Inversiones y Pesca. Las 3 filas viejas
  del Excel (`agricultura.gob.ec`, `finanzas.gob.ec`, `produccion.gob.ec`) se consolidaron en 1 sola fila,
  dominio nuevo `economicoproductivo.gob.ec`.

**Links muertos, arreglados de verdad (no solo re-flageados):**
- **Niubox** (PE) → era una URL de búsqueda de Facebook. Real: `https://niubox.legal/category/nius/`
  (consultora legal peruana especializada en tech/regulatorio — es literalmente su sección de noticias).
- **Asociación Latinoamericana de Internet** (aparecía roto en 2 lados) → real: `https://alai.lat/`.

**Sin resolver, requiere tu confirmación:**
- Ministerio de Telecomunicaciones EC quedó tageado `google` solo por afinidad temática (digital/telecom),
  no porque el notas.md de Google lo liste explícito — ver `problemas_detectados`.

Las demás categorías (Coyuntura Política, Temas Agrarios, Temas Salud, Temas Tech/Pagos — incluye
Twitter/X y Facebook) se dejaron intactas en contenido, solo se les quitó la columna Chile.

## Relación con `notas.md` (resuelto, 2026-09-12)
Nicolas confirmó: la matriz y las "Entidades a monitorear" de cada `clientes/<cliente>/notas.md` son parte
de lo mismo, no una reemplaza a la otra. `notas.md` es el perfil curado a mano por cliente (temas,
contactos, canal); esta matriz es el catálogo base de fuentes (institución/medio/red social) con el tag
`"clientes"` que cruza cada fuente contra a quién le importa. Ambas se mantienen.
