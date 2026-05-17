# Alertas diarias por email

Sistema de alertas que manda un correo a las **9 AM (Lima/Quito)** con:
- Nuevos proyectos de ley presentados en las últimas 24h
- Nuevos dictámenes (PE) o cambios de fase relevantes (EC)

Si a las 9 AM no hay novedades, intenta de nuevo a las 10 AM. En ambos casos
el correo se manda **una sola vez por día** (el estado se guarda en
`data/alert_sent_log.json`).

## Setup inicial

### 1. Generar Gmail app password

(Solo si tu cuenta `@valiconsultores.com` es Google Workspace; sino, contactá
al admin del dominio.)

1. Andá a https://myaccount.google.com/apppasswords
2. Ingresá con tu cuenta
3. Generá un app password nuevo. Nombre sugerido: "Radar Legislativo"
4. Copiá los 16 caracteres (espacios opcionales). Ese es tu `GMAIL_APP_PASSWORD`.

Si no podés acceder a la página de app passwords, tu cuenta debe tener
2-Step Verification activado primero (https://myaccount.google.com/signinoptions/two-step-verification).

### 2. Configurar GitHub Secrets

En el repo en GitHub: **Settings → Secrets and variables → Actions → New repository secret**

Agregá 3 secrets:

| Nombre                 | Valor                                    |
|------------------------|------------------------------------------|
| `GMAIL_USER`           | nicolas.silva@valiconsultores.com        |
| `GMAIL_APP_PASSWORD`   | (los 16 chars del paso 1)                |
| `ALERT_RECIPIENT`      | nicolas.silva@valiconsultores.com        |

### 3. Activar GitHub Actions

En **Settings → Actions → General → Workflow permissions**:
- Marcá **"Read and write permissions"** (para que el workflow pueda commitear
  el log de alertas)
- Marcá **"Allow GitHub Actions to create and approve pull requests"** (opcional)

### 4. Probar manualmente la primera vez

En **Actions** del repo → seleccioná **"Alertas diarias Radar Legislativo"** →
**Run workflow**. Dejá los inputs en default y dale Run.

Tarda ~5-10 min la primera corrida (porque hace bootstrap completo de Peru
desde el snapshot gzipped). Las siguientes corridas son ~3-5 min porque la
DB queda cacheada.

Si todo OK, vas a recibir un email a las 9 AM de Lima cada día.

## Test local

```powershell
# Test sin enviar (dry run)
python -m alerts.cli send --dry-run

# Test real (necesita .env con GMAIL_USER + GMAIL_APP_PASSWORD)
python -m alerts.cli send --force
```

Crear `.env` en la raíz del repo (ya gitignored):
```
GMAIL_USER=nicolas.silva@valiconsultores.com
GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
ALERT_RECIPIENT=nicolas.silva@valiconsultores.com
```

## Estructura

- `alerts/build.py` — queries PE+EC, ventana 24h
- `alerts/template.py` — render HTML del correo
- `alerts/send.py` — SMTP Gmail
- `alerts/cli.py` — entry point + lógica 9 AM / 10 AM retry
- `.github/workflows/daily-alerts.yml` — cron 14:00 y 15:00 UTC
- `data/alert_sent_log.json` — estado del scheduler (commiteado por CI)
