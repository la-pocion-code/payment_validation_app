import csv
from io import TextIOWrapper
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
from .forms import FinancialRecordForm, FinancialRecordUpdateForm, CSVUploadForm
from .models import FinancialRecord
from .filters import FinancialRecordFilter
# --- Vistas de Autenticación y Páginas Estáticas (pueden permanecer como funciones) ---

def login_view(request):
    return render(request, 'records/login.html')

def logout_view(request):
    logout(request)
    return redirect('login')

# --- Vistas Basadas en Clases para el CRUD de FinancialRecord ---

class RecordListView(LoginRequiredMixin, ListView):
    model = FinancialRecord
    template_name = 'records/records_list.html'
    context_object_name = 'records'
    ordering = ['-fecha', '-hora']

class RecordCreateView(LoginRequiredMixin, SuccessMessageMixin, CreateView):
    model = FinancialRecord
    form_class = FinancialRecordForm
    template_name = 'records/records_form.html'
    success_url = reverse_lazy('record_list')
    success_message = "¡Registro financiero guardado exitosamente!"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Crear Registro'
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

class FinancialRecordListView(FilterView):
    model = FinancialRecord
    template_name = 'records/lista_registros.html'
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
            reader = csv.reader(decoded_file, delimiter=';') # Asegúrate del delimitador

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

            # Usamos una transacción atómica para asegurar que si algo falla, no se guarde nada
            # o para guardar en bloques si preferimos no detener todo por un error.
            # Aquí, vamos a procesar y reportar errores, e intentar guardar los válidos.
            
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
                    

            # Ahora, intentar crear los registros que pasaron las validaciones iniciales
            # con ignore_conflicts=True para saltar duplicados a nivel de BD.
            # Esto es más eficiente que hacer un .save() por cada registro.
            if records_to_create:
                try:
                    # bulk_create no llama al método save() ni a save_m2m(),
                    # pero sí dispara IntegrityError si hay duplicados con unique_together
                    # a menos que usemos ignore_conflicts.
                    # Sin ignore_conflicts, un solo duplicado detendrá todo el bulk_create.
                    # Con ignore_conflicts, los duplicados simplemente no se insertan.
                    count_before = FinancialRecord.objects.count()
                    created_objects = FinancialRecord.objects.bulk_create(records_to_create, ignore_conflicts=True)
                    count_after = FinancialRecord.objects.count()
                    successfully_created = count_after - count_before
                    duplicates_count = len(records_to_create) - successfully_created

                except IntegrityError as e:
                    # Este bloque se alcanzaría si no usamos ignore_conflicts=True
                    # y un duplicado detiene todo el bulk_create.
                    # Con ignore_conflicts=True, este bloque no se ejecuta por duplicados.
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
            
            # Puedes redirigir a una página de resumen o a la lista de registros
            return redirect('record_list')
    else:
        form = CSVUploadForm()

    context = {'form': form}
    return render(request, 'records/csv_upload_form.html', context)
