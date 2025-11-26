import csv
from io import TextIOWrapper
from datetime import datetime
from django.db import transaction, IntegrityError
from .models import FinancialRecord, Bank, OrigenTransaccion, Client
from decimal import Decimal

class CSVProcessor:
    """
    Encapsula la lógica para procesar un archivo CSV de registros financieros.
    """
    def __init__(self, csv_file):
        self.csv_file = csv_file
        self.column_mapping = {
            'FECHA': 'fecha',
            'HORA': 'hora',
            '#COMPROBANTE': 'comprobante',
            'BANCO LLEGADA': 'banco_llegada',
            'VALOR': 'valor'
        }
        self.results = { # Corregido: self.results
            "processed": 0,
            "created": 0,
            "duplicates": 0,
            "line_errors": []
        }

        # Origen por defecto si la columna no existe
        self.default_origen, _ = OrigenTransaccion.objects.get_or_create(name="IMPORTADO MASIVO")

    def _get_reader(self):
        """Prepara y devuelve un lector de CSV."""
        # Lista de codificaciones a intentar
        encodings_to_try = ['utf-8-sig', 'latin-1', 'utf-8']
        
        for encoding in encodings_to_try:
            try:
                # Volvemos al inicio del archivo en cada intento
                self.csv_file.file.seek(0)
                decoded_file = TextIOWrapper(self.csv_file.file, encoding=encoding)
                
                # Intentamos detectar el dialecto (separador)
                try:
                    dialect = csv.Sniffer().sniff(decoded_file.read(1024))
                    decoded_file.seek(0)
                    return csv.reader(decoded_file, dialect)
                except csv.Error:
                    decoded_file.seek(0)
                    return csv.reader(decoded_file, delimiter=';') # Fallback a punto y coma
            except (UnicodeDecodeError, AttributeError):
                continue # Si falla la decodificación, prueba con la siguiente
        
        # Si ninguna codificación funcionó, lanzamos un error
        raise ValueError("No se pudo decodificar el archivo. Asegúrate de que esté guardado en formato UTF-8 o Latin-1.")

    def _validate_header(self, header):
        """Valida que el header del CSV contenga las columnas requeridas (excepto origen_transaccion)."""
        missing_columns = [col for col in self.column_mapping.keys() if col not in header]
        if missing_columns:
            raise ValueError(f'Faltan las siguientes columnas en el CSV: {", ".join(missing_columns)}')

    def _parse_row(self, row, header_map):
        """Parsea una fila del CSV y la convierte en un diccionario de datos."""
        row_data = {}
        for col_name, field_name in self.column_mapping.items():
            value = row[header_map[col_name]].strip()
            if field_name == 'fecha':
                row_data[field_name] = datetime.strptime(value, '%d/%m/%Y').date()
            elif field_name == 'hora':
                row_data[field_name] = datetime.strptime(value, '%H:%M:%S').time()
            elif field_name == 'valor':
                row_data[field_name] = float(value.replace(',', '.'))
            elif field_name == 'banco_llegada':
                bank, _ = Bank.objects.get_or_create(name=value.upper())
                row_data[field_name] = bank
            else:
                row_data[field_name] = value

        # Asignar el origen de transacción
        if 'ORIGEN TRANSACCION' in header_map:
            origen_valor = row[header_map['ORIGEN TRANSACCION']].strip()
            origen, _ = OrigenTransaccion.objects.get_or_create(name=origen_valor.upper())
            row_data['origen_transaccion'] = origen
        else:
            # Si la columna no existe, usar el valor por defecto
            row_data['origen_transaccion'] = self.default_origen


        # --- INICIO: Asignar estado de pago Aprobado ---
        row_data['payment_status'] = 'Aprobado'
        # --- FIN: Asignar estado de pago Aprobado ---
        return row_data

    def process(self):
        """Orquesta el proceso completo de lectura, validación e inserción."""
        reader = self._get_reader()
        header = next(reader, None)
        if not header:
            raise ValueError("El archivo CSV está vacío.")

        self._validate_header(header)
        header_map = {col: i for i, col in enumerate(header)}

        records_to_process = []
        for i, row in enumerate(reader, start=2):  # Empezar en 2 para contar la cabecera
            self.results['processed'] += 1
            if not row:
                continue
            try:
                row_data = self._parse_row(row, header_map)
                records_to_process.append(row_data)
            except (ValueError, IndexError, KeyError) as e:
                self.results['line_errors'].append(f"Línea {i}: {e}")

        if records_to_process:
            print(f"DEBUG: Intentando procesar {len(records_to_process)} registros.")
            
            # --- INICIO DE LA SOLUCIÓN ---
            # 1. Eliminar duplicados DENTRO del propio archivo CSV antes de comparar con la BD.
            unique_records_in_csv = {}
            for data in records_to_process:
                # Creamos una clave única para cada registro
                key = (
                    data['fecha'],
                    data['hora'],
                    data['comprobante'],
                    data['banco_llegada'].id,
                    Decimal(str(data['valor'])).quantize(Decimal('0.01'))
                )
                # Si la clave no está en el diccionario, la añadimos. Esto descarta duplicados.
                if key not in unique_records_in_csv:
                    unique_records_in_csv[key] = data
            
            # Ahora `records_to_process` solo contiene registros únicos del CSV.
            records_to_process = list(unique_records_in_csv.values())
            # --- FIN DE LA SOLUCIÓN ---

            try:
                with transaction.atomic():
                    # Consultar la base de datos para encontrar qué registros ya existen
                    existing_records = FinancialRecord.objects.filter(
                        fecha__in=[data['fecha'] for data in records_to_process],
                        comprobante__in=[data['comprobante'] for data in records_to_process]
                    ).values_list('fecha', 'hora', 'comprobante', 'banco_llegada_id', 'valor')

                    existing_record_keys = set()
                    for record in existing_records:
                        # Convertimos el valor de la BD a Decimal para una comparación precisa
                        key = (
                            record[0], # fecha (date)
                            record[1], # hora (time)
                            record[2], # comprobante (str)
                            record[3], # banco_llegada_id (int)
                            Decimal(record[4]).quantize(Decimal('0.01')) # valor (Decimal)
                        )
                        existing_record_keys.add(key)

                    # Filtrar los registros que no existen en la base de datos
                    records_to_create = []
                    for data in records_to_process:
                        key = (
                            data['fecha'],
                            data['hora'],
                            data['comprobante'],
                            data['banco_llegada'].id,
                            Decimal(str(data['valor'])).quantize(Decimal('0.01'))
                        )
                        if key not in existing_record_keys:
                            records_to_create.append(FinancialRecord(**data))

                    # Creación masiva de los nuevos registros
                    if records_to_create:
                        created_objects = FinancialRecord.objects.bulk_create(records_to_create)
                        self.results['created'] = len(created_objects)
                    else:
                        self.results['created'] = 0
                    
                    self.results['duplicates'] = len(records_to_process) - self.results['created']

                    print(f"DEBUG: Creados {self.results['created']} | Duplicados {self.results['duplicates']}")

            except Exception as e:
                raise Exception(f"Error durante la creación masiva de registros: {e}")
        
        return self

    def get_messages(self):
        """Genera una lista de mensajes para mostrar al usuario."""
        messages = []
        if self.results['processed'] == 0:
            messages.append(('warning', 'No se encontraron registros válidos para cargar en el archivo CSV.'))
            return messages

        messages.append(('info', f"Registros procesados: {self.results['processed']}"))
        messages.append(('info', f"Registros creados exitosamente: {self.results['created']}"))
        if self.results['duplicates'] > 0:
            messages.append(('info', f"Registros rechazados por duplicidad: {self.results['duplicates']}"))
        
        num_line_errors = len(self.results['line_errors'])
        if num_line_errors > 0:
            messages.append(('warning', f'{num_line_errors} registros tuvieron errores de formato o validación:'))
            for err in self.results['line_errors'][:10]:
                messages.append(('warning', err))
            if num_line_errors > 10:
                messages.append(('warning', f'... y {num_line_errors - 10} errores más.'))
        
        return messages
