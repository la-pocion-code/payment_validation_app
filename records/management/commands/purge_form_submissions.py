from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from records.models import FormSubmission


class Command(BaseCommand):
    help = (
        'Borra las llaves de idempotencia (FormSubmission) más antiguas que N días. '
        'Los tokens solo son útiles durante la ventana de reintentos del navegador, '
        'así que no hace falta conservarlos.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=7,
            help='Antigüedad mínima en días para borrar un token (por defecto: 7).'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Solo informa cuántos tokens se borrarían, sin borrar nada.'
        )

    def handle(self, *args, **options):
        days = options['days']
        cutoff = timezone.now() - timedelta(days=days)
        queryset = FormSubmission.objects.filter(created_at__lt=cutoff)
        total = queryset.count()

        if options['dry_run']:
            self.stdout.write(self.style.NOTICE(
                f'[dry-run] Se borrarían {total} tokens anteriores a {cutoff:%d-%m-%Y %H:%M}.'
            ))
            return

        deleted, _ = queryset.delete()
        self.stdout.write(self.style.SUCCESS(
            f'{deleted} tokens eliminados (anteriores a {cutoff:%d-%m-%Y %H:%M}). '
            f'Quedan {FormSubmission.objects.count()} en total.'
        ))
