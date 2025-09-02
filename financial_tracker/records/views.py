import csv
from io import TextIOWrapper
from django.http import HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth import logout
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.urls import reverse_lazy
from django.views.generic import ListView, CreateView, UpdateView, DeleteView, DetailView
from django.db import IntegrityError, transaction
from datetime import datetime
from .filters import FinancialRecordFilter
from django_filters.views import FilterView
from .forms import FinancialRecordForm, FinancialRecordUpdateForm, CSVUploadForm, BankForm
from .models import FinancialRecord, Bank, DuplicateRecordAttempt
from .filters import FinancialRecordFilter
# --- Vistas de Autenticación y Páginas Estáticas (pueden permanecer como funciones) ---

def login_view(request):
    return render(request, 'records/login.html')

def logout_view(request):
    logout(request)
    return redirect('login')

# --- Vistas Basadas en Clases para el CRUD de FinancialRecord ---



class RecordCreateView(LoginRequiredMixin, SuccessMessageMixin, CreateView):
    model = FinancialRecord
    form_class = FinancialRecordForm
    template_name = 'records/records_form.html'
    success_url = reverse_lazy('record_list')
    success_message = "¡Registro financiero guardado exitosamente!"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['request'] = self.request
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Crear Registro'
        context['vendedores'] = FinancialRecord.objects.values_list('vendedor', flat=True).distinct()
        context['clientes'] = FinancialRecord.objects.values_list('cliente', flat=True).distinct()
        return context

class RecordUpdateView(LoginRequiredMixin, SuccessMessageMixin, UpdateView):
    model = FinancialRecord
    form_class = FinancialRecordUpdateForm
    template_name = 'records/records_form.html'
    success_url = reverse_lazy('record_list')
    success_message = "¡Registro actualizado exitosamente!"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Editar Registro'
        context['vendedores'] = FinancialRecord.objects.values_list('vendedor', flat=True).distinct()
        context['clientes'] = FinancialRecord.objects.values_list('cliente', flat=True).distinct()
        # Pre-calculate history changes in the view
        history = self.object.history.all()
        for h in history:
            if h.prev_record:
                h.delta = h.diff_against(h.prev_record)
        context['history'] = history
        return context

class RecordDeleteView(LoginRequiredMixin, UserPassesTestMixin, DeleteView):
    model = FinancialRecord
    template_name = 'records/record_confirm_delete.html'
    success_url = reverse_lazy('record_list')
    success_message = "¡Registro eliminado exitosamente!"

    def test_func(self):
        return self.request.user.is_superuser

    def form_valid(self, form):
        messages.success(self.request, self.success_message)
        return super().form_valid(form)


class BankCreateView(LoginRequiredMixin, UserPassesTestMixin, CreateView):
    model = Bank
    form_class = BankForm
    template_name = 'records/bank_form.html'
    success_url = reverse_lazy('record_create')  # Redirect back to the record creation form

    def test_func(self):
        return self.request.user.is_superuser

class FinancialRecordListView(LoginRequiredMixin, FilterView):
    model = FinancialRecord
    template_name = 'records/records_list.html'
    filterset_class = FinancialRecordFilter
    paginate_by = 50

    def get_queryset(self):
        queryset = super().get_queryset()
        return queryset.order_by('-creado')

    def get_filterset_kwargs(self, filterset_class):
        kwargs = super().get_filterset_kwargs(filterset_class)
        if kwargs['data'] is None:
            kwargs['data'] = {'status': 'Pendiente'}
        return kwargs


# --- Vistas para Historial y Restauración (pueden permanecer como funciones) ---

@login_required
def history_record_view(request, pk):
    record = get_object_or_404(FinancialRecord, pk=pk)
    history = record.history.all()
    for h in history:
        if h.prev_record:
            h.delta = h.diff_against(h.prev_record)
    
    context = {
        'record': record,
        'history': history
    }
    return render(request, 'records/record_history.html', context)

@login_required
def restore_delete_record_view(request, history_id):
    history_record = get_object_or_404(FinancialRecord.history, history_id=history_id)
    if not request.user.is_superuser:
        messages.error(request, 'No tienes permisos para restaurar registros.')
        return redirect('historial_registro', pk=history_record.instance.pk)

    history_record.instance.save()
    messages.success(request, f'Registro restaurado exitosamente a la versión del {history_record.history_date}.')
    return redirect('historial_registro', pk=history_record.instance.pk)

@login_required
def deleted_records_view(request):
    if not request.user.is_superuser:
        messages.error(request, 'No tienes permisos para ver esta página.')
        return redirect('record_list')
    
    deleted_records = FinancialRecord.history.filter(history_type='-').order_by('-history_date')
    context = {
        'deleted_records': deleted_records
    }
    return render(request, 'records/deleted_records_list.html', context)

@login_required
def export_csv(request):
    if not request.user.is_superuser:
        messages.error(request, 'No tienes permisos para realizar esta acción.')
        return redirect('record_list')

    # Get the filterset with the query parameters
    filterset = FinancialRecordFilter(request.GET, queryset=FinancialRecord.objects.all().order_by('-creado'))

    # Create the HttpResponse object with the appropriate CSV header.
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="financial_records.csv"'

    writer = csv.writer(response)
    # Write the header row
    writer.writerow([
        'FECHA', 'HORA', '#COMPROBANTE', 'BANCO LLEGADA', 'VALOR', 'CLIENTE',
        'VENDEDOR', 'STATUS', '# DE FACTURA', 'FACTURADOR'
    ])

    # Write data rows
    for record in filterset.qs:
        writer.writerow([
            record.fecha.strftime('%d/%m/%Y'),
            record.hora.strftime('%H:%M:%S'),
            record.comprobante,
            record.banco_llegada.name,
            record.valor,
            record.cliente,
            record.vendedor,
            record.status,
            record.numero_factura,
            record.facturador,
        ])

    return response

# --- Vista de Carga CSV (se mantiene como función por su complejidad) ---

@login_required
def csv_upload_view(request):
    if not request.user.is_superuser:
        messages.error(request, 'No tienes permisos para cargar archivos.')
        return redirect('record_list')

    if request.method == 'POST':
        form = CSVUploadForm(request.POST, request.FILES)
        if form.is_valid():
            csv_file = form.cleaned_data['csv_file']

            if not csv_file.name.endswith('.csv'):
                messages.error(request, 'Error: Por favor, sube un archivo CSV válido.')
                return redirect('csv_upload')

            decoded_file = TextIOWrapper(csv_file.file, encoding='utf-8-sig')
            
            # Sniff the delimiter
            try:
                dialect = csv.Sniffer().sniff(decoded_file.read(1024))
                decoded_file.seek(0)
                reader = csv.reader(decoded_file, dialect)
            except csv.Error:
                # If sniffing fails, fallback to semicolon
                decoded_file.seek(0)
                reader = csv.reader(decoded_file, delimiter=';')


            header = next(reader, None) # Lee la primera fila como encabezado y lo salta

            if header is None:
                messages.error(request, 'El archivo CSV está vacío.')
                return redirect('csv_upload')
            
            # Mapeo de columnas a campos del modelo
            column_mapping = {
                'FECHA': 'fecha',
                'HORA': 'hora',
                '#COMPROBANTE': 'comprobante',
                'BANCO LLEGADA': 'banco_llegada',
                'VALOR': 'valor',
                'CLIENTE': 'cliente',
                'VENDEDOR': 'vendedor',
                'STATUS': 'status',
                '# DE FACTURA': 'numero_factura',
                'FACTURADOR': 'facturador',
            }

            # Validar que todas las columnas necesarias estén presentes
            missing_columns = [col for col in column_mapping.keys() if col not in header]
            if missing_columns:
                messages.error(request, f'Error: Faltan las siguientes columnas en el CSV: {", ".join(missing_columns)}. Asegúrate de que los nombres de las columnas coincidan exactamente.')
                return redirect('csv_upload')

            # Crear un diccionario para el acceso rápido a los índices de las columnas
            header_to_index = {col: index for index, col in enumerate(header)}

            records_to_create = []
            duplicates_count = 0
            successfully_created = 0
            line_errors = []
            processed_rows_count = 0

            with transaction.atomic():
                for i, row in enumerate(reader, start=2): # Empieza desde la línea 2 (después del encabezado)
                    processed_rows_count += 1
                    if not row:
                        continue # Salta filas vacías

                    row_data = {}
                    has_error_in_row = False

                    # Intenta mapear y convertir los datos de la fila
                    for col_name, field_name in column_mapping.items():
                        try:
                            value = row[header_to_index[col_name]].strip()
                            if field_name == 'fecha':
                                row_data[field_name] = datetime.strptime(value, '%d/%m/%Y').date()
                            elif field_name == 'hora':
                                row_data[field_name] = datetime.strptime(value, '%H:%M:%S').time()
                            elif field_name == 'valor':
                                row_data[field_name] = float(value.replace(',', '.')) # Para manejar comas como separador decimal
                            elif field_name == 'banco_llegada':
                                bank, created = Bank.objects.get_or_create(name=value.upper())
                                row_data[field_name] = bank
                            else:
                                row_data[field_name] = value
                        except (ValueError, IndexError) as e:
                            line_errors.append(f"Línea {i}: Error en la columna '{col_name}': {e}. Dato original: '{row[header_to_index.get(col_name, 'N/A')]}'")
                            has_error_in_row = True
                            break # No procesar más campos de esta fila si ya hay un error

                    if has_error_in_row:
                        continue # Pasa a la siguiente fila

                    # Crear una instancia del modelo y añadirla a la lista para creación masiva
                    record = FinancialRecord(**row_data)
                    records_to_create.append(record)
                    

            if records_to_create:
                try:
                    count_before = FinancialRecord.objects.count()
                    created_objects = FinancialRecord.objects.bulk_create(records_to_create, ignore_conflicts=True)
                    count_after = FinancialRecord.objects.count()
                    successfully_created = count_after - count_before
                    duplicates_count = len(records_to_create) - successfully_created

                except IntegrityError as e:
                    messages.error(request, f'Error masivo: Ocurrió un error de integridad de la base de datos al intentar cargar los registros. Puede haber duplicados que no fueron detectados previamente. Detalles: {e}')
                    return redirect('csv_upload')
                except Exception as e:
                    messages.error(request, f'Ocurrió un error inesperado al realizar la carga masiva: {e}')
                    return redirect('csv_upload')
            else:
                messages.warning(request, 'No se encontraron registros válidos para cargar en el archivo CSV.')


            # Reporte final
            messages.success(request, f'Proceso de carga masiva finalizado.')
            messages.info(request, f'Registros procesados: {processed_rows_count} (excluyendo encabezado).')
            messages.info(request, f'Registros creados exitosamente: {successfully_created}.')
            messages.info(request, f'Registros rechazados por duplicidad: {duplicates_count}.')
            if line_errors:
                messages.warning(request, f'{len(line_errors)} registros tuvieron errores de formato o validación:')
                for err in line_errors:
                    messages.warning(request, err)
            
            return redirect('record_list')
    else:
        form = CSVUploadForm()

    context = {'form': form}
    return render(request, 'records/csv_upload_form.html', context)

class DuplicateAttemptsListView(LoginRequiredMixin, UserPassesTestMixin, ListView):
    model = DuplicateRecordAttempt
    template_name = 'records/duplicate_attempts_list.html'
    context_object_name = 'attempts'
    paginate_by = 50

    def test_func(self):
        return self.request.user.is_superuser

    def get_queryset(self):
        return DuplicateRecordAttempt.objects.filter(is_resolved=False).order_by('-timestamp')

@login_required
def resolve_duplicate_attempt(request, pk):
    if not request.user.is_superuser:
        messages.error(request, 'No tienes permisos para realizar esta acción.')
        return redirect('record_list')
    
    attempt = get_object_or_404(DuplicateRecordAttempt, pk=pk)
    attempt.is_resolved = True
    attempt.save()
    messages.success(request, 'El intento de registro duplicado ha sido marcado como resuelto.')
    return redirect('duplicate_attempts_list')
