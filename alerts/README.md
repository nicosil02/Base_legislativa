# Alertas diarias por email

Sistema de alertas que manda un correo a las **9 AM (Lima/Quito)** con:
- Nuevos proyectos de ley presentados en las ultimas 24h
- Nuevos dictamenes (PE) o cambios de fase relevantes (EC)

Si a las 9 AM no hay novedades, intenta de nuevo a las 10 AM. En ambos casos
el correo se manda **una sola vez por dia** (el estado se guarda en
`data/alert_sent_log.json`).

## Setup inicial

### 1. Crear cuenta en Resend

1. Anda a https://resend.com/signup
2. Crea cuenta con tu mail `nicolas.silva@valiconsultores.com`
3. Una vez logueado, anda a https://resend.com/api-keys
4. Click **Create API Key**, nombre "Radar Legislativo", permission "Sending access"
5. **Copia la key** (empieza con `re_...`). Solo se muestra una vez.

### 2. (Opcional) Verificar dominio valiconsultores.com

Por default, el correo se manda desde `onboarding@resend.dev` (es la
direccion sandbox de Resend, funciona sin verificacion pero el destinatario
ve que viene de un dominio ajeno).

Si queres que aparezca **"de"** `nicolas.silva@valiconsultores.com` o
`alertas@valiconsultores.com`, necesitas agregar 3 DNS records (SPF, DKIM,
DMARC) en valiconsultores.com. Como esto requiere acceso al DNS del dominio
(probablemente del admin IT de Vali), podes posponerlo. Mientras tanto
usamos `onboarding@resend.dev` y funciona igual.

Si lo queres hacer: Resend dashboard → Domains → Add domain →
`valiconsultores.com` → seguir las instrucciones. Una vez verificado, pone
la direccion `Radar Legislativo <alertas@valiconsultores.com>` (o lo que
prefieras) en el secret `RESEND_FROM` (paso 3).

### 3. Configurar GitHub Secrets

En el repo GitHub: **Settings → Secrets and variables → Actions → New repository secret**

Agrega estos secrets:

| Nombre              | Valor                                          |
|---------------------|------------------------------------------------|
| `RESEND_API_KEY`    | la key del paso 1 (re_...)                    |
| `ALERT_RECIPIENT`   | nicolas.silva@valiconsultores.com             |
| `RESEND_FROM`       | (opcional) "Radar Legislativo <alertas@valiconsultores.com>" si verificaste el dominio. Sino dejalo vacio. |

### 4. Permisos del workflow

Settings → **Actions → General → Workflow permissions**:
- Marca **"Read and write permissions"**
- Save

### 5. Probar manualmente la primera vez

En **Actions → Alertas diarias Radar Legislativo → Run workflow**.

Tarda ~5-10 min la primera corrida (bootstrap inicial de Peru). Las
siguientes son ~3-5 min porque la DB queda en cache.

Si todo OK, vas a recibir un email a tu inbox.

## Test local

Crea un `.env` en la raiz del repo (ya gitignored):
```
RESEND_API_KEY=re_xxxxxxxxxxxxxxxxxxxx
ALERT_RECIPIENT=nicolas.silva@valiconsultores.com
```

Despues:
```powershell
# Dry run: imprime HTML, no envia
python -m alerts.cli send --dry-run

# Envio real (requiere .env con la API key)
python -m alerts.cli send --force
```

## Estructura

- `alerts/build.py` - queries PE + EC, ventana 24h
- `alerts/template.py` - render HTML del correo
- `alerts/send.py` - cliente HTTP de Resend
- `alerts/cli.py` - entry point + logica 9 AM / 10 AM retry
- `.github/workflows/daily-alerts.yml` - cron 14:00 y 15:00 UTC
- `data/alert_sent_log.json` - estado del scheduler (commiteado por CI)
