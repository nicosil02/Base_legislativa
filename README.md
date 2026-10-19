# Radar Legislativo

Plataforma de monitoreo legislativo. Hoy cubre **Perú** (Congreso de la República —
período vigente 2026–2031, Congreso bicameral: Senado + Cámara de Diputados, instalado
2026-07-27; más el período histórico 2021–2026, Congreso unicameral). Diseñada como app
multi-país: cada país vive en su propia página bajo `pages/`. Frontend en Streamlit con
estética editorial-data (similar a datadaf.com), backend en SQLite alimentado por
scraping del API oficial.

## Setup inicial

### Camino rápido (PC nueva, usando la base publicada)

Paso a paso completo, con secretos y servicios externos, en `docs/INSTALAR.md`.

```bash
pip install -r requirements.txt -c constraints.txt
bash scripts/bajar_db.sh proyectos.db.gz proyectos.db
python -m streamlit run app.py            # abre el dashboard
```

Luego corres `python -m scraper.cli update` para traer los PLs nuevos.

### Camino desde cero

```powershell
pip install -r requirements.txt -c constraints.txt
python -m scraper.cli init                       # crea proyectos.db + comisiones
python -m scraper.cli update                     # carga completa (~30-40 min)
```

No commitear `data/*.db.gz` en `main`: la base va solo en la rama `datos`.

## Dashboard (frontend)

```powershell
python -m streamlit run app.py
```

App multi-página con estética editorial-data (tipografía Inter, peso 900, acentos azules `#2563EB`).

- **Home (`/`)** — `app.py`. Title "Radar Legislativo" + grid de países: 🇵🇪 Perú operativo, 🇨🇴 Colombia y 🇪🇨 Ecuador como placeholders. Cards con bordes sutiles que en hover destacan en azul.
- **Perú (`/Peru`)** — `pages/1_Peru.py`. Dashboard con:
  - **KPIs**: Total, Presentados, En comisión, Con dictamen, Autógrafas, Ley publicada (matchea `PUBLIC...PERUANO` y variantes).
  - **Filtros**: PL (text), Tema, Estado, Comisión, Partido, Proponente (todos selectbox single-select con "Todos" por defecto) + búsqueda libre por título / autor.
  - **Tabla `st.dataframe` con 6 columnas** que entran sin scroll horizontal: PL, Título, Presentado, Estado, Tema, Comisión (princ.). Click en headers para ordenar.
  - **Panel de detalle** al hacer click en una fila: PL + título completo, metadata grid (Estado, Tema, Partido, Proponente, Presentado, Último cambio), todas las comisiones asignadas, sumilla, autores completos, historial de cambios, links Portal y PDF.
  - **Sidebar**: rango de fechas (date range picker) + panel Sync con último run y botón "Actualizar ahora".
- **Comisiones**: el filtro muestra solo las **24 ordinarias** + un grupo único **"Comisiones Especiales"** que agrupa el resto (especiales, subcomisiones, typos del catálogo). El mapeo está en `scraper/comisiones_ordinarias.py`.

Caching de queries 60s. Para refrescar manualmente: `C` o `R` en la página.

## Actualización automática cada 2 horas (Windows)

```powershell
# Una sola vez:
.\scripts\install_schedule.ps1
```

Registra la tarea **BaseLegislativa-Update** en el Task Scheduler:
- Corre `python -m scraper.cli update` cada 2 horas.
- Logs en `update.log` (en la carpeta del repo).
- No requiere admin; corre bajo tu usuario aunque la sesión esté bloqueada (`-LogonType S4U`).

Comandos útiles:

```powershell
Get-ScheduledTask -TaskName "BaseLegislativa-Update"     # ver estado
Start-ScheduledTask -TaskName "BaseLegislativa-Update"   # disparar manualmente
Get-Content update.log -Tail 50 -Wait                    # ver logs en vivo
.\scripts\install_schedule.ps1 -Uninstall                # desinstalar
```

Para cambiar la frecuencia: `.\scripts\install_schedule.ps1 -IntervalHours 1`.

## CLI sin frontend

```powershell
python -m scraper.cli update                                 # sync incremental
python -m scraper.cli update --full                          # rehace TODO el detalle
python -m scraper.cli query --tema "Tecnología" --limit 30
python -m scraper.cli query --partido "Perú Libre" --estado "EN COMISIÓN"
python -m scraper.cli show 14515                             # detalle + historial
python -m scraper.cli recategorizar                          # re-aplica reglas a los no-manuales
python -m scraper.cli export --out proyectos.json            # dump completo
```

## Cómo funciona

El portal oficial (`https://wb2server.congreso.gob.pe/spley-portal/`) es una SPA Angular
que consume un API REST en `https://api.congreso.gob.pe/spley-portal-service`.

- **Listado**: `POST /proyecto-ley/lista-con-filtro` con `{perParId, first, rows}` — el
  sync corre esto para **cada período** en `scraper.sync.PERIODOS_SYNC` (hoy solo
  `2026`, ver abajo). Devuelve todos los PLs del período en una sola respuesta.
- **Detalle**: `GET /expediente/{enc(perParId)}/{enc(pleyNum)}`. Los parámetros se cifran
  con AES-128-ECB + PKCS7 (clave extraída del bundle Angular). Trae comisiones, firmantes,
  seguimientos completos y archivos PDF.
- **Comisiones**: `GET /comisiones` (catálogo, no depende del período).

El sync sólo llama al detalle para PLs nuevos o cuyo `desEstado` cambió → en uso
incremental son pocas docenas de calls.

### Períodos parlamentarios (`perParId`)

El Congreso peruano pasó de unicameral a **bicameral** (Senado + Cámara de Diputados) el
2026-07-27, tras la reforma constitucional de 2024. `scraper/sync.py` solo sincroniza el vigente:

| `perParId` | Período | Congreso | Estado |
|---|---|---|---|
| `2021` | 2021–2026 | Unicameral | Histórico (cerrado 2026-07-26) |
| `2026` | 2026–2031 | Bicameral | **Vigente** — `PER_PAR_ID_ACTUAL` |

Los demás módulos con datos period-sensibles (`sesiones/` — comisiones, `pleno/` —
agendas del Pleno) siguen el mismo criterio; ver sus propios `__init__.py`/`README` para
el detalle de cada API (cada una usa su propio backend del Congreso, con su propio
catálogo de períodos).

## Esquema SQLite

- `proyectos` — fila principal con `tema`, `tema_manual` (1 = manual del Excel o de
  un override Tec/Farma; 0 = clasificador automático), `first_seen_at`, `last_changed_at`.
- `proyecto_comision` — M:N con las comisiones asignadas.
- `seguimientos` — historial de cambios tal como lo da el servidor.
- `archivos` — PDFs adjuntos por seguimiento.
- `comisiones` — catálogo.
- `sync_runs` — bitácora de cada corrida.

## Roadmap

- Migrar a Postgres (Supabase / Neon) y desplegar:
  - Frontend → Streamlit Cloud (gratis para apps públicas, conectado al repo de GitHub).
  - Scheduler → GitHub Actions cron cada 2h (gratis, sin servidor).
- Tag "Crop" para Syngenta dentro de Agricultura.
- Ampliar período: 2016-2021 y anteriores.
