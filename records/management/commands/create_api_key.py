from django.core.management.base import BaseCommand, CommandError

from records.models import ApiKey


class Command(BaseCommand):
    help = (
        "Crea una llave de acceso a la API REST para una integración (Odoo, intranet...). "
        "La llave se muestra UNA sola vez."
    )

    def add_arguments(self, parser):
        parser.add_argument('name', help='Nombre de la integración, p. ej. "Odoo"')
        parser.add_argument('--write', action='store_true',
                            help='Permite escribir (POST/PATCH). Sin esto, la llave es de solo lectura.')

    def handle(self, *args, **options):
        name = options['name'].strip()
        if ApiKey.objects.filter(name=name).exists():
            raise CommandError(f'Ya existe una llave para "{name}". Desactívela en el admin o use otro nombre.')
        api_key, raw_key = ApiKey.issue(name, can_write=options['write'])
        permiso = 'lectura y escritura' if api_key.can_write else 'solo lectura'
        self.stdout.write(self.style.SUCCESS(f'Llave creada para "{name}" ({permiso}).'))
        self.stdout.write('Guárdela ahora; no se puede volver a consultar:\n')
        self.stdout.write(f'    {raw_key}\n')
        self.stdout.write(f'Uso:  Authorization: Api-Key {raw_key}')
