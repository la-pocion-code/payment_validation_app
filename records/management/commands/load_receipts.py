# records/management/commands/load_receipts.py
from django.core.management.base import BaseCommand, CommandError
from records.services import CSVProcessor
import os

class Command(BaseCommand):
    help = 'Carga recibos desde un archivo CSV usando la lógica centralizada de CSVProcessor.'

    def add_arguments(self, parser):
        parser.add_argument('csv_file_path', type=str, help='La ruta al archivo CSV para cargar.')

    def handle(self, *args, **options):
        file_path = options['csv_file_path']
        self.stdout.write(self.style.SUCCESS(f'Iniciando la carga de recibos desde: {file_path}'))

        if not os.path.exists(file_path):
            raise CommandError(f'El archivo "{file_path}" no fue encontrado.')

        try:
            # Abrimos el archivo en modo binario ('rb') porque TextIOWrapper (usado dentro de CSVProcessor)
            # se encargará de la decodificación.
            with open(file_path, 'rb') as f:
                # La clase CSVProcessor espera un objeto que tenga un atributo 'file',
                # similar a como Django maneja los archivos subidos. Creamos un objeto simple para simularlo.
                class MockUploadedFile:
                    def __init__(self, file_obj):
                        self.file = file_obj

                mock_file = MockUploadedFile(f)
                
                # Delegamos todo el procesamiento a nuestra clase de servicio
                processor = CSVProcessor(mock_file)
                result = processor.process()

                # Imprimimos los mensajes de resultado en la consola
                for msg_type, text in result.get_messages():
                    style = getattr(self.style, msg_type.upper(), self.style.NOTICE)
                    self.stdout.write(style(text))

        except Exception as e:
            raise CommandError(f'Ocurrió un error inesperado durante el proceso: {e}')
