# Setup cron-job.org — alertas a las 9 AM exacto

GitHub Actions cron tiene latencias variables (0-3+ horas). Para que el
correo llegue **puntual a las 9 AM Lima**, usamos cron-job.org (gratis,
HTTP a horarios precisos) para llamar al `workflow_dispatch` API de
GitHub.

## Paso 1: Crear un GitHub Personal Access Token (PAT)

1. Ir a https://github.com/settings/tokens?type=beta
2. **Generate new token** (fine-grained)
3. Configuración:
   - **Token name**: `cron-job-alertas`
   - **Resource owner**: `nicosil02`
   - **Expiration**: 1 año (o el máximo que GitHub permita)
   - **Repository access**: Only select repositories → `Base_legislativa`
   - **Repository permissions**:
     - `Actions`: **Read and write**
     - `Contents`: **Read**
   - Resto: no access
4. **Generate token**
5. Copiar el token (`github_pat_...`). **No se muestra de nuevo.**

## Paso 2: Configurar cron-job.org

1. Ir a https://cron-job.org/en/ → Sign up gratis
2. **Create cronjob**:
   - **Title**: `Alertas Vali — daily 9 AM Lima`
   - **URL**: `https://api.github.com/repos/nicosil02/Base_legislativa/actions/workflows/daily-alerts.yml/dispatches`
   - **Execution schedule**:
     - Time zone: `America/Lima`
     - Time: `09:00` (cron-job.org dispara con precisión de segundos)
     - Days: Mon, Tue, Wed, Thu, Fri (laborable). Sabado/domingo opcional.
3. **Advanced settings**:
   - **Request method**: `POST`
   - **Headers**:
     ```
     Authorization: Bearer github_pat_TUTOKEN_AQUI
     Accept: application/vnd.github+json
     X-GitHub-Api-Version: 2022-11-28
     ```
   - **Request body** (raw JSON):
     ```json
     {"ref": "main", "inputs": {"slot": "09", "force": "false"}}
     ```
4. **Save**

## Paso 3: Test

En cron-job.org, click **Test run** sobre el cronjob recién creado.
- Si status = `204 No Content` → OK, GitHub recibió el dispatch
- En GitHub → Actions → Alertas diarias deberías ver un nuevo run en ~30 seg

## Funcionamiento

A partir de mañana, cron-job.org dispara a las 9:00:00 AM Lima (sin
atraso) un POST a GitHub Actions API. GitHub recibe el `workflow_dispatch`
y arranca el workflow **inmediatamente** (no usa cron interno). Tiempo
total estimado de email entregado: **9:00 - 9:03 AM** Lima.

## Backup actual

Aunque cron-job.org falle (downtime del servicio), seguimos teniendo:
- `daily-alerts.yml` con cron nativo de GH (atraso 0-3h)
- `refrescar-pe.yml` envía la alerta como step backup cuando corre

`already_sent_today` previene duplicados — solo el primero que llega envía.

## Renovación del PAT

GitHub PATs fine-grained tienen máx 1 año. Marcar calendario para
renovar antes que expire. Cuando expire, cron-job.org devuelve `401`
en su log → vamos a settings de cron-job, actualizamos el header
Authorization con el nuevo PAT, listo.
