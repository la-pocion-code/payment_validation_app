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
- **Sin rol no se ve nada**: `records.middleware.RoleRequiredMiddleware` manda a
  `request_access` (403 JSON en AJAX y `/api/`) a todo usuario con sesión que no sea
  superusuario ni tenga grupo, y le crea o reabre su `AccessRequest` para que aparezca en
  «Usuarios». Las vistas conservan además su propio `group_required`.
- **Editar transacción no debe escribir si nada cambió**: `TransactionUpdateView.form_valid`
  compara contra lo guardado antes de `save()`; los campos ocultos de los roles de solo
  lectura deben enviar el valor exacto (hora con segundos, observación vacía y no «None»).
  Hay pruebas (`GuardarSinCambiosTests`) que envían el formulario tal cual lo pinta cada rol.

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

5. **Segundo chequeo** en la rama de formulario inválido, antes de `flush_duplicate_attempts`:
   con varios workers dos POST del mismo formulario pueden cruzarse (el segundo pasa la fase 1
   antes del commit del primero y su `clean()` ya ve el recibo). Se repite `already_submitted`
   y se responde «ya fue guardado» en vez de registrar un duplicado falso.

Aplicado en las cuatro vías que crean recibos: `create_bulk_receipts`, `CreditCreateView`,
`TransactionUpdateView` y `create_credit_note_from_surplus` (esta última suma
`select_for_update` sobre la `Transaction` y comprobante determinista como llave).

Apoyos: `records/static/js/submit-once.js` (guard de doble submit, opt-in con
`data-submit-once`), `@never_cache` en las vistas de formulario (evita que bfcache devuelva
un token ya consumido) y captura de `IntegrityError` para no responder 500.

Comandos: `python manage.py diagnose_duplicates` (informe de solo lectura) y
`python manage.py purge_form_submissions --days 7`.

## Servidor (gunicorn)

La configuración está en `gunicorn.conf.py` (gthread, 3 workers × 4 hilos, timeout 120 s),
**no** en el `Procfile`: el servicio de Railway tiene su propio «start command» en el panel,
que es el que se ejecuta y deja al `Procfile` sin efecto. gunicorn carga ese archivo solo.

Reglas que evitan las caídas que hubo con 1 worker sync:

- Todo reporte CSV sale con `stream_csv()` (`records/utils.py`) sobre `queryset.iterator()`.
- Las listas no consultan por fila: `select_related`/`Prefetch` en la vista y totales
  calculados sobre lo precargado (`receipts_total_calc`, `difference_calc`), no con las
  propiedades `Transaction.receipts_total`/`.difference`, que lanzan un `aggregate` cada vez.
  Hay pruebas que fallan si el número de consultas crece con las filas.

## API REST (`/api/v1/`)

Paquete `records/api/` (DRF + drf-spectacular). Guía para integradores: `docs/API.md`;
Swagger en `/api/v1/docs/`.

- **Auth**: `Authorization: Api-Key <llave>` (modelo `ApiKey`, se guarda el hash; se crean con
  `python manage.py create_api_key "Odoo" --write` o en el admin) o sesión de la app.
  Permisos en `records/api/auth.py::ApiAccess`: la llave escribe solo con `can_write`; un
  usuario con sesión escribe según `write_groups` del viewset.
- **Recursos**: `transactions`, `receipts`, `clients` (GET/POST/PATCH, sin DELETE ni PUT) y
  catálogos de solo lectura.
- **Duplicados**: `check_receipt_duplicates()` en `records/api/serializers.py` replica la regla
  de `FinancialRecordForm.clean()` y responde `409`. Si se cambia una, cambiar la otra (y el
  aviso previo `views.check_receipt_duplicate`, que es la tercera copia de la regla).
- **Idempotencia**: cabecera `Idempotency-Key` sobre la misma tabla `FormSubmission`
  (`records/api/idempotency.py`).
- **Sincronización**: `?updated_since=` usa `Transaction.updated_at` y
  `FinancialRecord.modificado`. Ojo: `QuerySet.update()` no dispara `auto_now`; al usarlo
  sobre recibos hay que pasar `modificado=timezone.now()`.
- `odoo_id` en `Client` y `Transaction` para la referencia cruzada con Odoo.

## Interfaz (Tailwind + HTMX sobre plantillas Django)

Migración por pantallas; no hay SPA. Estado: **hechos** el marco (`base.html`: barra lateral
plegable, buscador global, avisos tipo toast, barra de progreso, aviso de sesión por vencer),
la lista de Transacciones, la lista y el detalle de Recibos, los formularios de captura
(`create_bulk_receipts.html`, `transaction_form.html`, `credit_form.html`), la bandeja de
duplicados y «Alertas por correo».
También catálogos, clientes, usuarios, historial de duplicados, historial de la transacción
y cargas de archivo. **Pendientes** (poco uso, solo administradores): registros y
transacciones eliminados, `record_history.html` y las páginas de acceso denegado.

- **Catálogos, clientes y usuarios** comparten `components/catalog_table.html`,
  `components/modal_form.html`, `components/modal_confirm_delete.html` y
  `records/static/js/catalog.js`: un botón `data-pv-modal data-url="…"` abre la ventana y
  carga el parcial que la vista devuelve a AJAX. Eliminar algo en uso (`ProtectedError`) lo
  convierte `ProtectedDeleteMiddleware` en un mensaje, no en un 500.
Los avisos (toasts) van abajo a la derecha, salvo en pantallas con `.pv-actionbar`, donde suben
para no tapar el botón de guardar.

- **Marca**: logo `images/pocion-logo.svg` (el `pcn-pocion-logo-2025.svg` de la intranet) y
  `images/favicon.svg` (el favicon de la intranet). Los correos usan `correo/logo-pocion.png`.
- **Buscador global** (`views.global_search`, parcial `partials/search_results.html`):
  transacciones por ID, factura o cliente; recibos por comprobante o valor exacto; clientes.
  Atajo «/» o Ctrl+K; el teclado lo maneja `app.js`.
- **Recibos**: `CreditListView` devuelve `partials/credits_table.html` a HTMX. El cambio de
  estado y «Revisado» en línea van por `data-pv-status` / `data-pv-review` en `app.js`, contra
  las vistas AJAX de siempre. `window.pvConfirm({...})` reemplaza a `confirm()`.
- **Captura**: `records/static/js/capture.js` es común a los dos formularios
  (`<form data-pv-capture>`): resumen fijo `pvCaptureSummary(venta, recibos)`, atajos Alt+N y
  Ctrl+Enter, aviso al salir sin guardar y **aviso previo de duplicado** contra
  `views.check_receipt_duplicate` (solo lectura, no registra intentos).

- **CSS**: fuente en `frontend/app.css`; `cd frontend && npm install && npm run build:css` genera
  `records/static/css/app.css`, que **se versiona** (Railway no usa Node). Tras cambiar
  clases `tw:` en una plantilla hay que recompilar y commitear el CSS.
- Tailwind va **con prefijo `tw:` y sin preflight** porque Bootstrap y jQuery UI siguen
  cargados para las pantallas sin migrar (comparten nombres como `mb-3` o `collapse`).
  Cuando se migre la última, se retiran Bootstrap, jQuery UI y `custom.css`.
- **Componentes** `pv-*` (shell, tarjeta, tabla, badge, chips, toast) definidos en
  `frontend/app.css`; iconos en `records/templates/records/components/icon.html`.
- **Colores**: los de la identidad de marca — rosa `#E50076` principal, púrpura `#5C0F8B`
  secundario, teal `#1DCAD3` para datos, texto `#54565A`.
- **HTMX**: la vista devuelve el parcial (`records/templates/records/partials/`) cuando
  llega la cabecera `HX-Request` (ver `TransactionListView.get_template_names`). El JS común
  está en `records/static/js/app.js` (`window.pvToast(mensaje, tipo)` para avisos).
- La suite usa el storage con manifiesto: tras añadir un estático nuevo, correr
  `python manage.py collectstatic --noinput` antes de `manage.py test`.

## Alertas por correo (duplicados)

Cada `DuplicateRecordAttempt` nuevo puede avisar por correo. Lo decide `DuplicateAlertTemplate`
(una fila por tipo, `DUPLICATE` y `SIMILAR`; la migración 0039 las crea **apagadas**): activo,
destinatarios, copia, asunto y mensaje con variables `{usuario}`, `{comprobante}`, `{valor}`…
Se editan en `/alertas/` (solo superusuarios), con «Enviarme una prueba» y vista previa.

- `records/alerts.py`: receptor `post_save` (conectado en `apps.py`), envío tras el commit y en
  un hilo; un fallo de SMTP se registra en el log y no afecta al guardado.
- `records/correo.py`: el marco de marca, portado de `common/correo_marco.py` de la intranet
  (texto plano como fuente, HTML derivado, «Etiqueta: URL» → botón, logo en línea).
- Variables de entorno: `EMAIL_HOST_USER` y `EMAIL_HOST_PASSWORD` (contraseña de aplicación de
  Workspace), opcionales `EMAIL_HOST`, `EMAIL_PORT`, `DEFAULT_FROM_EMAIL`, `SITE_URL`. Sin
  `EMAIL_HOST_USER` el backend es la consola: el correo queda en el log y no sale.

## Pruebas y CI

`python manage.py test` (113 pruebas: `records/tests.py`, `tests_api.py`, `tests_ui.py`).
`.github/workflows/tests.yml` las corre contra PostgreSQL en cada push a `staging` y `main`,
junto con `check` y `makemigrations --check`. Railway despliega al recibir el push sin esperar
ese resultado, salvo que se active «Wait for CI» en el servicio.

## Convenciones

- Español en UI y mensajes de commit.
- Auditoría de cambios con `django-simple-history` en `FinancialRecord` y `Transaction`.
- Cálculo de fecha efectiva considera festivos colombianos (`holidays`).

## graphify (grafo de conocimiento)

Existe un grafo del código en `graphify-out/` (`graph.json`, `graph.html`, `GRAPH_REPORT.md`),
ignorado por git. Consultable con `/graphify query "<pregunta>"`,
`/graphify explain "<nodo>"` o `/graphify path "A" "B"`. Reconstruir tras cambios de código
con `/graphify . --update`.
