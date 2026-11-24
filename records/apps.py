from django.apps import AppConfig


class RecordsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'records'

    def ready(self):
        # Aviso por correo cuando se registra un intento de duplicado (records/alerts.py).
        from django.db.models.signals import post_save

        from .alerts import on_attempt_saved
        from .models import DuplicateRecordAttempt

        post_save.connect(on_attempt_saved, sender=DuplicateRecordAttempt,
                          dispatch_uid='records.alerts.duplicate_attempt')
