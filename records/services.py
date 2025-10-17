# records/services.py

import csv
from io import TextIOWrapper
from datetime import datetime
from django.db import transaction, IntegrityError
from .models import FinancialRecord, Bank

class CSVProcessor:
    """
    Encapsula la lógica para procesar un archivo CSV de registros financieros.
    """
    def __init__(self, csv_file):
        self.csv_file = csv_file
        self.column_mapping = {
            'FECHA': 'fecha', 'HORA': 'hora', '#COMPROBANTE': 'comprobante',
            'BANCO LLEGADA': 'banco_llegada', 'VALOR': 'valor',
        }
        self.results = {
            "processed": 0, "created": 0, "duplicates": 0,
            "line_errors": []
        }

    def _get_reader(self):
        """Prepara y devuelve un lector de CSV."""
        decoded_file = TextIOWrapper(self.csv_file.file, encoding='utf-8-sig')
        try:
            dialect = csv.Sniffer().sniff(decoded_file.read(1024))
            decoded_file.seek(0)
            return csv.reader(decoded_file, dialect)
        except csv.Error:
            decoded_file.seek(0)
            return csv.reader(decoded_file, delimiter=';')

    def _validate_header(self, header):
        """Valida que el header del CSV contenga las columnas requeridas."""
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
        return row_data

    def process(self):
        """
        Orquesta el proceso completo de lectura, validación e inserción.
        """
        reader = self._get_reader()
        header = next(reader, None)
        if not header:
            raise ValueError("El archivo CSV está vacío.")
        
        self._validate_header(header)
        header_map = {col: i for i, col in enumerate(header)}
        
        records_to_create = []
        for i, row in enumerate(reader, start=2): # Empezar en 2 para contar la cabecera
            self.results['processed'] += 1
            if not row:
                continue
            try:
                row_data = self._parse_row(row, header_map)
                records_to_create.append(FinancialRecord(**row_data))
            except (ValueError, IndexError) as e:
                original_value = row[header_map.get(e.args[0], 'N/A')] if isinstance(e, KeyError) else 'N/A'
                self.results['line_errors'].append(f"Línea {i}: {e}. Dato original: '{original_value}'")

        if records_to_create:
            try:
                with transaction.atomic():
                    # Usar ignore_conflicts para evitar fallos por duplicados
                    created_objects = FinancialRecord.objects.bulk_create(records_to_create, ignore_conflicts=True)
                    self.results['created'] = len(created_objects)
                    self.results['duplicates'] = len(records_to_create) - self.results['created']
            except IntegrityError as e:
                raise Exception(f"Error de integridad masivo: {e}")
        
        return self

    def get_messages(self):
        """Genera una lista de mensajes para mostrar al usuario."""
        messages = []
        if self.results['processed'] == 0:
            messages.append(('warning', 'No se encontraron registros válidos para cargar en el archivo CSV.'))
            return messages

        messages.append(('info', f"Registros procesados: {self.results['processed']}."))
        messages.append(('info', f"Registros creados exitosamente: {self.results['created']}."))
        if self.results['duplicates'] > 0:
            messages.append(('info', f"Registros rechazados por duplicidad: {self.results['duplicates']}."))
        
        num_line_errors = len(self.results['line_errors'])
        if num_line_errors > 0:
            messages.append(('warning', f'{num_line_errors} registros tuvieron errores de formato o validación:'))
            # Limitar la cantidad de errores mostrados para no saturar la UI
            for err in self.results['line_errors'][:10]:
                messages.append(('warning', err))
            if num_line_errors > 10:
                messages.append(('warning', f'... y {num_line_errors - 10} errores más.'))
        
        return messages