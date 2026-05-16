# Radar Legislativo

Plataforma de monitoreo legislativo. Hoy cubre **Perú** (Congreso de la República,
período 2021–2026). Diseñada como app multi-país: cada país vive en su propia página
bajo `pages/`. Frontend en Streamlit con estética editorial-data (similar a datadaf.com),
backend en SQLite alimentado por scraping del API oficial.

## Setup inicial

### Camino rápido (PC nueva, usando el snapshot del repo)

El repo trae un snapshot ya cargado (`data/proyectos.db.gz` con ~14,600 PLs +
etiquetas del Excel ya aplicadas). En 2 comandos arrancas con todo:

```powershell
pip install -r requirements.txt
python -m scraper.cli restaurar           # descomprime data/proyectos.db.gz -> proyectos.db
python -m streamlit run app.py            # abre el dashboard
```

Luego corres `python -m scraper.cli update` para traer los PLs nuevos que
hayan aparecido entre el snapshot y hoy (segundos).

### Camino desde cero (sin snapshot)

Si querés (re)construir desde el API:

```powershell
pip install -r requirements.txt
python -m scraper.cli init                       # crea proyectos.db + comisiones
python -m scraper.cli update                     # carga completa (~30-40 min, ~14,600 PLs)
python -m scraper.cli importar-temas data\ProyectosDeLey.xlsx
```

El `importar-temas` aplica las etiquetas manuales del Excel (`tema_manual=1`) y luego
corre dos pases de override:

- **Farma** sobrescribe Otros / Salud cuando matchea ≥1 keyword (medicamentos, oncología, VIH, vacunación, etc.).
- **Tecnología** sobrescribe **cualquier categoría** cuando matchea ≥1 keyword distintivo (IA, datos personales, biometría, ciberseguridad, plataforma digital, etc.).

### Refrescar el snapshot del repo

Cuando quieras actualizar el `data/proyectos.db.gz` para que tus compañeros
arranquen con una DB más fresca, después de un `update`:

```powershell
# PowerShell
$ErrorActionPreference = "Stop"
& "$env:WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe" -Command `
  "Compress-Archive -Force -Path proyectos.db -DestinationPath data\proyectos.db.zip"
# o más simple si tienes git bash / Python:
python -c "import gzip,shutil; shutil.copyfileobj(open('proyectos.db','rb'), gzip.open('data/proyectos.db.gz','wb',9))"
git add data/proyectos.db.gz
git commit -m "snapshot DB $(Get-Date -Format yyyy-MM-dd)"
git push
```

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

- **Listado**: `POST /proyecto-ley/lista-con-filtro` con `{perParId: 2021, first, rows}`.
  Devuelve los ~14,600 PLs en una sola respuesta (~30 s).
- **Detalle**: `GET /expediente/{enc(perParId)}/{enc(pleyNum)}`. Los parámetros se cifran
  con AES-128-ECB + PKCS7 (clave extraída del bundle Angular). Trae comisiones, firmantes,
  seguimientos completos y archivos PDF.
- **Comisiones**: `GET /comisiones` (catálogo).

El sync sólo llama al detalle para PLs nuevos o cuyo `desEstado` cambió → en uso
incremental son pocas docenas de calls.

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
