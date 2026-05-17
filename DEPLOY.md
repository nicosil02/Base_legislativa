# Deploy a Streamlit Cloud

Sistema todo-en-uno con Streamlit Cloud (hosting gratis) + GitHub Actions
(cron gratis) + Resend (email gratis 3000/mes).

## 1. Pre-requisitos

- Repo PUBLICO en GitHub (`nicosil02/Base_legislativa`). Listo.
- Cuenta en Resend con API key (`RESEND_API_KEY`). Ya configurada.
- Cuenta en Streamlit Cloud (gratis con tu cuenta de GitHub).

## 2. Generar secrets adicionales

### JWT_SECRET (para firmar magic link tokens)

Corre esto en tu terminal local para generar uno random:
```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```
Guardalo, va al secret `JWT_SECRET` en Streamlit Cloud (paso 4).

### GH_TOKEN (Personal Access Token, para persistir users.json)

1. Anda a https://github.com/settings/personal-access-tokens/new
2. Token name: "Vali Intelligence users.json write"
3. Expiration: 1 year (o forever)
4. Resource owner: `nicosil02`
5. Repository access: select repositories → `Base_legislativa`
6. Permissions → Repository permissions → **Contents: Read and write**
7. Generate token → copia el token (empieza con `github_pat_...`)

## 3. Deploy en Streamlit Cloud

1. Anda a https://share.streamlit.io
2. Login con tu GitHub
3. **New app** → repo `nicosil02/Base_legislativa` → branch `main` → file `app.py`
4. App URL: por ejemplo `vali-intelligence.streamlit.app`
5. **Advanced settings → Secrets** (pega esto como TOML):

```toml
RESEND_API_KEY = "re_xxxxxxxxxxxxxxxxxxxx"
RESEND_FROM = "Vali Intelligence <onboarding@resend.dev>"
ALERT_RECIPIENT = "nicolas.silva@valiconsultores.com"
JWT_SECRET = "tu-jwt-secret-del-paso-2"
APP_BASE_URL = "https://vali-intelligence.streamlit.app"
GH_TOKEN = "github_pat_xxxxxxxx"
GH_REPO = "nicosil02/Base_legislativa"
GH_BRANCH = "main"
```

6. Click **Deploy**. Tarda ~2 min en buildearse.
7. Una vez UP, anda a `https://vali-intelligence.streamlit.app` y deberias
   ver la pantalla de login.

## 4. Primer login

1. Ingresa tu email `nicolas.silva@valiconsultores.com`
2. Recibis un correo con el magic link
3. Click → te loguea automaticamente

A partir de aqui podes invitar a colegas: cualquier @valiconsultores.com puede
entrar con su email + magic link. Cada nuevo registro commitea automaticamente
`data/users.json` al repo.

## 5. Alertas diarias (ya funcionando)

GitHub Actions ya tiene el workflow `daily-alerts.yml` corriendo:
- 9 AM Lima (14:00 UTC) — alerta si hay novedades
- 10 AM Lima (15:00 UTC) — retry si 9 AM no envio

Tras este cambio, las alertas se envian a TODOS los usuarios registrados en
`data/users.json`, no solo al hardcoded ALERT_RECIPIENT.

## 6. Costos

| Servicio | Plan | Costo |
|----------|------|-------|
| Streamlit Cloud | Free (public repo) | $0/mes |
| GitHub Actions | 2000 min/mes free | $0/mes |
| Resend | 3000 emails/mes free | $0/mes |
| **Total** | | **$0/mes** |

Soporta hasta ~100 usuarios sin tocar limites. Si superas Resend free, $20/mes
te da 50k emails. Si superas GH Actions free... cualquiera; el job dura ~2 min.
