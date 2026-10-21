# Montar todo de cero

Guia para levantar el sistema en otra PC o en otra cuenta de GitHub. Los
valores de los secretos no estan aca, solo los nombres y para que sirven.

## 1. Codigo y Python

Python 3.13 (el mismo que usa CI). En Windows los comandos van en Git Bash.

```bash
git clone https://github.com/nicosil02/Base_legislativa.git
cd Base_legislativa
python -m venv .venv
source .venv/Scripts/activate        # Linux/Mac: source .venv/bin/activate
pip install -r requirements.txt -c constraints.txt
```

- `requirements.txt` tiene lo que usa la app de Streamlit.
- `constraints.txt` fija la version exacta de todo lo que instalan los
  workflows (sale de los logs de CI). Cualquier `pip install` suelto va con
  `-c constraints.txt` para caer en la misma version que CI. El test
  `core/test_workflows.py` falla si un workflow lo olvida.
- Para correr los scrapers que abren navegador (Ecuador, comisiones EC en
  Facebook) hace falta ademas
  `pip install playwright -c constraints.txt && python -m playwright install chromium`.

Los workflows usan Python 3.13, menos
`votaciones-ocr.yml` y `votaciones-ocr-bicameral.yml`, que usan 3.12 (corren
PaddleOCR; `refrescar-pe.yml` corre el mismo PaddleOCR en 3.13 sin problema,
asi que se pueden pasar a 3.13 cuando haga falta). constraints.txt sirve para
las dos.

## 2. Bases de datos

Las bases viven en la rama `datos`, no en `main` (ver `scripts/publicar_db.sh`).

```bash
bash scripts/bajar_db.sh proyectos.db.gz proyectos.db
bash scripts/bajar_db.sh proyectos_ec.db.gz proyectos_ec.db
```

`proyectos.db` se publica en partes y el script la arma sola. `cerebro.db` y
el grafo (`data/grafo/`) los baja la app la primera vez desde el release
`cerebro` de GitHub, no hay que hacer nada.

## 3. Correr la app y los tests

```bash
python -m streamlit run app.py
pip install pytest pyyaml faster-whisper -c constraints.txt
python -m pytest
```

Para la app local los secretos van en un archivo `.env` en la raiz
(`NOMBRE=valor`, uno por linea) o en `.streamlit/secrets.toml`. Los dos
estan en `.gitignore`.

## 4. Secretos de GitHub Actions

Se cargan en Settings > Secrets and variables > Actions del repo.

| Secreto | Para que sirve |
|---|---|
| `GEMINI_API_KEY` | Gemini (tier gratis) para resumir sesiones, avisos de TV, grafo del cerebro y el juez "mismo hecho". Tambien es la clave de los datos de clientes (llega a cada workflow como `CLIENTES_CLAVE`, ver seccion 6b) |
| `TELEGRAM_BOT_TOKEN` | Token del bot de alertas (@RadarValiAlertasBot) |
| `TELEGRAM_CHAT_ID` | Chat o grupo donde el bot manda los avisos |
| `CALLMEBOT_PHONE` | Numero de WhatsApp para CallMeBot (respaldo si Telegram falla) |
| `CALLMEBOT_APIKEY` | API key de CallMeBot para ese numero |
| `RESEND_API_KEY` | Envio del correo diario por Resend (lo manda `refrescar-pe.yml`) |
| `RESEND_FROM` | Remitente del correo |
| `ALERT_RECIPIENT` | Destinatario del correo si no hay usuarios registrados en `data/users.json` |
| `GITHUB_TOKEN` | Lo crea GitHub solo en cada corrida; se usa para hacer push de datos y bajar releases. No hay que cargarlo |

## 5. Secretos de Streamlit Cloud

Se cargan en Manage app > Settings > Secrets (formato TOML). La app los pasa
a variables de entorno al arrancar (`app.py`).

| Secreto | Para que sirve |
|---|---|
| `GEMINI_API_KEY` | Chat sobre transcripciones y preguntas al grafo del cerebro |
| `GH_TOKEN` | Token de GitHub (permiso Contents lectura y escritura) para guardar decisiones, descartes, usuarios y pedidos de video en el repo |
| `GH_REPO` | `nicosil02/Base_legislativa` |
| `GH_BRANCH` | Rama donde se guardan esos archivos (por defecto `main`) |
| `[auth]` | Login con Google. Lleva `redirect_uri` y `cookie_secret`, y dentro `[auth.google]` van `client_id`, `client_secret` y `server_metadata_url`. Si falta, la app queda abierta sin login |
| `TURSO_URL_<BASE>` y `TURSO_TOKEN` | Opcional. Base alojada en Turso en vez del sqlite local (ej. `TURSO_URL_PROYECTOS`). Hoy no se usa |

En Streamlit Cloud la app se crea con repo `nicosil02/Base_legislativa`,
rama `main`, archivo `app.py` y Python 3.13.

## 6. Servicios externos

- **cron-job.org** dispara `vigilar-congreso.yml` cada 10 minutos por la API
  de GitHub, porque el cron de GitHub se atrasa horas. Necesita un token de
  GitHub con permiso Actions. Paso a paso en `docs/cron-job-org-setup.md`.
- **Bot de Telegram** se crea con @BotFather (da el token). El chat id sale
  de mandarle un mensaje al bot y leer `getUpdates`.
- **Gemini** da la API key gratis en Google AI Studio.
- **Resend** manda el correo con una cuenta gratis, de ahi salen `RESEND_API_KEY` y
  el remitente.
- **CallMeBot** es el respaldo por WhatsApp, se activa mandando el mensaje que
  indica su web.
- **Cloudflare WARP** lo instalan solos los workflows que bajan de YouTube y lo
  prenden en modo proxy (puerto 40000), sin cuenta. YouTube bloquea las
  IP de GitHub y WARP les da otra. No hay nada que configurar.
- **Google Cloud (OAuth)** tiene el cliente del login con Google, de donde
  salen `client_id` y `client_secret`. La URL de redireccion es la de la app
  terminada en `/oauth2callback`.

## 6b. Datos de clientes (cifrados)

El repo es publico, asi que perfiles, historial de alertas y matrices de
clientes van en git solo como `clientes/**/*.cifrado` (`clientes/privado.py`).
La web y los workflows los abren solos con el valor de `GEMINI_API_KEY`. En
una PC nueva:

```bash
export CLIENTES_CLAVE="<el mismo valor de GEMINI_API_KEY>"
python -m clientes.privado abrir      # .cifrado -> texto (tras git pull: --pisar)
python -m clientes.privado cerrar     # texto -> .cifrado, antes de hacer commit
```

Sin la clave la app arranca igual, pero sin clientes. Si se cambia la clave
de Gemini: primero `abrir` con la vieja, despues `cerrar` con la nueva y
recien ahi cambiar el secreto.

### Cliente nuevo (sin tocar codigo)

```bash
python -m clientes.nuevo crear acme --nombre "Acme" --paises PE,EC
# llenar clientes/acme/cliente.json y notas.md (Claude puede hacerlo con el bluebook)
python -m clientes.nuevo probar acme --dias 30   # que le habria llegado el ultimo mes
python -m clientes.privado enviar clientes/acme  # commit + push de los .buzon; GitHub los cifra
```

Un rubro que no esta en `noticias/temas.py` (mineria, energia...) va en la
ficha como `temas_propios`; normas de su interes, en `palabras_norma`. Los
jueces de Gemini (resumen en vivo, agendas, TV) leen `notas.md`.

## 7. Subir una version

Cambiar el numero en `constraints.txt` (y en `requirements.txt` si la usa la
app), hacer push y ver que pase `tests.yml` y el workflow que usa ese
paquete. Hay versiones fijas con motivo, anotado en el mismo archivo
(PyAV antes de 19, paddlepaddle 3.2.2, numpy, pillow, huggingface-hub).
