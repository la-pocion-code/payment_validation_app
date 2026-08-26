# CLAUDE.md — payment_validation_app

Contexto del proyecto para asistentes de IA. Idioma del repo: **español** (UI, commits, docs).

## Qué es

Aplicación web interna en **Django** para gestionar y **validar registros de pagos** de
**La Poción** (Colombia). Control de acceso por roles, auditoría completa de cambios,
importación masiva CSV/Excel y detección de duplicados. Desplegada en **Railway**.

## Stack

| Capa | Tecnología |
|---|---|
| Backend | Django 5.2.5 + Django REST Framework 3.14 |
| Base de datos | PostgreSQL (Railway) / SQLite (fallback local) vía `dj-database-url` |
| Servidor | Gunicorn |
| Estáticos | WhiteNoise (`CompressedManifestStaticFilesStorage`) |
| Auth | `social-auth-app-django` (Google OAuth2) |
| Auditoría | `django-simple-history` |
| Filtros | `django-filter` |
| Datos | pandas, openpyxl (CSV/Excel), `holidays` (festivos Colombia) |
| Deploy | Railway.app |

## Estructura

- **App única: `records/`**
  - `models.py` — modelos de dominio (ver abajo)
  - `views.py` — vistas (archivo grande, ~112 KB; corazón de la lógica de UI)
  - `forms.py`, `filters.py`, `services.py`, `urls.py`, `admin.py`
  - `pipeline.py` — pasos custom del pipeline de social-auth
  - `context_processors.py` — contadores de duplicados/solicitudes y grupos del usuario
  - `decorators.py`, `utils.py`
  - `management/commands/` — `load_clients.py`, `load_receipts.py`
  - `templates/`, `static/`, `migrations/`
- **Config: `financial_tracker/`** — `settings.py`, `urls.py`, `wsgi.py`, `asgi.py`
- `manage.py`, `Procfile`, `requirements.txt`

## Modelos clave (`records/models.py`)

- `FinancialRecord` — recibo financiero central. `payment_status` (Pendiente/Aprobado/Rechazado),
  FK opcional a `Transaction`, `linked_credit_note` (self OneToOne). `unique_together`:
  (fecha, hora, comprobante, banco_llegada, valor).
- `Transaction` — venta/facturación. `status` (Pendiente/Facturado/Anulado/No Facturable),
  `unique_transaction_id`; `receipts_total` y `difference` como propiedades.
- `Client` — nombre + DNI único; propiedad `available_balance`.
- Catálogos: `Bank`, `Seller`, `PaymentDocument`, `OrigenTransaccion`, `TransactionType`.
- `DuplicateRecordAttempt` — registra intentos de duplicado (DUPLICATE/SIMILAR).
- `AccessRequest` — onboarding de nuevos usuarios.
- `AuthorizedUser` — usuarios autorizados.
- `FormSubmission` — llave de idempotencia por envío de formulario (PK = token UUID).

## Autenticación y roles

- Google OAuth2 restringido a dominios `@lapocion.com` y `@gmail.com`.
- Pipeline custom en `records/pipeline.py`: `require_email_domain`, `create_access_request`,
  `set_superuser_flag` (referenciados en `SOCIAL_AUTH_PIPELINE` de `settings.py`).
- `ADMIN_EMAILS` (en `settings.py`) reciben superuser: `jcorrea`, `venriquez`, `wcastro` @lapocion.com.
- Grupos Django: **Admin**, **Digitador** (crear registros), **Facturador** (editar factura),
  **Validador** (cambiar `payment_status`).
- Usuarios nuevos quedan en espera hasta que un Admin aprueba su `AccessRequest`.

## Comandos de desarrollo

Entorno virtual local: `tutorial-env`. Variables en `.env` (ver `README.md` para la lista;
`.env` está gitignorado).

```bash
python manage.py runserver        # servidor de desarrollo
python manage.py migrate
python manage.py makemigrations
python manage.py collectstatic --noinput
python manage.py check
python manage.py load_clients     # comando custom
python manage.py load_receipts    # comando custom
```

## Configuración relevante (`financial_tracker/settings.py`)

- `DEBUG` desde env (`'True'`/`'False'`). Con `DEBUG=False` se activan SSL redirect, HSTS,
  cookies seguras y `SECURE_PROXY_SSL_HEADER` (Railway termina SSL en su proxy).
- `ALLOWED_HOSTS` y `CSRF_TRUSTED_ORIGINS` se construyen dinámicamente con `RAILWAY_PUBLIC_DOMAIN`.
- `DATABASES`: usa `DATABASE_URL` si existe (PostgreSQL Railway, `conn_max_age=600`),
  si no cae a SQLite local.
- `LANGUAGE_CODE = 'es'`, `TIME_ZONE = 'America/Bogota'`, `USE_TZ = True`.
- Sesión: `SESSION_COOKIE_AGE = 3600` (1 h), `SESSION_SAVE_EVERY_REQUEST = True`.

## Deploy (Railway)

- Push a `main` → **producción**; push a `staging` → **staging**.
- Flujo recomendado: desarrollar en `staging`, verificar, merge `staging` → `main`.
- `Procfile`: `collectstatic → migrate → gunicorn financial_tracker.wsgi:application`.

## Idempotencia de formularios (duplicados por red inestable)

Los digitadores trabajan con WIFI inestable, así que un mismo POST puede llegar dos veces
(doble clic, F5 → «reenviar formulario», reintento del navegador o del proxy). Antes eso
producía un falso «Registro duplicado exacto» y, cuando el digitador re-digitaba creyendo
que nada se había guardado, un duplicado real.

Mecanismo, en `records/idempotency.py`:

1. `{% submit_token %}` (`records/templatetags/idempotency.py`) emite un UUID nuevo en cada
   render del formulario, junto al `{% csrf_token %}`.
2. `already_submitted(request)` — al **inicio** del POST, antes de instanciar los
   formularios. Si el token ya existe, responde `redirect` + `messages.info` («ya fue
   guardado»). Va antes a propósito: acceder a `form.errors` dispara
   `FinancialRecordForm.clean()`, que anota intentos de duplicado.
3. `claim_submission(request, scope)` — **primera** sentencia dentro del `transaction.atomic()`
   que escribe. El `INSERT` de la PK duplicada es lo que resuelve la carrera (en PostgreSQL
   espera al commit/rollback rival). Levanta `DuplicateSubmission`, que se captura **fuera**
   del atomic.
4. `complete_submission(claim, ...)` — al final, dentro del mismo atomic, guarda la URL de
   destino para un reenvío posterior. Si el guardado falla, el rollback libera el token.

Aplicado en las cuatro vías que crean recibos: `create_bulk_receipts`, `CreditCreateView`,
`TransactionUpdateView` y `create_credit_note_from_surplus` (esta última suma
`select_for_update` sobre la `Transaction` y comprobante determinista como llave).

Apoyos: `records/static/js/submit-once.js` (guard de doble submit, opt-in con
`data-submit-once`), `@never_cache` en las vistas de formulario (evita que bfcache devuelva
un token ya consumido) y captura de `IntegrityError` para no responder 500.

Comandos: `python manage.py diagnose_duplicates` (informe de solo lectura) y
`python manage.py purge_form_submissions --days 7`.

## Convenciones

- Español en UI y mensajes de commit.
- Auditoría de cambios con `django-simple-history` en `FinancialRecord` y `Transaction`.
- Cálculo de fecha efectiva considera festivos colombianos (`holidays`).

## graphify (grafo de conocimiento)

Existe un grafo del código en `graphify-out/` (`graph.json`, `graph.html`, `GRAPH_REPORT.md`),
ignorado por git. Consultable con `/graphify query "<pregunta>"`,
`/graphify explain "<nodo>"` o `/graphify path "A" "B"`. Reconstruir tras cambios de código
con `/graphify . --update`.
