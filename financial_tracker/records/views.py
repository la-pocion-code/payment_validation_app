import csv
from io import TextIOWrapper
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth import logout
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.urls import reverse_lazy
from django.views.generic import ListView, CreateView, UpdateView, DeleteView, DetailView
from django.db import IntegrityError, transaction
from datetime import datetime
from django.core.exceptions import PermissionDenied
from .filters import FinancialRecordFilter, DuplicateRecordAttemptFilter
from django_filters.views import FilterView
from .forms import FinancialRecordForm, FinancialRecordUpdateForm, CSVUploadForm, BankForm, UserUpdateForm
from .models import FinancialRecord, Bank, DuplicateRecordAttempt, AccessRequest
from django.contrib.auth.views import LoginView
from django.contrib.auth.models import Group, User
from .decorators import group_required
from django.utils.decorators import method_decorator
from django.template.loader import render_to_string


class CustomLoginView(LoginView):
    template_name = 'records/login.html'

    def get_success_url(self):
        if not self.request.user.groups.exists() and not self.request.user.is_superuser:
            AccessRequest.objects.get_or_create(user=self.request.user)
            return reverse_lazy('request_access')
        return reverse_lazy('record_list')

def logout_view(request):
    logout(request)
    return redirect('login')

@login_required
def request_access(request):
    return render(request, 'records/request_access.html')

@user_passes_test(lambda u: u.is_superuser)
def access_request_list(request):
    requests = AccessRequest.objects.filter(approved=False) 
    users = User.objects.all()
    return render(request, 'records/access_request_list.html', {'requests': requests, 'users': users})

@user_passes_test(lambda u: u.is_superuser)
def approve_access_request(request, request_id):
    access_request = get_object_or_404(AccessRequest, id=request_id)
    access_request.approved = True
    access_request.save()
    
    group, created = Group.objects.get_or_create(name='Usuario')
    access_request.user.groups.add(group)
    
    access_request.user.is_active = True
    access_request.user.save()
    
    messages.success(request, f'Acceso aprobado para {access_request.user.username}.')
    return redirect('access_request_list')

@user_passes_test(lambda u: u.is_superuser)
def delete_access_request(request, request_id):
    access_request = get_object_or_404(AccessRequest, id=request_id)
    username = access_request.user.username

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        try:
            access_request.delete()
            return JsonResponse({'success': True, 'message': f'Solicitud de acceso para {username} eliminada exitosamente.'})
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)})
    
    access_request.delete()
    messages.success(request, f'Solicitud de acceso para {username} eliminada exitosamente.')
    return redirect('access_request_list')


@method_decorator(group_required('Admin', 'Usuario'), name='dispatch')
class RecordCreateView(LoginRequiredMixin, SuccessMessageMixin, CreateView):
    model = FinancialRecord
    form_class = FinancialRecordForm
    template_name = 'records/records_form.html'
    success_url = reverse_lazy('record_create')
    success_message = "¡Registro guardado exitosamente!"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['request'] = self.request
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Nuevo Registro'
        context['vendedores'] = FinancialRecord.objects.values_list('vendedor', flat=True).distinct()
        context['clientes'] = FinancialRecord.objects.values_list('cliente', flat=True).distinct()
        return context

@method_decorator(group_required('Admin', 'Usuario'), name='dispatch')
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

    def dispatch(self, request, *args, **kwargs):
        try:
            return super().dispatch(request, *args, **kwargs)
        except PermissionDenied:
            if request.headers.get('x-requested-with', '').startswith('XMLHttpRequest'):
                print(f"Permission denied during AJAX dispatch for user {request.user.username}.")
                return JsonResponse({'success': False, 'message': 'No tienes permisos para realizar esta acción.'}, status=403)
            raise # Re-raise for non-AJAX requests

    def test_func(self):
        is_superuser = self.request.user.is_superuser
        if not is_superuser:
            print(f"Permission denied for user {self.request.user.username}: Not a superuser.")
        return is_superuser

    def delete(self, request, *args, **kwargs):
        self.object = self.get_object()
        
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            try:
                if not self.test_func():
                    print(f"Permission denied during AJAX delete for user {self.request.user.username}.")
                    return JsonResponse({'success': False, 'message': 'No tienes permisos para realizar esta acción.'}, status=403)

                self.object.delete()
                print(f"Returning JSON success response for record {self.object.pk}")
                return JsonResponse({'success': True, 'message': self.success_message})
            except Exception as e:
                print(f"Error deleting record: {e}")
                return JsonResponse({'success': False, 'message': str(e)}, status=500)
        
        # For non-AJAX requests, proceed with default DeleteView behavior
        return super().delete(request, *args, **kwargs)


class BankCreateView(LoginRequiredMixin, CreateView):
    model = Bank
    form_class = BankForm
    template_name = 'records/bank_form.html'
    success_url = reverse_lazy('bank_list')

    def get(self, request, *args, **kwargs):
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            form = self.get_form()
            html_form = render_to_string('records/bank_form.html', {'form': form, 'title': 'Crear Nuevo Banco'}, request=request)
            return HttpResponse(html_form)
        
        self.template_name = 'records/bank_form_standalone.html'
        return super().get(request, *args, **kwargs)

    def form_valid(self, form):
        if self.request.headers.get('x-requested-with') == 'XMLHttpRequest':
            bank = form.save()
            return JsonResponse({'success': True, 'id': bank.id, 'name': bank.name, 'message': 'Banco creado exitosamente!'})
        return super().form_valid(form)

    def form_invalid(self, form):
        if self.request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'form_html': render_to_string('records/bank_form.html', {'form': form, 'title': 'Crear Nuevo Banco'}, request=self.request)})
        
        self.template_name = 'records/bank_form_standalone.html'
        return super().form_invalid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Crear Nuevo Banco'
        return context

class BankUpdateView(LoginRequiredMixin, UserPassesTestMixin, SuccessMessageMixin, UpdateView):
    model = Bank
    form_class = BankForm
    template_name = 'records/bank_form.html'
    success_url = reverse_lazy('bank_list')
    success_message = "¡Banco actualizado exitosamente!"

    def test_func(self):
        return self.request.user.is_superuser

    def get(self, request, *args, **kwargs):
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            self.object = self.get_object()
            form = self.get_form()
            html_form = render_to_string('records/bank_form.html', {'form': form, 'title': 'Editar Banco'}, request=request)
            return HttpResponse(html_form)
        
        self.template_name = 'records/bank_form_standalone.html'
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Editar Banco'
        return context

    def form_valid(self, form):
        if self.request.headers.get('x-requested-with') == 'XMLHttpRequest':
            bank = form.save()
            return JsonResponse({'success': True, 'id': bank.id, 'name': bank.name, 'message': self.success_message})
        return super().form_valid(form)

    def form_invalid(self, form):
        if self.request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'form_html': render_to_string('records/bank_form.html', {'form': form, 'title': self.get_context_data()['title']}, request=self.request)})
        
        self.template_name = 'records/bank_form_standalone.html'
        return super().form_invalid(form)

@method_decorator(group_required('Admin', 'Usuario'), name='dispatch')
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

class BankDeleteView(LoginRequiredMixin, UserPassesTestMixin, DeleteView):
    model = Bank
    template_name = 'records/bank_confirm_delete.html'
    success_url = reverse_lazy('bank_list')
    success_message = "¡Banco eliminado exitosamente!"

    def test_func(self):
        return self.request.user.is_superuser

    def get(self, request, *args, **kwargs):
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            self.object = self.get_object()
            context = self.get_context_data(object=self.object)
            html_form = render_to_string(self.template_name, context, request=request)
            return HttpResponse(html_form)
        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            self.object = self.get_object()
            self.object.delete()
            messages.success(self.request, self.success_message)
            return JsonResponse({'success': True, 'message': self.success_message})
        return super().post(request, *args, **kwargs)

class BankListView(LoginRequiredMixin, UserPassesTestMixin, ListView):
    model = Bank
    template_name = 'records/bank_list.html'
    context_object_name = 'banks'

    def test_func(self):
        return self.request.user.is_superuser


class UserUpdateView(LoginRequiredMixin, UserPassesTestMixin, SuccessMessageMixin, UpdateView):
    model = User
    form_class = UserUpdateForm
    template_name = 'records/user_form.html'
    success_url = reverse_lazy('access_request_list')
    success_message = "¡Usuario actualizado exitosamente!"

    def test_func(self):
        return self.request.user.is_superuser

    def get(self, request, *args, **kwargs):
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            self.object = self.get_object()
            form = self.get_form()
            html_form = render_to_string(self.template_name, {'form': form, 'title': 'Editar Usuario', 'user': self.object}, request=request)
            return HttpResponse(html_form)
        return super().get(request, *args, **kwargs)

    def form_valid(self, form):
        if self.request.headers.get('x-requested-with') == 'XMLHttpRequest':
            form.save()
            return JsonResponse({'success': True, 'message': self.success_message})
        return super().form_valid(form)

    def form_invalid(self, form):
        if self.request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'form_html': render_to_string(self.template_name, {'form': form, 'title': 'Editar Usuario', 'user': self.object}, request=self.request)})
        return super().form_invalid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Editar Usuario'
        return context

class UserDeleteView(LoginRequiredMixin, UserPassesTestMixin, DeleteView):
    model = User
    template_name = 'records/user_confirm_delete.html'
    success_url = reverse_lazy('access_request_list')
    success_message = "¡Usuario eliminado exitosamente!"

    def test_func(self):
        return self.request.user.is_superuser

    def get(self, request, *args, **kwargs):
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            self.object = self.get_object()
            context = self.get_context_data(object=self.object)
            html_form = render_to_string(self.template_name, context, request=request)
            return HttpResponse(html_form)
        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            self.object = self.get_object()
            self.object.delete()
            messages.success(self.request, self.success_message)
            return JsonResponse({'success': True, 'message': self.success_message})
        return super().post(request, *args, **kwargs)

def access_denied_view(request):
    return render(request, 'records/access_denied.html')

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

    filterset = FinancialRecordFilter(request.GET, queryset=FinancialRecord.objects.all().order_by('-creado'))

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="financial_records.csv"'

    writer = csv.writer(response)
    writer.writerow([
        'FECHA', 'HORA', '#COMPROBANTE', 'BANCO LLEGADA', 'VALOR', 'CLIENTE',
        'VENDEDOR', 'STATUS', '# DE FACTURA', 'FACTURADOR'
    ])

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
            
            try:
                dialect = csv.Sniffer().sniff(decoded_file.read(1024))
                decoded_file.seek(0)
                reader = csv.reader(decoded_file, dialect)
            except csv.Error:
                decoded_file.seek(0)
                reader = csv.reader(decoded_file, delimiter=';')


            header = next(reader, None)

            if header is None:
                messages.error(request, 'El archivo CSV está vacío.')
                return redirect('csv_upload')
            
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

            missing_columns = [col for col in column_mapping.keys() if col not in header]
            if missing_columns:
                messages.error(request, f'Error: Faltan las siguientes columnas en el CSV: {", ".join(missing_columns)}. Asegúrate de que los nombres de las columnas coincidan exactamente.')
                return redirect('csv_upload')

            header_to_index = {col: index for index, col in enumerate(header)}

            records_to_create = []
            duplicates_count = 0
            successfully_created = 0
            line_errors = []
            processed_rows_count = 0
            status_rejected_count = 0

            valid_statuses = [choice[0] for choice in FinancialRecord.STATUS_CHOICES]

            with transaction.atomic():
                for i, row in enumerate(reader, start=2):
                    processed_rows_count += 1
                    if not row:
                        continue

                    row_data = {}
                    has_error_in_row = False

                    for col_name, field_name in column_mapping.items():
                        try:
                            value = row[header_to_index[col_name]].strip()
                            if field_name == 'fecha':
                                row_data[field_name] = datetime.strptime(value, '%d/%m/%Y').date()
                            elif field_name == 'hora':
                                row_data[field_name] = datetime.strptime(value, '%H:%M:%S').time()
                            elif field_name == 'valor':
                                row_data[field_name] = float(value.replace(',', '.'))
                            elif field_name == 'banco_llegada':
                                bank, created = Bank.objects.get_or_create(name=value.upper())
                                row_data[field_name] = bank
                            elif field_name == 'status':
                                cleaned_status = value.strip().capitalize()
                                if cleaned_status not in valid_statuses:
                                    line_errors.append(f"Línea {i}: Estado '{value}' no válido. Debe ser uno de {valid_statuses}.")
                                    status_rejected_count += 1
                                    has_error_in_row = True
                                    break
                                row_data[field_name] = cleaned_status
                            elif field_name == 'cliente':
                                row_data[field_name] = value.strip().title()
                            else:
                                row_data[field_name] = value
                        except (ValueError, IndexError) as e:
                            line_errors.append(f"Línea {i}: Error en la columna '{col_name}': {e}. Dato original: '{row[header_to_index.get(col_name, 'N/A')]}'")
                            has_error_in_row = True
                            break

                    if has_error_in_row:
                        continue

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


            messages.success(request, f'Proceso de carga masiva finalizado.')
            messages.info(request, f'Registros procesados: {processed_rows_count} (excluyendo encabezado).')
            messages.info(request, f'Registros creados exitosamente: {successfully_created}.')
            messages.info(request, f'Registros rechazados por duplicidad: {duplicates_count}.')
            if status_rejected_count > 0:
                messages.warning(request, f'Registros rechazados por formato de estado no válido: {status_rejected_count}.')
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
    attempt.resolved_by = request.user
    attempt.resolved_at = datetime.now()
    attempt.save()
    messages.success(request, 'El intento de registro duplicado ha sido marcado como resuelto.')
    return redirect('duplicate_attempts_list')


class DuplicateAttemptsHistoryListView(LoginRequiredMixin, UserPassesTestMixin, FilterView):
    model = DuplicateRecordAttempt
    template_name = 'records/duplicate_attempts_history_list.html'
    context_object_name = 'attempts'
    filterset_class = DuplicateRecordAttemptFilter
    paginate_by = 50

    def test_func(self):
        return self.request.user.is_superuser

    def get_queryset(self):
        return DuplicateRecordAttempt.objects.all().order_by('-timestamp')


@login_required
def export_duplicate_attempts_csv(request):
    if not request.user.is_superuser:
        messages.error(request, 'No tienes permisos para realizar esta acción.')
        return redirect('duplicate_attempts_history_list')

    filterset = DuplicateRecordAttemptFilter(request.GET, queryset=DuplicateRecordAttempt.objects.all().order_by('-timestamp'))

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="duplicate_attempts.csv"'

    writer = csv.writer(response)
    writer.writerow([
        'Timestamp', 'User', 'Data', 'Resolved By', 'Resolved At'
    ])

    for attempt in filterset.qs:
        resolved_by_username = attempt.resolved_by.username if attempt.resolved_by else 'N/A'
        resolved_at_timestamp = attempt.resolved_at.strftime('%Y-%m-%d %H:%M:%S') if attempt.resolved_at else 'N/A'
        writer.writerow([
            attempt.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
            attempt.user.username,
            str(attempt.data),
            resolved_by_username,
            resolved_at_timestamp
        ])

    return response
