import pandas as pd
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError
from records.models import Client
import os
import re # Importar el módulo de expresiones regulares

class Command(BaseCommand):
    help = 'Carga clientes desde un archivo CSV o Excel. El archivo debe tener las columnas "name" y "dni".'

    def add_arguments(self, parser):
        parser.add_argument('file_path', type=str, help='La ruta completa al archivo CSV o Excel a procesar.')

    def handle(self, *args, **options):
        file_path = options['file_path']

        # 1. Validar que el archivo existe
        if not os.path.exists(file_path):
            raise CommandError(f'El archivo "{file_path}" no fue encontrado.')

        self.stdout.write(self.style.NOTICE(f'Iniciando la carga de clientes desde: {file_path}'))

        # 2. Leer el archivo con Pandas
        try:
            if file_path.endswith('.csv'):
                df = pd.read_csv(file_path)
            elif file_path.endswith(('.xls', '.xlsx')):
                df = pd.read_excel(file_path)
            else:
                raise CommandError('Formato de archivo no soportado. Use .csv, .xls, o .xlsx')
        except Exception as e:
            raise CommandError(f'Error al leer el archivo: {e}')

        # 3. Validar columnas requeridas
        required_columns = ['name', 'dni']
        if not all(col in df.columns for col in required_columns):
            raise CommandError("El archivo debe contener las columnas 'name' y 'dni'.")

        # 4. Limpiar y procesar los datos
        df.dropna(subset=['name', 'dni'], inplace=True)
        df['dni'] = df['dni'].astype(str) # Asegurar que DNI sea texto

        if df.empty:
            self.stdout.write(self.style.WARNING('El archivo no contiene registros válidos para procesar.'))
            return

        total_rows = len(df)
        created_count = 0
        skipped_count = 0
        
        self.stdout.write(f'Se encontraron {total_rows} registros en el archivo. Procesando...')

        # 5. Iterar y crear clientes
        for index, row in df.iterrows():
            name = str(row['name']).strip()
            dni_raw = str(row['dni']).strip()

            if not name or not dni_raw:
                skipped_count += 1
                continue

            # --- SOLUCIÓN: Limpiar el DNI aquí, ANTES de llamar a get_or_create ---
            # Se aplica la misma lógica de limpieza que en el modelo Client.
            dni = re.sub(r"[^A-Za-z0-9\-]", "", dni_raw)
            
            # Limpiamos también el nombre para que coincida con la lógica del modelo
            name = re.sub(r"[^A-Z\s]", "", name.upper())

            # La lógica de no duplicados se maneja aquí:
            # get_or_create intenta obtener un cliente con ese DNI.
            # Si no existe, lo crea. Si ya existe, simplemente lo obtiene.
            # El booleano 'created' nos dice si se creó un nuevo registro.
            # Esto aprovecha la restricción 'unique=True' en tu modelo Client.
            client, created = Client.objects.get_or_create(
                dni=dni,
                defaults={'name': name}
            )

            if created:
                # Si se creó, significa que el DNI no existía.
                # El modelo ya se guardó con el nombre y DNI limpios gracias a tu método save().
                created_count += 1
                self.stdout.write(f' -> Creado: {client}')
            else:
                # Si no se creó, significa que el DNI ya existía.
                skipped_count += 1
                self.stdout.write(f' -> Omitido (DNI ya existe): {dni}')

        # 6. Mostrar resumen final
        self.stdout.write(self.style.SUCCESS('\n--- Proceso Finalizado ---'))
        self.stdout.write(self.style.SUCCESS(f'Clientes nuevos creados: {created_count}'))
        self.stdout.write(self.style.WARNING(f'Registros omitidos (duplicados o vacíos): {skipped_count}'))
        self.stdout.write(self.style.SUCCESS('¡Carga completada exitosamente!'))
