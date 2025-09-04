# Validacion de Pagos

Financial Tracker es una aplicación web desarrollada con Django para gestionar y validar registros de pagos. Proporciona un control de acceso basado en roles, permitiendo que diferentes usuarios (Administradores, Digitadores y Facturadores) realicen acciones específicas. La aplicación admite la entrada manual de datos, la carga masiva de archivos CSV y rastrea el historial de todos los cambios.

## Características

*   **Autenticación de Usuarios:** Inicio de sesión seguro utilizando cuentas de Google.
*   **Control de Acceso Basado en Roles:**
    *   **Admin:** Acceso completo a todas las funciones, incluida la gestión de usuarios, eliminación de registros y configuración del sistema.
    *   **Digitador:** Puede crear nuevos registros financieros.
    *   **Facturador:** Puede actualizar registros existentes con información de facturas.
*   **Operaciones CRUD:** Operaciones de Crear, Leer, Actualizar y Eliminar para registros financieros y bancos.
*   **Carga Masiva de CSV:** Los administradores pueden cargar registros financieros de forma masiva utilizando un archivo CSV. El sistema valida los datos y evita entradas duplicadas.
*   **Filtros Avanzados:** Busca y filtra registros fácilmente por fecha, estado, cliente y más.
*   **Pista de Auditoría:** Se utiliza `django-simple-history` para rastrear todos los cambios realizados en los registros financieros, proporcionando un historial completo para fines de auditoría.
*   **Exportar Datos:** Exporta los registros financieros filtrados a un archivo CSV.
*   **Prevención de Duplicados:** El sistema identifica y marca los intentos de crear registros duplicados.
*   **Sistema de Solicitud de Acceso:** Los nuevos usuarios son puestos en una cola de espera hasta que un administrador apruebe su acceso.

## Tecnologías Utilizadas

*   **Backend:** Django
*   **Base de Datos:** SQLite (para desarrollo), PostgreSQL 
*   **Autenticación:** `social-auth-app-django` con el proveedor de Google.
*   **Frontend:** Plantillas de Django, HTML, CSS
*   **Otras Librerías Clave:**
    *   `django-filter`: Para filtrar QuerySets.
    *   `django-simple-history`: Para auditoría y control de versiones de los modelos.
    *   `python-decouple`: Para separar la configuración del código fuente.

## Instalación

1.  **Clona el repositorio:**
    ```bash
    git clone <url-de-tu-repositorio>
    cd payment_validation_app
    ```

2.  **Crea y activa un entorno virtual:**
    ```bash
    # Para Windows
    python -m venv app-env
    app-env\Scripts\activate

    # Para macOS/Linux
    python3 -m venv app-env
    source app-env/bin/activate
    ```

3.  **Instala las dependencias:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Configura las variables de entorno:**
    Crea un archivo `.env` en el directorio `financial_tracker/financial_tracker/` (el mismo directorio que `settings.py`). Añade las siguientes variables:
    ```
    SECRET_KEY='tu-clave-secreta-de-django'
    SOCIAL_AUTH_GOOGLE_OAUTH2_KEY='tu-clave-oauth2-de-google'
    SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET='tu-secreto-oauth2-de-google'

    # Opcional: Para la base de datos PostgreSQL en producción
    # DB_NAME='nombre-de-tu-bd'
    # DB_USER='usuario-de-tu-bd'
    # DB_PASSWORD='contraseña-de-tu-bd'
    # DB_HOST='localhost'
    # DB_PORT=5432
    ```

5.  **Ejecuta las migraciones de la base de datos:**
    ```bash
    python financial_tracker/manage.py migrate
    ```

6.  **Crea un superusuario (opcional, para la configuración inicial):**
    ```bash
    python financial_tracker/manage.py createsuperuser
    ```

7.  **Ejecuta el servidor de desarrollo:**
    ```bash
    python financial_tracker/manage.py runserver
    ```
    La aplicación estará disponible en `http://127.0.0.1:8000/`.

## Uso

1.  Accede a la aplicación en tu navegador web.
2.  Inicia sesión con tu cuenta de Google.
3.  Si eres un usuario nuevo, serás dirigido a una página para solicitar acceso. Un administrador debe aprobar tu solicitud.
4.  Una vez aprobado, serás redirigido al panel principal donde podrás ver y gestionar los registros financieros según el rol que te haya sido asignado.

*   **Administradores:** Pueden ver todos los registros, gestionar usuarios, cargar archivos CSV y realizar todas las operaciones CRUD.
*   **Digitadores:** Pueden añadir nuevos registros de pago.
*   **Facturadores:** Pueden editar registros existentes para añadir detalles de la factura.
