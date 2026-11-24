"""
Configuración de gunicorn.

Vive aquí y no en el Procfile a propósito: en Railway el servicio tiene su propio
«start command» en el panel, que es el que se ejecuta de verdad y deja al Procfile
sin efecto. Este archivo gunicorn lo carga solo desde el directorio de trabajo,
arranque con el comando que arranque.

Antes corría con los valores por defecto: 1 worker sync y timeout de 30 s. Una sola
petición lenta (un reporte grande) bloqueaba a todos los usuarios y, al pasar de
30 s, gunicorn mataba al único worker: la app quedaba caída mientras el proxy
reintentaba.
"""

import os

# Hilos: las peticiones pasan casi todo su tiempo esperando a PostgreSQL, así que
# varios hilos por worker atienden en paralelo sin gastar memoria en más procesos.
worker_class = 'gthread'
workers = int(os.getenv('WEB_CONCURRENCY', '3'))
threads = int(os.getenv('GUNICORN_THREADS', '4'))

# Con gthread el latido del worker no depende de cuánto dure una petición, así que
# un reporte en streaming largo ya no dispara el timeout.
timeout = int(os.getenv('GUNICORN_TIMEOUT', '120'))
graceful_timeout = 30
keepalive = 5

# Recicla cada worker tras N peticiones (con desfase, para que no reinicien a la vez).
max_requests = 1000
max_requests_jitter = 100

accesslog = '-'
errorlog = '-'
