import pandas as pd
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from records.models import FinancialRecord, Client, Bank, OrigenTransaccion
from django.contrib.auth.models import User
import os
from decimal import Decimal, InvalidOperation

class Command(BaseCommand):
    help = (
        'Carga recibos (abonos) desde un archivo CSV o Excel. '
        'El archivo debe tener las columnas: fecha, hora, comprobante, banco_llegada, '
        'valor, origen_transaccion, cliente_dni.'
    )

    def add_arguments(self, parser):
        parser.add_argument('file_path', type=str, help='La ruta completa al archivo a procesar.')
        parser.add_argument(
            '--user-id',
            type=int,
            help='El ID del usuario que figurará como "subido por". Si no se especifica, se dejará en blanco.'
        )

    @transaction.atomic
    def handle(self, *args, **options):
        file_path = options['file_path']
        user_id = options['user_id']
        
        # 1. Validar y obtener el usuario
        uploader = None
        if user_id:
            try:
                uploader = User.objects.get(pk=user_id)
                self.stdout.write(self.style.SUCCESS(f'Los recibos serán asignados al usuario: {uploader.username}'))
            except User.DoesNotExist:
                raise CommandError(f'El usuario con ID "{user_id}" no fue encontrado.')

        # 2. Validar que el archivo existe
        if not os.path.exists(file_path):
            raise CommandError(f'El archivo "{file_path}" no fue encontrado.')

        self.stdout.write(self.style.NOTICE(f'Iniciando la carga de recibos desde: {file_path}'))

        # 3. Leer el archivo con Pandas
        try:
            if file_path.endswith('.csv'):
                df = pd.read_csv(file_path, sep=';') # Asumimos punto y coma como separador
            elif file_path.endswith(('.xls', '.xlsx')):
                df = pd.read_excel(file_path)
            else:
                raise CommandError('Formato de archivo no soportado. Use .csv, .xls, o .xlsx')
        except Exception as e:
            raise CommandError(f'Error al leer el archivo: {e}')

        # 4. Validar columnas requeridas
        required_columns = ['fecha', 'hora', 'comprobante', 'banco_llegada', 'valor', 'origen_transaccion', 'cliente_dni']
        if not all(col in df.columns for col in required_columns):
            raise CommandError(f"El archivo debe contener las columnas: {', '.join(required_columns)}")

        # 5. Procesar los datos
        df.dropna(subset=required_columns, inplace=True)
        if df.empty:
            self.stdout.write(self.style.WARNING('El archivo no contiene registros válidos para procesar.'))
            return

        total_rows = len(df)
        created_count = 0
        skipped_count = 0
        error_count = 0
        
        self.stdout.write(f'Se encontraron {total_rows} registros en el archivo. Procesando...')

        # 6. Iterar y crear recibos
        for index, row in df.iterrows():
            try:
                # Limpieza y obtención de datos de la fila
                fecha = pd.to_datetime(row['fecha'], dayfirst=True).date()
                hora = pd.to_datetime(row['hora']).time()
                comprobante = str(row['comprobante']).strip()
                valor = Decimal(str(row['valor']).replace(',', '.'))
                cliente_dni = str(row['cliente_dni']).strip()
                banco_nombre = str(row['banco_llegada']).strip().upper()
                origen_nombre = str(row['origen_transaccion']).strip().upper()

                # Búsqueda de objetos relacionados
                cliente = Client.objects.get(dni=cliente_dni)
                banco = Bank.objects.get(name=banco_nombre)
                origen = OrigenTransaccion.objects.get(name=origen_nombre)

                # Lógica para evitar duplicados usando get_or_create
                # Esto aprovecha la restricción `unique_together` de tu modelo.
                record, created = FinancialRecord.objects.get_or_create(
                    fecha=fecha,
                    hora=hora,
                    comprobante=comprobante,
                    banco_llegada=banco,
                    valor=valor,
                    defaults={
                        'cliente': cliente,
                        'origen_transaccion': origen,
                        'payment_status': 'Pendiente',
                        'uploaded_by': uploader,
                        'description': 'Cargado masivamente desde archivo.'
                    }
                )

                if created:
                    created_count += 1
                    self.stdout.write(f' -> Creado: Recibo {comprobante} para cliente {cliente.dni}')
                else:
                    skipped_count += 1
                    self.stdout.write(self.style.WARNING(f' -> Omitido (ya existe): Recibo {comprobante}'))

            except Client.DoesNotExist:
                error_count += 1
                self.stdout.write(self.style.ERROR(f' -> Error en fila {index+2}: Cliente con DNI "{row["cliente_dni"]}" no encontrado.'))
            except Bank.DoesNotExist:
                error_count += 1
                self.stdout.write(self.style.ERROR(f' -> Error en fila {index+2}: Banco "{row["banco_llegada"]}" no encontrado.'))
            except OrigenTransaccion.DoesNotExist:
                error_count += 1
                self.stdout.write(self.style.ERROR(f' -> Error en fila {index+2}: Origen "{row["origen_transaccion"]}" no encontrado.'))
            except (InvalidOperation, ValueError) as e:
                error_count += 1
                self.stdout.write(self.style.ERROR(f' -> Error en fila {index+2}: Formato de dato inválido. ({e})'))
            except Exception as e:
                error_count += 1
                self.stdout.write(self.style.ERROR(f' -> Error inesperado en fila {index+2}: {e}'))

        # 7. Mostrar resumen final
        self.stdout.write(self.style.SUCCESS('\n--- Proceso Finalizado ---'))
        self.stdout.write(self.style.SUCCESS(f'Recibos nuevos creados: {created_count}'))
        self.stdout.write(self.style.WARNING(f'Recibos omitidos (duplicados): {skipped_count}'))
        self.stdout.write(self.style.ERROR(f'Filas con errores: {error_count}'))
        self.stdout.write(self.style.SUCCESS('¡Carga de recibos completada!'))

