# Validación de Pagos — La Poción

Aplicación web interna desarrollada con Django para gestionar y validar registros de pagos. Proporciona control de acceso basado en roles, auditoría completa de cambios, importación masiva CSV y detección de duplicados.

## Entornos

| Entorno | URL |
|---|---|
| Producción | https://web-production-b0638.up.railway.app |
| Staging | https://web-staging-d62c.up.railway.app |

## Características

- **Autenticación:** Login con Google OAuth2 restringido a dominios `@lapocion.com` y `@gmail.com`
- **Sistema de solicitud de acceso:** Los nuevos usuarios quedan en espera hasta que un Admin apruebe su acceso
- **Control de acceso por roles:**
  - **Admin:** Acceso completo — gestión de usuarios, eliminación de registros, carga CSV, configuración
  - **Digitador:** Crear nuevos registros financieros
  - **Facturador:** Editar registros existentes con información de factura
  - **Validador:** Validar y aprobar registros
- **Operaciones CRUD** sobre registros financieros, bancos, clientes y vendedores
- **Carga masiva CSV:** Importación con validación automática y detección de duplicados
- **Filtros avanzados:** Por fecha, estado, cliente, banco y más
- **Exportación CSV:** De los registros filtrados activos
- **Auditoría completa:** Historial de cambios por registro via `django-simple-history`
- **Gestión de créditos** y control de `OrigenTransaccion`

## Stack tecnológico

| Capa | Tecnología |
|---|---|
| Backend | Django 5.2.5 + Django REST Framework |
| Base de datos | PostgreSQL (Railway) / SQLite (desarrollo local) |
| Servidor | Gunicorn |
| Archivos estáticos | WhiteNoise 6.10.0 |
| Autenticación | social-auth-app-django (Google OAuth2) |
| Auditoría | django-simple-history |
| Deploy | Railway.app |

## Instalación local

### Requisitos previos

- Python 3.11+
- Git

### Pasos

1. **Clonar el repositorio:**
   ```bash
   git clone <url-del-repositorio>
   cd payment_validation_app
   ```

2. **Crear y activar entorno virtual:**
   ```bash
   # Windows
   python -m venv venv
   venv\Scripts\activate

   # macOS / Linux
   python3 -m venv venv
   source venv/bin/activate
   ```

3. **Instalar dependencias:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configurar variables de entorno:**
   Crear archivo `.env` en la raíz del proyecto (junto a `manage.py`):
   ```env
   SECRET_KEY='tu-clave-secreta-de-django'
   DEBUG=True
   SOCIAL_AUTH_GOOGLE_OAUTH2_KEY='tu-client-id-de-google'
   SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET='tu-client-secret-de-google'

   # Opcional: PostgreSQL local (si no se define, usa SQLite)
   # DATABASE_URL=postgresql://usuario:password@localhost:5432/nombre_db
   ```

5. **Ejecutar migraciones:**
   ```bash
   python manage.py migrate
   ```

6. **Iniciar servidor de desarrollo:**
   ```bash
   python manage.py runserver
   ```
   Disponible en `http://127.0.0.1:8000/`

## Deploy en Railway

El deploy es automático vía GitHub:

- Push a `main` → deploy en **producción**
- Push a `staging` → deploy en **staging**

### Variables de entorno requeridas en Railway

| Variable | Descripción |
|---|---|
| `SECRET_KEY` | Clave secreta Django (única por entorno) |
| `DEBUG` | `False` en producción y staging |
| `DATABASE_URL` | Provista automáticamente por Railway PostgreSQL |
| `SOCIAL_AUTH_GOOGLE_OAUTH2_KEY` | Client ID de Google OAuth2 |
| `SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET` | Client Secret de Google OAuth2 |
| `RAILWAY_PUBLIC_DOMAIN` | Provista automáticamente por Railway |

### Proceso de deploy (Procfile)

```
python manage.py collectstatic --noinput && python manage.py migrate && gunicorn financial_tracker.wsgi:application --bind 0.0.0.0:$PORT
```

### Flujo de trabajo recomendado

1. Desarrollar en rama `staging`
2. Verificar en `https://web-staging-d62c.up.railway.app`
3. Merge `staging` → `main` para llevar a producción

## Uso básico

1. Acceder a la app y hacer login con cuenta Google autorizada
2. Los usuarios nuevos deben solicitar acceso — un Admin lo aprueba
3. Según el rol asignado se habilitarán las funciones correspondientes

## Administradores del sistema

- jcorrea@lapocion.com
- venriquez@lapocion.com
- wcastro@lapocion.com
