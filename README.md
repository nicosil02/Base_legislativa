# Base Legislativa — Proyectos de Ley del Congreso del Perú

Base de datos local de los proyectos de ley del período 2021-2026, con clasificación
temática híbrida (etiquetas manuales del Excel + reglas para Tecnología/Farma) y un
dashboard Streamlit para explorarla.

## Setup inicial

```powershell
pip install -r requirements.txt
python -m scraper.cli init                       # crea proyectos.db + 59 comisiones
python -m scraper.cli update                     # carga completa (~30-40 min, ~14,600 PLs)
python -m scraper.cli importar-temas "C:\Users\USER\Downloads\ProyectosDeLey.xlsx"
```

El `importar-temas` aplica las etiquetas manuales del Excel (`tema_manual=1`) y luego
corre dos pases de override:

- **Farma** sobrescribe Otros / Salud cuando matchea ≥1 keyword (medicamentos, oncología, VIH, vacunación, etc.).
- **Tecnología** sobrescribe **cualquier categoría** cuando matchea ≥1 keyword distintivo (IA, datos personales, biometría, ciberseguridad, plataforma digital, etc.).

## Dashboard (frontend)

```powershell
streamlit run app.py
```

Se abre una pestaña del navegador con:

- **KPIs** arriba (totales por estado).
- **Sidebar** con filtros: tema, estado, partido, proponente, comisión, búsqueda libre.
- **Tabla** con links directos al portal del Congreso y al PDF.
- **Detalle expandible** del proyecto seleccionado (sumilla + historial de cambios).
- Botón **Actualizar ahora** que dispara un `update` incremental en background.

Las consultas a la DB se cachean 60s. Si actualizas la DB por otro lado, dale **C** o
recarga la página para refrescar.

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
