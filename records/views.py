import csv
from django.views.decorators.http import require_POST
from io import TextIOWrapper
from django.db.models import Q, Count, F
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
from django.db.models.deletion import ProtectedError
from datetime import datetime 
from django.core.exceptions import PermissionDenied
from .filters import FinancialRecordFilter, DuplicateRecordAttemptFilter, TransactionFilter, CreditFilter, ClientFilter
from django_filters.views import FilterView
from django.forms import inlineformset_factory
from .forms import FinancialRecordForm, FinancialRecordUpdateForm, CSVUploadForm, BankForm, UserUpdateForm, TransactionForm, FinancialRecordFormSet, SellerForm, OrigenTransaccionForm, TransactionTypeForm, ClientForm, CreditForm
from .models import FinancialRecord, Bank, DuplicateRecordAttempt, AccessRequest, Transaction, Seller, OrigenTransaccion, TransactionType, Client
from django.contrib.auth.views import LoginView
from django.contrib.auth.models import Group, User
from .decorators import group_required
from django.utils.decorators import method_decorator
from .services import CSVProcessor 
from django.template.loader import render_to_string
from .forms import AccessRequestApprovalForm 
from django.template.loader import render_to_string
from .utils import calculate_effective_date
from .forms import BulkClientUploadForm
from datetime import datetime
from django.utils import timezone
from django.db.models import Q



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

@method_decorator(group_required('Admin', 'Digitador',  ), name='dispatch')
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

@method_decorator(group_required('Admin' ), name='dispatch')
class FinancialRecordDetailView(LoginRequiredMixin, DetailView):
    model = FinancialRecord
    template_name = 'records/record_detail.html' # Usaremos este nuevo template
    context_object_name = 'record'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = f'Detalle del Recibo #{self.object.id}'
        
        # Obtenemos el historial de cambios para este recibo
        history = self.object.history.all()
        for h in history:
            if h.prev_record:
                h.delta = h.diff_against(h.prev_record)
        context['history'] = history
        return context


@method_decorator(group_required('Admin', 'Facturador', 'Validador'), name='dispatch')
class RecordUpdateView(LoginRequiredMixin, SuccessMessageMixin, UpdateView):
    model = FinancialRecord
    form_class = FinancialRecordUpdateForm
    template_name = 'records/records_form.html'
    success_url = reverse_lazy('record_list')
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['request'] = self.request
        return kwargs
    
    def  form_valid(self, form):
        if self.request.user.groups.filter(name='Facturador').exists():
            # Si el usuario es 'Facturador', se le asigna automáticamente como facturador
            # y el campo 'status' se establece en 'Facturado'.
            form.instance.facturador = self.request.user.username
            # form.instance.status = 'Facturado'
        
     
        return super().form_valid(form)
    

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

@method_decorator(group_required('Admin'), name='dispatch')
class RecordDeleteView(LoginRequiredMixin, UserPassesTestMixin, DeleteView):
    model = FinancialRecord
    template_name = 'records/record_confirm_delete.html'
    success_url = reverse_lazy('record_list')
    success_message = "¡Registro eliminado exitosamente!"

    def test_func(self):
        is_superuser = self.request.user.is_superuser
        if not is_superuser:
            print(f"Permission denied for user {self.request.user.username}: Not a superuser.")
        return is_superuser

    # Este método maneja las solicitudes DELETE (si el frontend las envía)
    def delete(self, request, *args, **kwargs):
        self.object = self.get_object()
        
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            try:
                if not self.test_func():
                    print(f"Permission denied during AJAX delete for user {request.user.username}.")
                    return JsonResponse({'success': False, 'message': 'No tienes permisos para realizar esta acción.'}, status=403)

                self.object.delete()
                print(f"Returning JSON success response for record {self.object.pk}")
                return JsonResponse({'success': True, 'message': self.success_message})
            except Exception as e:
                print(f"Error deleting record: {e}")
                return JsonResponse({'success': False, 'message': str(e)}, status=500)
        
        # Para solicitudes no-AJAX, procede con el comportamiento por defecto de DeleteView
        return super().delete(request, *args, **kwargs)

    # --- NUEVO MÉTODO POST PARA MANEJAR SOLICITUDES AJAX DESDE EL FRONTEND ---
    def post(self, request, *args, **kwargs):
        # Si la solicitud es AJAX, la manejamos de forma similar al método delete
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            self.object = self.get_object() # Obtener el objeto antes de la eliminación
            try:
                if not self.test_func(): # Reutilizar la verificación de permisos
                    print(f"Permission denied during AJAX POST delete for user {request.user.username}.")
                    return JsonResponse({'success': False, 'message': 'No tienes permisos para realizar esta acción.'}, status=403)

                self.object.delete() # Eliminar el objeto
                messages.success(request, self.success_message) # Añadir mensaje de éxito
                print(f"Returning JSON success response for record {self.object.pk} via POST.")
                return JsonResponse({'success': True, 'message': self.success_message})
            except Exception as e:
                print(f"Error deleting record via POST: {e}")
                return JsonResponse({'success': False, 'message': str(e)}, status=500)
        
        # Para solicitudes POST no-AJAX, o si no es AJAX, se usa el comportamiento por defecto de DeleteView
        # que eliminará el objeto y redirigirá a success_url.
        return super().post(request, *args, **kwargs)


@method_decorator(group_required('Admin', 'Digitador'), name='dispatch')
class CreditCreateView(LoginRequiredMixin, CreateView):
    model = FinancialRecord
    form_class = CreditForm
    template_name = 'records/credit_form.html'
    success_url = reverse_lazy('credit_list') # O a donde quieras redirigir

    def get_form_kwargs(self):
        """
        Pasa el objeto 'request' al formulario. Es crucial para que el formulario
        pueda acceder al usuario (self.request.user) al crear un DuplicateRecordAttempt.
        """
        kwargs = super().get_form_kwargs()
        kwargs['request'] = self.request
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Registrar Nuevo Abono'
        # Este flag se usará en la plantilla para mostrar el checkbox de confirmación
        context['show_confirm_duplicate'] = 'confirm_duplicate' in (self.request.POST or {})
        return context

    def form_valid(self, form):
        with transaction.atomic():
            # Asignamos el objeto a self.object para que la vista lo reconozca
            self.object = form.save(commit=False)
            credit = self.object # Podemos seguir usando 'credit' por legibilidad
            credit.uploaded_by = self.request.user
            # El estado ya se establece en el formulario, pero lo aseguramos aquí
            credit.payment_status = 'Pendiente' 
            credit.save()

            # Si el usuario confirmó un duplicado similar, creamos el registro de intento
            # que ya fue validado en el form.
            if form.cleaned_data.get('confirm_duplicate'):
                serializable_data = {k: str(v) for k, v in form.cleaned_data.items()}
                DuplicateRecordAttempt.objects.create(
                    user=self.request.user,
                    data=serializable_data,
                    attempt_type='SIMILAR',
                    is_resolved=True, # Lo marcamos como resuelto porque el usuario confirmó
                    resolved_by=self.request.user,
                    resolved_at=timezone.now()
                )

        messages.success(self.request, 'Abono registrado exitosamente. Queda pendiente de aprobación.')
        # Dejamos que la clase base maneje la redirección.
        # Llama a super().form_valid() que a su vez llama a get_success_url().
        return super().form_valid(form)

    def form_invalid(self, form):
        # Si el formulario es inválido específicamente por una advertencia de duplicado similar...
        if 'confirm_duplicate' in form.errors:
            # El mensaje de error ya viene formateado desde el formulario, así que lo usamos directamente.
            # El uso de safe es porque confiamos en el HTML generado en nuestro form.
            messages.warning(self.request, form.errors['confirm_duplicate'][0], extra_tags='safe')
            # Volvemos a renderizar el formulario, pero esta vez pasamos un flag
            # para que la plantilla sepa que debe mostrar el checkbox de confirmación.
            return self.render_to_response(self.get_context_data(form=form, show_confirm_duplicate=True))
        
        # Si hay errores que no son de campo (como el duplicado exacto)
        if form.non_field_errors():
            for error in form.non_field_errors():
                # Mostramos el error específico del formulario (que ya tiene formato HTML)
                messages.error(self.request, error, extra_tags='safe')
        else:
            # Mensaje genérico solo si no hay un error no-field más específico
            messages.error(self.request, 'Por favor, corrige los errores resaltados en el formulario.')
        
        return self.render_to_response(self.get_context_data(form=form))

@method_decorator(group_required('Admin', 'Digitador',  'Validador'), name='dispatch')
class CreditListView(LoginRequiredMixin, FilterView):
    model = FinancialRecord
    template_name = 'records/credit_list.html'
    context_object_name = 'credits'
    paginate_by = 50
    filterset_class = CreditFilter

    def get_queryset(self):
        """
        El queryset base sobre el cual se aplicarán los filtros.
        Obtenemos solo los abonos (registros sin transacción asociada).
        Modificado para incluir todos los FinancialRecords y optimizar la carga del cliente.
        """
        queryset = FinancialRecord.objects.all().order_by('-creado') # Eliminado el filtro transaction__isnull=True
        # Optimizar la carga de datos relacionados para evitar N+1 queries
        # Esto cargará el cliente directo y el cliente de la transacción en una sola consulta.
        return queryset.select_related('cliente', 'transaction__cliente', 'banco_llegada', 'uploaded_by')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Listado de Recibos'
        # FilterView añade el objeto 'filter' al contexto automáticamente.
        # Podemos usarlo para obtener la URL con los filtros actuales para la paginación.
        context['filter_params'] = self.request.GET.urlencode()
        return context
    

class CreditDetailView(LoginRequiredMixin, DetailView):
    model = FinancialRecord # Cambiado de Transaction a FinancialRecord
    template_name = 'records/credit_detail.html'
    context_object_name = 'credit' # Cambiado de 'transaction' a 'credit'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Historial de cambios para el FinancialRecord (abono)
        history = self.object.history.all()
        for h in history:
            if h.prev_record:
                h.delta = h.diff_against(h.prev_record)
        context['history'] = history
        
        # Añadir información del cliente al contexto si existe
        if self.object.cliente:
            context['client'] = self.object.cliente
        
        return context

@method_decorator(group_required('Admin'), name='dispatch')
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

@method_decorator(group_required('Admin'), name='dispatch')
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

@method_decorator(group_required('Admin'), name='dispatch')
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
            # Devolvemos tanto el HTML del formulario como la URL a la que debe apuntar.
            return JsonResponse({
                'html_form': html_form,
                'form_url': reverse_lazy('Client_delete', kwargs={'pk': self.object.pk})
            })
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
    
    
@method_decorator(group_required('Admin'), name='dispatch')
class ClientUpdateView(LoginRequiredMixin, UserPassesTestMixin, SuccessMessageMixin, UpdateView):
    model = Client
    form_class = ClientForm
    template_name = 'records/Client_form.html'
    success_url = reverse_lazy('Client_list')
    success_message = "¡Cliente actualizado exitosamente!"

    def test_func(self):
        return self.request.user.is_superuser

    def get(self, request, *args, **kwargs):
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            self.object = self.get_object()
            form = self.get_form()
            html_form = render_to_string('records/Client_form.html', {'form': form, 'title': 'Editar Cliente'}, request=request)
            return HttpResponse(html_form)
        
        self.template_name = 'records/Client_form_standalone.html'
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Editar Cliente'
        return context

    def form_valid(self, form):
        if self.request.headers.get('x-requested-with') == 'XMLHttpRequest':
            try:
                Client = form.save()
            except IntegrityError:
                return JsonResponse({'success': False, 'form_html': render_to_string('records/Client_form.html', {'form': form, 'title': self.get_context_data()['title']}, request=self.request)})
            return JsonResponse({'success': True, 'id': Client.id, 'name': Client.name, 'message': self.success_message})
        return super().form_valid(form)

    def form_invalid(self, form):
        if self.request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'form_html': render_to_string('records/Client_form.html', {'form': form, 'title': self.get_context_data()['title']}, request=self.request)})
        
        self.template_name = 'records/Client_form_standalone.html'
        return super().form_invalid(form)

@method_decorator(group_required('Admin'), name='dispatch')
class ClientDeleteView(LoginRequiredMixin, UserPassesTestMixin, DeleteView):
    model = Client
    template_name = 'records/Client_confirm_delete.html'
    success_url = reverse_lazy('Client_list')
    success_message = "¡Cliente eliminado exitosamente!"

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
            try:
                self.object.delete()
                messages.success(self.request, self.success_message)
                return JsonResponse({'success': True, 'message': self.success_message})
            except (IntegrityError, ProtectedError):
                # Este error ocurre si el cliente está asociado a transacciones (on_delete=PROTECT)
                error_message = f'No se puede eliminar el cliente "{self.object.name}" porque tiene transacciones asociadas.'
                return JsonResponse({'success': False, 'message': error_message}, status=400)
            except Exception as e:
                # Captura cualquier otro error inesperado
                return JsonResponse({'success': False, 'message': str(e)}, status=500)
        return super().post(request, *args, **kwargs)

@method_decorator(group_required('Admin'), name='dispatch')
class ClientListView(LoginRequiredMixin, UserPassesTestMixin, FilterView):
    model = Client
    template_name = 'records/Client_list.html'
    context_object_name = 'clients' # Cambiado a 'clients' para seguir convenciones
    filterset_class = ClientFilter
    paginate_by = 50 # Mostraremos 50 clientes por página

    def test_func(self):
        return self.request.user.is_superuser
    
    def get_queryset(self):
        # Ordenamos por nombre para una visualización consistente
        return super().get_queryset().order_by('name')
    

@user_passes_test(lambda u: u.is_superuser)
def bulk_client_upload(request):
    if request.method == 'POST':
        form = BulkClientUploadForm(request.POST, request.FILES)
        if form.is_valid():
            file = request.FILES['file']
            import pandas as pd

            try:
                # Reiniciar el puntero del archivo por si se leyó antes
                file.seek(0)
                df = pd.read_excel(file)
            except Exception:
                try:
                    # Si falla, intentar leer como CSV
                    file.seek(0)
                    df = pd.read_csv(file)
                except Exception as e:
                    messages.error(request, f"No se pudo leer el archivo. Asegúrate de que sea un Excel o CSV válido. Error: {e}")
                    return redirect('Client_list')

            # Validar que las columnas 'name' y 'dni' existan
            required_columns = ['name', 'dni']
            if not all(col in df.columns for col in required_columns):
                messages.error(request, "El archivo debe contener las columnas 'name' y 'dni'.")
                return redirect('Client_list')

            # Eliminar filas donde 'name' o 'dni' son nulos
            df.dropna(subset=['name', 'dni'], inplace=True)

            if df.empty:
                messages.warning(request, "El archivo no contiene registros válidos para procesar.")
                return redirect('Client_list')

            total_rows = len(df)
            messages.info(request, f"Archivo leído correctamente. Se procesarán {total_rows} registros.")

            # Iterar sobre las filas del DataFrame y crear los clientes
            created_count = 0
            duplicates_count = 0
            error_count = 0

            for index, row in df.iterrows():
                # Limpiar datos de espacios en blanco
                name = str(row['name']).strip()
                dni = str(row['dni']).strip()

                if not name or not dni:
                    error_count += 1
                    continue

                # Verificar si ya existe un cliente con el mismo DNI
                if Client.objects.filter(dni=dni).exists():
                    duplicates_count += 1
                else:
                    try:
                        Client.objects.create(name=name, dni=dni)
                        created_count += 1
                    except Exception as e:
                        messages.error(request, f"Error al crear el cliente {name} (DNI: {dni}): {e}")
                        error_count += 1
            
            # Construir mensaje final
            message = f"Proceso finalizado. Clientes nuevos: {created_count}. Duplicados omitidos: {duplicates_count}. Errores: {error_count}."
            messages.success(request, message)
            return redirect('Client_list')
    else:
        form = BulkClientUploadForm()

    return render(request, 'records/client_bulk_upload_page.html', {'form': form})



@method_decorator(group_required('Admin' ), name='dispatch')
class ClientCreateView(LoginRequiredMixin, CreateView):
    model = Client
    form_class = ClientForm
    template_name = 'records/Client_form.html'
    success_url = reverse_lazy('Client_list')

    def get(self, request, *args, **kwargs):
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            form = self.get_form()
            html_form = render_to_string('records/Client_form.html', {'form': form, 'title': 'Crear Nuevo Cliente'}, request=request)
            return HttpResponse(html_form)
        
        self.template_name = 'records/Client_form_standalone.html'
        return super().get(request, *args, **kwargs)

    def form_valid(self, form):
        if self.request.headers.get('x-requested-with') == 'XMLHttpRequest':
            try:
                Client = form.save()
            except IntegrityError:
                return JsonResponse({'success': False, 'form_html': render_to_string('records/Client_form.html', {'form': form, 'title': 'Crear Nuevo Cliente'}, request=self.request)})
            return JsonResponse({'success': True, 'id': Client.id, 'name': Client.name, 'message': '¡Cliente creado exitosamente!'})
        return super().form_valid(form)

    def form_invalid(self, form):
        if self.request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'form_html': render_to_string('records/Client_form.html', {'form': form, 'title': 'Crear Nuevo Cliente'}, request=self.request)})
        
        self.template_name = 'records/Client_form_standalone.html'
        return super().form_invalid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Crear Nuevo Cliente'
        return context
    
@method_decorator(group_required('Admin'), name='dispatch')
class OrigenTransaccionCreateView(LoginRequiredMixin, CreateView):
    model = OrigenTransaccion
    form_class = OrigenTransaccionForm
    template_name = 'records/origen_transaccion_form.html'
    success_url = reverse_lazy('origen_transaccion_list')

    def get(self, request, *args, **kwargs):
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            form = self.get_form()
            html_form = render_to_string('records/origen_transaccion_form.html', {'form': form, 'title': 'Crear Nuevo Origen de Transacción'}, request=request)
            return HttpResponse(html_form)
        
        self.template_name = 'records/origen_transaccion_form_standalone.html'
        return super().get(request, *args, **kwargs)

    def form_valid(self, form):
        if self.request.headers.get('x-requested-with') == 'XMLHttpRequest':
            origen_transaccion = form.save()
            return JsonResponse({'success': True, 'id': origen_transaccion.id, 'name': origen_transaccion.name, 'message': '¡Origen de Transacción creado exitosamente!'})
        return super().form_valid(form)

    def form_invalid(self, form):
        if self.request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'form_html': render_to_string('records/origen_transaccion_form.html', {'form': form, 'title': 'Crear Nuevo Origen de Transacción'}, request=self.request)})
        
        self.template_name = 'records/origen_transaccion_form_standalone.html'
        return super().form_invalid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Crear Nuevo Origen de Transacción'
        return context

@method_decorator(group_required('Admin'), name='dispatch')
class OrigenTransaccionUpdateView(LoginRequiredMixin, UserPassesTestMixin, SuccessMessageMixin, UpdateView):
    model = OrigenTransaccion
    form_class = OrigenTransaccionForm
    template_name = 'records/origen_transaccion_form.html'
    success_url = reverse_lazy('origen_transaccion_list')
    success_message = "¡Origen de Transacción actualizado exitosamente!"

    def test_func(self):
        return self.request.user.is_superuser

    def get(self, request, *args, **kwargs):
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            self.object = self.get_object()
            form = self.get_form()
            html_form = render_to_string('records/origen_transaccion_form.html', {'form': form, 'title': 'Editar Origen de Transacción'}, request=request)
            return HttpResponse(html_form)
        
        self.template_name = 'records/origen_transaccion_form_standalone.html'
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Editar Origen de Transacción'
        return context

    def form_valid(self, form):
        if self.request.headers.get('x-requested-with') == 'XMLHttpRequest':
            origen_transaccion = form.save()
            return JsonResponse({'success': True, 'id': origen_transaccion.id, 'name': origen_transaccion.name, 'message': self.success_message})
        return super().form_valid(form)

    def form_invalid(self, form):
        if self.request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'form_html': render_to_string('records/origen_transaccion_form.html', {'form': form, 'title': self.get_context_data()['title']}, request=self.request)})
        
        self.template_name = 'records/origen_transaccion_form_standalone.html'
        return super().form_invalid(form)

@method_decorator(group_required('Admin'), name='dispatch')
class OrigenTransaccionDeleteView(LoginRequiredMixin, UserPassesTestMixin, DeleteView):
    model = OrigenTransaccion
    template_name = 'records/origen_transaccion_confirm_delete.html'
    success_url = reverse_lazy('origen_transaccion_list')
    success_message = "¡Origen de Transacción eliminado exitosamente!"

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

class OrigenTransaccionListView(LoginRequiredMixin, UserPassesTestMixin, ListView):
    model = OrigenTransaccion
    template_name = 'records/origen_transaccion_list.html'
    context_object_name = 'origen_transacciones'

    def test_func(self):
        return self.request.user.is_superuser


@method_decorator(group_required('Admin'), name='dispatch')
class SellerCreateView(LoginRequiredMixin, CreateView):
    model = Seller
    form_class = SellerForm
    template_name = 'records/seller_form.html'
    success_url = reverse_lazy('seller_list')

    def get(self, request, *args, **kwargs):
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            form = self.get_form()
            html_form = render_to_string('records/seller_form.html', {'form': form, 'title': 'Crear Nuevo Vendedor'}, request=request)
            return HttpResponse(html_form)
        self.template_name = 'records/seller_form_standalone.html'
        return super().get(request, *args, **kwargs)

    def form_valid(self, form):
        if self.request.headers.get('x-requested-with') == 'XMLHttpRequest':
            vendedor = form.save()
            return JsonResponse({'success': True, 'id': vendedor.id, 'name': vendedor.name, 'message': '¡Vendedor creado exitosamente!'})
        return super().form_valid(form)

    def form_invalid(self, form):
        if self.request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'form_html': render_to_string('records/seller_form.html', {'form': form, 'title': 'Crear Nuevo Vendedor'}, request=self.request)})
        self.template_name = 'records/seller_form_standalone.html'
        return super().form_invalid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Crear Nuevo Vendedor'
        return context


@method_decorator(group_required('Admin'), name='dispatch')
class SellerUpdateView(LoginRequiredMixin, UserPassesTestMixin, SuccessMessageMixin, UpdateView):
    model = Seller
    form_class = SellerForm
    template_name = 'records/seller_form.html'
    success_url = reverse_lazy('seller_list')
    success_message = "¡Vendedor actualizado exitosamente!"

    def test_func(self):
        return self.request.user.is_superuser
    
    def get(self, request, *args, **kwargs):
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            self.object = self.get_object()
            form = self.get_form()
            html_form = render_to_string('records/seller_form.html', {'form': form, 'title': 'Editar Vendedor'}, request=request)
            return HttpResponse(html_form)
        
        self.template_name = 'records/seller_form_standalone.html'
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Editar Vendedor'
        return context

    def form_valid(self, form):
        if self.request.headers.get('x-requested-with') == 'XMLHttpRequest':
            vendedor = form.save()
            return JsonResponse({'success': True, 'id': vendedor.id, 'name': vendedor.name, 'message': self.success_message})
        return super().form_valid(form)

    def form_invalid(self, form):
        if self.request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'form_html': render_to_string('records/seller_form.html', {'form': form, 'title': self.get_context_data()['title']}, request=self.request)})
        
        self.template_name = 'records/seller_form_standalone.html'
        return super().form_invalid(form)

@method_decorator(group_required('Admin'), name='dispatch')
class SellerDeleteView(LoginRequiredMixin, UserPassesTestMixin, DeleteView):
    model = Seller
    template_name = 'records/seller_confirm_delete.html'
    success_url = reverse_lazy('seller_list')
    success_message = "¡Vendedor eliminado exitosamente!"

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

class SellerListView(LoginRequiredMixin, UserPassesTestMixin, ListView):
    model = Seller
    template_name = 'records/seller_list.html'
    context_object_name = 'Sellers'

    def test_func(self):
        return self.request.user.is_superuser


@method_decorator(group_required('Admin'), name='dispatch')
class TransactionTypeCreateView(LoginRequiredMixin, CreateView):
    model = TransactionType
    form_class = TransactionTypeForm
    template_name = 'records/TransactionType_form.html'
    success_url = reverse_lazy('TransactionType_list')

    def get(self, request, *args, **kwargs):
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            form = self.get_form()
            html_form = render_to_string('records/TransactionType_form.html', {'form': form, 'title': 'Crear Tipo de Transacción'}, request=request)
            return HttpResponse(html_form)
        self.template_name = 'records/TransactionType_form_standalone.html'
        return super().get(request, *args, **kwargs)

    def form_valid(self, form):
        if self.request.headers.get('x-requested-with') == 'XMLHttpRequest':
            vendedor = form.save()
            return JsonResponse({'success': True, 'id': vendedor.id, 'name': vendedor.name, 'message': '¡Tipo de Transacción creado exitosamente!'})
        return super().form_valid(form)

    def form_invalid(self, form):
        if self.request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'form_html': render_to_string('records/TransactionType_form.html', {'form': form, 'title': 'Crear Tipo de Transacción'}, request=self.request)})
        self.template_name = 'records/TransactionType_form_standalone.html'
        return super().form_invalid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Crear Tipo de Transacción'
        return context


# Vista para actualizar Vendedores
@method_decorator(group_required('Admin'), name='dispatch')
class TransactionTypeUpdateView(LoginRequiredMixin, UserPassesTestMixin, SuccessMessageMixin, UpdateView):
    model = TransactionType
    form_class = TransactionTypeForm
    template_name = 'records/TransactionType_form.html'
    success_url = reverse_lazy('TransactionType_list')
    success_message = "¡Tipo Transacción actualizado exitosamente!"

    def test_func(self):
        return self.request.user.is_superuser
    
    def get(self, request, *args, **kwargs):
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            self.object = self.get_object()
            form = self.get_form()
            html_form = render_to_string('records/TransactionType_form.html', {'form': form, 'title': 'Editar Tipo Transacción'}, request=request)
            return HttpResponse(html_form)
        
        self.template_name = 'records/TransactionType_form_standalone.html'
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Editar Tipo Transacción'
        return context

    def form_valid(self, form):
        if self.request.headers.get('x-requested-with') == 'XMLHttpRequest':
            vendedor = form.save()
            return JsonResponse({'success': True, 'id': vendedor.id, 'name': vendedor.name, 'message': self.success_message})
        return super().form_valid(form)

    def form_invalid(self, form):
        if self.request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'form_html': render_to_string('records/TransactionType_form.html', {'form': form, 'title': self.get_context_data()['title']}, request=self.request)})
        
        self.template_name = 'records/TransactionType_form_standalone.html'
        return super().form_invalid(form)

# Vista para eliminar Vendedores
@method_decorator(group_required('Admin'), name='dispatch')
class TransactionTypeDeleteView(LoginRequiredMixin, UserPassesTestMixin, DeleteView):
    model = TransactionType
    template_name = 'records/TransactionType_confirm_delete.html'
    success_url = reverse_lazy('TransactionType_list')
    success_message = "¡Tipo Transacción eliminado exitosamente!"

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

@method_decorator(group_required('Admin'), name='dispatch')
class TransactionTypeListView(LoginRequiredMixin, UserPassesTestMixin, ListView):
    model = TransactionType
    template_name = 'records/TransactionType_list.html'
    context_object_name = 'TransactionTypes'

    def test_func(self):
        return self.request.user.is_superuser



@method_decorator(group_required('Admin', 'Digitador', 'Facturador', 'Validador'), name='dispatch')
class TransactionListView(LoginRequiredMixin, FilterView):
    model = Transaction
    template_name = 'records/records_list.html'
    context_object_name = 'object_list'
    filterset_class = TransactionFilter
    paginate_by = 50

    def get_queryset(self):
        """
        Modifica el queryset para optimizar la vista por defecto.
        - Por defecto: Muestra solo transacciones 'Pendientes' O con recibos no aprobados.
        - Para Facturadores: Aplica la lógica de mostrar solo transacciones listas para facturar.
        """
        queryset = super().get_queryset()
        user = self.request.user

        # Lógica específica para el rol 'Facturador'
        if user.groups.filter(name='Facturador').exists() and not user.is_superuser:
            queryset = queryset.annotate(
                num_receipts=Count('receipts'),
                num_approved_receipts=Count('receipts', filter=Q(receipts__payment_status='Aprobado'))
            ).filter(num_receipts__gt=0, num_receipts=F('num_approved_receipts'))

        # Lógica de filtrado por defecto si no se están usando los filtros
        # `self.request.GET` contendrá los parámetros de filtro si el usuario los usa.
        elif not self.request.GET:
            queryset = queryset.filter(
                Q(status='Pendiente') | 
                Q(receipts__payment_status__in=['Pendiente', 'Rechazado'])
            ).distinct()

        # Devolvemos el queryset con optimización y orden
        return queryset.prefetch_related('receipts').order_by('-id')

@method_decorator(group_required('Admin'), name='dispatch')
class TransactionDetailView(LoginRequiredMixin, DetailView):
    model = Transaction
    template_name = 'records/transaction_detail.html'
    context_object_name = 'transaction'

    def get_queryset(self):
        """
        Optimiza la consulta para incluir los datos del cliente y vendedor.
        """
        return super().get_queryset().select_related('cliente', 'vendedor')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # History for the Transaction itself
        transaction_history = self.object.history.all()
        for h in transaction_history:
            if h.prev_record:
                h.delta = h.diff_against(h.prev_record)
        context['transaction_history'] = transaction_history

        # History for each associated FinancialRecord
        receipts_with_history = []
        for receipt in self.object.receipts.all():
            receipt_history = receipt.history.all()
            for h in receipt_history:
                if h.prev_record:
                    h.delta = h.diff_against(h.prev_record)
            receipts_with_history.append({
                'receipt': receipt,
                'history': receipt_history
            })
        context['receipts_with_history'] = receipts_with_history

        return context

FinancialRecordInlineFormSet = inlineformset_factory(
    Transaction,
    FinancialRecord,
    form=FinancialRecordForm, # Assuming FinancialRecordForm is suitable for editing
    extra=0, # Start with zero empty forms
    can_delete=True
)


class TransactionUpdateView(LoginRequiredMixin, SuccessMessageMixin, UpdateView):
    model = Transaction
    form_class = TransactionForm
    template_name = 'records/transaction_form.html'
    success_url = reverse_lazy('record_list')
    success_message = "¡Transacción actualizada exitosamente!"

    def get_queryset(self):
        """
        Optimiza la consulta para incluir los datos del cliente y vendedor.
        """
        return super().get_queryset().select_related('cliente', 'vendedor')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Editar Transacción'
        user_groups = list(self.request.user.groups.values_list('name', flat=True))
        context['user_groups'] = user_groups
        context['is_admin'] = self.request.user.is_superuser
        context['is_digitador'] = 'Digitador' in user_groups
        context['is_validador'] = 'Validador' in user_groups
        context['is_facturador'] = 'Facturador' in user_groups

        
        transaction = self.get_object()
        total_receipts_amount = sum(receipt.valor for receipt in transaction.receipts.all() if receipt.valor)
        
        expected_amount = transaction.expected_amount or 0
        difference = expected_amount - total_receipts_amount
        
        context['total_receipts_amount'] = total_receipts_amount
        context['difference'] = difference

        # Obtener abonos/créditos disponibles para este cliente
        available_credits = []
        if transaction.cliente:
            available_credits = FinancialRecord.objects.filter(
                cliente=transaction.cliente,
                payment_status='Aprobado',
                transaction__isnull=True
            )
        context['available_credits'] = available_credits


        if self.request.POST:
            context['formset'] = FinancialRecordInlineFormSet(self.request.POST, instance=self.object, form_kwargs={'request': self.request})
        else:
            context['formset'] = FinancialRecordInlineFormSet(instance=self.object, form_kwargs={'request': self.request})
        return context
    
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        context = self.get_context_data()
        formset = context['formset']
        is_facturador = self.request.user.groups.filter(name='Facturador').exists()
        is_superuser = self.request.user.is_superuser

        has_similar_duplicate_warning = any('confirm_duplicate' in fs_form.errors for fs_form in formset)

        if formset.is_valid():
            if has_similar_duplicate_warning:
                messages.warning(
                    self.request,
                    'Se detectaron posibles duplicados en los recibos. Por favor, revisa las advertencias.'
                )
                return self.render_to_response(
                    self.get_context_data(form=form, formset=formset, show_confirm_duplicate=True)
                )

            with transaction.atomic():
                self.object = form.save(commit=False)

                # 🔹 Asegurar que facturador siempre sea texto válido
                if not self.object.facturador:  
                    # Si el campo viene vacío, lo llenamos con el username del usuario actual
                    self.object.facturador = self.request.user.username
                elif hasattr(self.object.facturador, 'username'):
                    # Si por alguna razón facturador es un objeto User
                    self.object.facturador = self.object.facturador.username

                self.object.save()

                # 🔹 Desvincular recibos marcados
                credit_ids_to_unlink = self.request.POST.getlist('unlink_credit')
                if credit_ids_to_unlink:
                    # Filtramos solo los recibos que pertenecen a esta transacción
                    receipts_to_unlink = self.object.receipts.filter(pk__in=credit_ids_to_unlink)
                    for receipt in receipts_to_unlink:
                        receipt.cliente = self.object.cliente # ¡CLAVE! Asignamos el cliente de la transacción al recibo.
                        receipt.transaction = None # Rompemos el vínculo
                        receipt.save()

                # 🔹 Aplicar abonos seleccionados a esta transacción
                credit_ids_to_apply = self.request.POST.getlist('apply_credit')
                if credit_ids_to_apply:
                    credits = FinancialRecord.objects.filter(pk__in=credit_ids_to_apply)
                    for credit in credits:
                        # Doble chequeo para seguridad: el abono debe pertenecer al cliente y no tener transacción asignada
                        if credit.cliente == self.object.cliente and credit.transaction is None:
                            credit.transaction = self.object
                            credit.save()

                # 🔹 Solo guardamos formset si NO es facturador o si es superuser
                if not is_facturador or is_superuser:
                    formset.instance = self.object
                    
                    for receipt_form in formset:
                        if receipt_form.has_changed() and receipt_form.cleaned_data:
                            if receipt_form.cleaned_data.get('DELETE'):
                                if receipt_form.instance.pk:
                                    receipt_form.instance.delete()
                            else:
                                receipt = receipt_form.save(commit=False)
                                is_new = not receipt.pk
                                
                                if is_new:
                                    receipt.uploaded_by = self.request.user
                                
                                receipt.transaction = self.object
                                receipt.save()

                                if receipt_form.cleaned_data.get('confirm_duplicate') and is_new:
                                    serializable_data = {k: str(v) for k, v in receipt_form.cleaned_data.items()}
                                    DuplicateRecordAttempt.objects.create(
                                        user=self.request.user,
                                        data=serializable_data,
                                        attempt_type='SIMILAR',
                                        is_resolved=True,
                                        resolved_by=self.request.user,
                                        resolved_at=timezone.now()
                                    )

            messages.success(self.request, self.success_message)
            return redirect(self.get_success_url())

        else:
            messages.error(self.request, 'Por favor, corrija los errores en el formulario.')
            return self.render_to_response(self.get_context_data(form=form, formset=formset))

    
    def form_invalid(self, form):
        messages.error(self.request, 'Por favor, corrija los errores en el formulario de la transacción.')
        context = self.get_context_data(form=form)
        formset = context['formset']

        has_similar_duplicate_warning = False
        for fs_form in formset:
            if 'confirm_duplicate' in fs_form.errors:
                has_similar_duplicate_warning = True
                break
        
        if has_similar_duplicate_warning:
            messages.warning(self.request, 'Se detectaron posibles duplicados en los recibos. Por favor, revisa las advertencias y marca la casilla de confirmación si deseas guardar de todos modos.')
            context['show_confirm_duplicate'] = True

        return self.render_to_response(context)
    
@method_decorator(group_required('Admin'), name='dispatch')  
class TransactionDeleteView(LoginRequiredMixin, UserPassesTestMixin, DeleteView):
    model = Transaction
    template_name = 'records/transaction_confirm_delete.html'
    success_url = reverse_lazy('record_list')
    success_message = "¡Transacción eliminada exitosamente!"

    def test_func(self):
        return self.request.user.is_superuser

    def post(self, request, *args, **kwargs):
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            self.object = self.get_object()
            try:
                if not self.test_func():
                    return JsonResponse({'success': False, 'message': 'No tienes permisos para realizar esta acción.'}, status=403)
                self.object.delete()
                messages.success(request, self.success_message)
                return JsonResponse({'success': True, 'message': self.success_message})
            except Exception as e:
                return JsonResponse({'success': False, 'message': str(e)}, status=500)
        return super().post(request, *args, **kwargs)


@method_decorator(group_required('Admin'), name='dispatch')
class AccessRequestApprovalView(LoginRequiredMixin, UserPassesTestMixin, SuccessMessageMixin, UpdateView):
    model = AccessRequest
    form_class = AccessRequestApprovalForm
    template_name = 'records/access_request_approval_modal.html'
    success_url = reverse_lazy('access_request_list')
    success_message = "¡Solicitud de acceso procesada exitosamente!"

    def test_func(self):
        return self.request.user.is_superuser

    def get(self, request, *args, **kwargs):
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            self.object = self.get_object()
            form = self.get_form()
            context = {
                'form': form,
                'title': 'Gestionar Solicitud de Acceso',
                'access_request': self.object,
                'user_to_approve': self.object.user,
            }
            html_form = render_to_string(self.template_name, context, request=request)
            return HttpResponse(html_form)
        return super().get(request, *args, **kwargs)

    def form_valid(self, form):
        if self.request.headers.get('x-requested-with') == 'XMLHttpRequest':
            access_request = self.get_object()
            action = form.cleaned_data['approval_action']
            user_to_approve = access_request.user

            if action == 'approve':
                user_to_approve.is_active = True
                user_to_approve.save()
                
                # Assign groups
                selected_groups = form.cleaned_data['groups']
                user_to_approve.groups.set(selected_groups) # Clears existing and sets new
                
                access_request.approved = True
                access_request.delete() # Delete the request after approval
                messages.success(self.request, f'Solicitud de acceso de {user_to_approve.username} aprobada y grupos asignados.')
            elif action == 'deny':
                access_request.delete() # Delete the request if denied
                messages.info(self.request, f'Solicitud de acceso de {user_to_approve.username} denegada y eliminada.')
            
            return JsonResponse({'success': True, 'message': self.success_message})
        return super().form_valid(form)

    def form_invalid(self, form):
        if self.request.headers.get('x-requested-with') == 'XMLHttpRequest':
            context = {
                'form': form,
                'title': 'Gestionar Solicitud de Acceso',
                'access_request': self.get_object(),
                'user_to_approve': self.get_object().user,
            }
            html_form = render_to_string(self.template_name, context, request=self.request)
            return JsonResponse({'success': False, 'form_html': html_form})
        return super().form_invalid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Gestionar Solicitud de Acceso'
        context['access_request'] = self.get_object()
        context['user_to_approve'] = self.get_object().user
        return context

@method_decorator(group_required('Admin'), name='dispatch')
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

@method_decorator(group_required('Admin'), name='dispatch')
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
    if request.method == 'POST':
        history_record = get_object_or_404(FinancialRecord.history, history_id=history_id)
        
        if not request.user.is_superuser:
            message = 'No tienes permisos para restaurar registros.'
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'message': message}, status=403)
            messages.error(request, message)
            return redirect('historial_registro', pk=history_record.instance.pk)

        if not history_record.instance.transaction_id or not Transaction.objects.filter(pk=history_record.instance.transaction_id).exists():
            message = 'No se puede restaurar el recibo porque la transacción asociada ya no existe.'
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'message': message}, status=400)
            messages.error(request, message)
            return redirect('deleted_receipts_list')

        history_record.instance.save()
        message = f'Registro restaurado exitosamente a la versión del {history_record.history_date}.'
        
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'success': True, 'message': message})
        
        messages.success(request, message)
        return redirect('deleted_receipts_list')
    
    return redirect('deleted_receipts_list')

@login_required
def deleted_records_view(request):
    if not request.user.is_superuser:
        messages.error(request, 'No tienes permisos para ver esta página.')
        return redirect('record_list')
    
    # 1. Obtener todos los registros del historial marcados como eliminados ('-').
    all_deleted_records_qs = FinancialRecord.history.filter(history_type='-').order_by('-history_date')
    
    # 2. Obtener los IDs de los registros originales que fueron eliminados.
    # El campo 'id' en el modelo de historial corresponde al 'pk' del modelo original.
    deleted_record_ids = all_deleted_records_qs.values_list('id', flat=True)
    
    # 3. Identificar cuáles de esos IDs han sido restaurados (es decir, existen de nuevo en la tabla principal).
    restored_ids = FinancialRecord.objects.filter(pk__in=deleted_record_ids).values_list('pk', flat=True)
    
    # 4. Excluir los registros restaurados de la lista de eliminados.
    truly_deleted_records = all_deleted_records_qs.exclude(id__in=restored_ids)
    context = {
        'deleted_records': truly_deleted_records
    }
    return render(request, 'records/deleted_records_list.html', context)

@login_required
@user_passes_test(lambda u: u.is_superuser)
def deleted_transactions_view(request):
    # 1. Obtener todos los registros del historial de transacciones marcados como eliminados ('-').
    all_deleted_transactions_qs = Transaction.history.filter(history_type='-').order_by('-history_date')

    # 2. Obtener los IDs originales de las transacciones eliminadas.
    deleted_transaction_ids = all_deleted_transactions_qs.values_list('id', flat=True)

    # 3. Identificar cuáles de esos IDs han sido restaurados (existen de nuevo en la tabla principal).
    restored_ids = Transaction.objects.filter(pk__in=deleted_transaction_ids).values_list('pk', flat=True)

    # 4. Excluir las transacciones restauradas de la lista de eliminados.
    truly_deleted_transactions = all_deleted_transactions_qs.exclude(id__in=restored_ids)
    context = {
        'deleted_transactions': truly_deleted_transactions,
        'title': 'Transacciones Eliminadas'
    }
    return render(request, 'records/deleted_transactions_list.html', context)

@login_required
@user_passes_test(lambda u: u.is_superuser)
def restore_transaction_view(request, history_id):
    if request.method == 'POST':
        history_record = get_object_or_404(Transaction.history, history_id=history_id)
        
        history_record.instance.save()
        
        message = f'Transacción ID {history_record.instance.pk} restaurada exitosamente.'

        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'success': True, 'message': message})
        
        messages.success(request, message)
        return redirect('deleted_transactions_list')
    
    return redirect('deleted_transactions_list')

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
        'FECHA', 'HORA', '#COMPROBANTE', 'BANCO LLEGADA', 'ORIGEN TRANSACCION', 'VALOR', 'STATUS', '# DE FACTURA', 'FACTURADOR'
    ])

    for record in filterset.qs:
        writer.writerow([
            record.fecha.strftime('%d/%m/%Y'),
            record.hora.strftime('%H:%M:%S'),
            record.comprobante,
            record.banco_llegada.name,
            record.origen_transaccion.name if record.origen_transaccion else '',
            record.valor,
            record.status,
            record.numero_factura,
            record.facturador,
        ])

    return response

@login_required
@user_passes_test(lambda u: u.is_superuser)
def export_transactions_csv(request):
    """
    Exporta un archivo CSV detallado a nivel de recibo (FinancialRecord),
    incluyendo la información de la transacción padre.
    """
    if not request.user.is_superuser:
        messages.error(request, 'No tienes permisos para realizar esta acción.')
        return redirect('record_list')

    # 1. Filtrar las transacciones basado en los query params de la URL
    transaction_filter = TransactionFilter(request.GET, queryset=Transaction.objects.all())

    # 2. Obtener los IDs de las transacciones filtradas
    filtered_transaction_ids = transaction_filter.qs.values_list('id', flat=True)

    # 3. Obtener todos los recibos que pertenecen a esas transacciones.
    #    Usamos select_related para optimizar la consulta y evitar N+1 queries,
    #    cargando eficientemente los datos de modelos relacionados.
    receipts_queryset = FinancialRecord.objects.filter(
        transaction__id__in=filtered_transaction_ids
    ).select_related(
        'transaction', 
        'transaction__vendedor', 
        'banco_llegada', 
        'origen_transaccion',
        'uploaded_by',
        'transaction__created_by'
    ).order_by('-transaction__date', '-id')

    # 4. Preparar la respuesta HTTP que devolverá el archivo CSV
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="reporte_detallado_recibos.csv"'
    response.write(u'\ufeff'.encode('utf8')) # Añade BOM para compatibilidad con Excel

    writer = csv.writer(response, delimiter=';')
    
    # 5. Escribir la fila de encabezados en el CSV
    writer.writerow([
        # Campos de la Transacción
        'ID Transaccion',
        'Fecha Transaccion',
        'Cliente',
        'Vendedor',
        'Descripcion Transaccion',
        'Estado Transaccion',
        '# Factura',
        'Facturador',
        'Creado por',
        # Campos del Recibo (FinancialRecord)
        'ID Recibo',
        'Fecha Recibo',
        'Hora Recibo',
        '# Comprobante',
        'Banco Llegada',
        'Origen Transaccion',
        'Valor Recibo',
        'Estado Pago Recibo',
        'Subido por',
    ])

    # 6. Iterar sobre cada recibo y escribir sus datos en una fila del CSV
    for receipt in receipts_queryset:
        transaction = receipt.transaction
        writer.writerow([
            # Datos de la Transacción (se repiten para cada recibo)
            transaction.unique_transaction_id,
            transaction.date.strftime('%d/%m/%Y'),
            transaction.cliente,
            transaction.vendedor.name if transaction.vendedor else '',
            transaction.description,
            transaction.status,
            transaction.numero_factura,
            transaction.facturador,
            transaction.created_by.username if transaction.created_by else '',
            # Datos del Recibo
            receipt.id,
            receipt.fecha.strftime('%d/%m/%Y'),
            receipt.hora.strftime('%H:%M:%S'),
            receipt.comprobante,
            receipt.banco_llegada.name if receipt.banco_llegada else '',
            receipt.origen_transaccion.name if receipt.origen_transaccion else '',
            receipt.valor,
            receipt.payment_status,
            receipt.uploaded_by.username if receipt.uploaded_by else '',
        ])

    return response

@user_passes_test(lambda u: u.is_superuser)
def csv_upload_view(request):
    if request.method == 'POST':
        form = CSVUploadForm(request.POST, request.FILES)
        if form.is_valid():
            csv_file = form.cleaned_data['csv_file']
            if not csv_file.name.endswith('.csv'):
                messages.error(request, 'Error: Por favor, sube un archivo CSV válido.')
                return redirect('csv_upload')
            
            try:
                # Delegamos el procesamiento a la nueva clase
                processor = CSVProcessor(csv_file)
                result = processor.process()

                # Mostramos los mensajes al usuario basados en el resultado
                messages.success(request, 'Proceso de carga masiva finalizado.')
                for msg_type, text in result.get_messages():
                    getattr(messages, msg_type)(request, text)
                
                # DEBUG: Verificar el número total de registros financieros después de la carga
                total_records = FinancialRecord.objects.count()
                print(f"DEBUG: Total FinancialRecords in DB after upload: {total_records}")

            except Exception as e:
                # Capturamos cualquier error inesperado durante el procesamiento
                messages.error(request, f'Ocurrió un error inesperado: {e}')
                # Capturamos cualquier error inesperado durante el procesamiento
                messages.error(request, f'Ocurrió un error inesperado: {e}')
            
            return redirect('record_list')
    else:
        form = CSVUploadForm()  

    return render(request, 'records/csv_upload_form.html', {'form': form})

@method_decorator(group_required('Admin'), name='dispatch')
class DuplicateAttemptsListView(LoginRequiredMixin, UserPassesTestMixin, ListView):
    model = DuplicateRecordAttempt
    template_name = 'records/duplicate_attempts_list.html'
    context_object_name = 'attempts'
    paginate_by = 50

    def test_func(self):
        return self.request.user.is_superuser

    def get_queryset(self):
        return DuplicateRecordAttempt.objects.filter(is_resolved=False).order_by('-timestamp')

@method_decorator(group_required('Admin'), name='dispatch')
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


@method_decorator(group_required('Admin'), name='dispatch')
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

@login_required
@group_required('Admin', 'Digitador')
def create_bulk_receipts(request):
    form_kwargs = {'request': request}

    if request.method == 'POST':
        transaction_form = TransactionForm(request.POST)
        formset = FinancialRecordFormSet(request.POST, form_kwargs=form_kwargs)

        # Variable para rastrear si hay advertencias de duplicados similares
        has_similar_duplicate_warning = False
        for form in formset:
            if 'confirm_duplicate' in form.errors:
                has_similar_duplicate_warning = True
                break

        # Validar ambos formularios
        if transaction_form.is_valid() and formset.is_valid():
            # Si hay advertencias de duplicados similares Y el usuario NO ha marcado la casilla de confirmación
            if has_similar_duplicate_warning:
                messages.warning(request, 'Se detectaron posibles duplicados. Por favor, revisa las advertencias y marca la casilla de confirmación si deseas guardar de todos modos.')
                context = {
                    'transaction_form': transaction_form,
                    'formset': formset,
                    'title': 'Nuevo Registro',
                    'show_confirm_duplicate': True # Flag para mostrar el checkbox en la plantilla
                }
                return render(request, 'records/create_bulk_receipts.html', context)

            # Si no hay errores o si los duplicados similares fueron confirmados, proceder a guardar
            with transaction.atomic():
                new_transaction = Transaction(
                    date=transaction_form.cleaned_data['date'],
                    cliente=transaction_form.cleaned_data['cliente'],
                    vendedor=transaction_form.cleaned_data['vendedor'],
                    transaction_type=transaction_form.cleaned_data['transaction_type'],
                    expected_amount = transaction_form.cleaned_data['expected_amount'],
                    description=transaction_form.cleaned_data['description'],
                    status='Pendiente',
                    numero_factura=transaction_form.cleaned_data['numero_factura'],
                    facturador=transaction_form.cleaned_data['facturador'],
                    created_by=request.user
                )
                new_transaction.save()

                # 🔹 Aplicar abonos seleccionados a la nueva transacción
                credit_ids_to_apply = request.POST.getlist('apply_credit')
                if credit_ids_to_apply:
                    # Buscamos los abonos que pertenecen al cliente y no tienen transacción asignada
                    credits_to_apply = FinancialRecord.objects.filter(
                        pk__in=credit_ids_to_apply,
                        cliente=new_transaction.cliente,
                        transaction__isnull=True
                    )
                    credits_to_apply.update(transaction=new_transaction)

                for form in formset:
                    if form.has_changed() and form.cleaned_data:
                        if form.cleaned_data.get('DELETE'):
                            if form.instance.pk:
                                form.instance.delete()
                        else:
                            receipt = form.save(commit=False)
                            receipt.transaction = new_transaction
                            receipt.uploaded_by = request.user
                            receipt.save()

                            # Si un duplicado similar fue confirmado por el usuario, registrarlo como resuelto
                            if form.cleaned_data.get('confirm_duplicate'):
                                serializable_data = {k: str(v) for k, v in form.cleaned_data.items()}
                                DuplicateRecordAttempt.objects.create(
                                    user=request.user,
                                    data=serializable_data,
                                    attempt_type='SIMILAR',
                                    is_resolved=True, # Marcar como resuelto porque el usuario confirmó
                                    resolved_by=request.user,
                                    resolved_at=timezone.now()
                                )

            messages.success(request, 'Transacción y recibos guardados exitosamente.')
            return redirect('record_list')
        else:
            messages.error(request, 'Por favor, corrija los errores en el formulario.')
            print(f"DEBUG: Transaction Form Errors: {transaction_form.errors}")
            print(f"DEBUG: Formset Errors: {formset.errors}")
            for i, form in enumerate(formset):
                if form.errors:
                    print(f"DEBUG: Form {i} Errors: {form.errors}")

            context = {
                'transaction_form': transaction_form,
                'formset': formset,
                'title': 'Nuevo Registro'
            }
            return render(request, 'records/create_bulk_receipts.html', context)

    else: # GET request
        transaction_form = TransactionForm()
        formset = FinancialRecordFormSet(queryset=FinancialRecord.objects.none(), form_kwargs=form_kwargs)

    context = {
        'transaction_form': transaction_form,
        'formset': formset,
        'title': 'Nuevo Registro'
    }
    return render(request, 'records/create_bulk_receipts.html', context)

def download_csv_template(request):
    """
    Genera y descarga una plantilla CSV para la carga masiva de registros financieros.
    """
    response  = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="csv_template.csv"'

    writer = csv.writer(response, delimiter=';')
    writer.writerow([
        'FECHA', 'HORA', '#COMPROBANTE', 'BANCO LLEGADA', 'VALOR'
    ])

    return response 


def get_effective_date_view(request):
    origen_id = request.GET.get('origen_id')
    start_date_str = request.GET.get('start_date')

    if not origen_id or not start_date_str:
        return JsonResponse({'error': 'Faltan parámetros'}, status=400)

    try:
        origen = OrigenTransaccion.objects.get(pk=origen_id)
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()

        # Tu lógica: si dias_efectivo es mayor a 1
        if origen.dias_efectivo >= 1:
            dias_efectivo = origen.dias_efectivo
            effective_date = calculate_effective_date(start_date, dias_efectivo)

            # Formateamos la fecha para mostrarla como DD/MM/YYYY
            formatted_date = effective_date.strftime('%d/%m/%Y')

            message = (
                f"Esta transacción tomará {dias_efectivo} días hábiles en procesarse. "
                f"Fecha efectiva esperada: {formatted_date}."
            )
            return JsonResponse({'message': message})
        else:
            # Si no cumple la condición, no devolvemos ningún mensaje
            return JsonResponse({'message': ''})

    except OrigenTransaccion.DoesNotExist:
        return JsonResponse({'error': 'ID de Origen inválido'}, status=404)
    except (ValueError, TypeError):
        return JsonResponse({'error': 'Formato de fecha inválido'}, status=400)
    
@login_required
def get_available_credits(request):
    """
    Vista AJAX para obtener los abonos disponibles de un cliente.
    Devuelve un fragmento de HTML renderizado.
    """
    client_id = request.GET.get('client_id')
    credits = []
    if client_id:
        try:
            credits = FinancialRecord.objects.filter(
                cliente_id=client_id,
                payment_status='Aprobado',
                transaction__isnull=True
            )
        except (ValueError, TypeError):
            pass # Ignora si el client_id no es válido

    html = render_to_string('records/_available_credits_list.html', {'credits': credits}, request=request)
    return JsonResponse({'html': html})


@login_required
def get_client_balance(request):
    client_id = request.GET.get('client_id')
    if not client_id:
        return JsonResponse({'error': 'Client ID no proporcionado'}, status=400)
    
    try:
        client = Client.objects.get(pk=client_id)
        balance = client.available_balance
        return JsonResponse({'balance': f'{balance:,.2f}'}) # Formatted balance
    except Client.DoesNotExist:
        return JsonResponse({'error': 'Cliente no encontrado'}, status=404)
    


@login_required 
def search_clients(request):
    """
    Vista para buscar clientes vía AJAX para el autocompletado.
    Responde con una lista de objetos JSON.
    """
    # jQuery UI Autocomplete envía el término de búsqueda en el parámetro 'term'
    term = request.GET.get('term', '').strip()
    
    results = []
    if len(term) >= 2: # Empezar a buscar con al menos 2 caracteres
        clients = Client.objects.filter(
            Q(name__icontains=term) | Q(dni__icontains=term)
        ).order_by('name')[:10] # Limitar a 10 resultados para un buen rendimiento

        for client in clients:
            results.append({
                "id": client.id,
                # 'label' es lo que jQuery UI mostrará en la lista de sugerencias.
                # Usamos el __str__ del modelo que ya está bien formateado.
                "label": str(client), 
            })
            
    # safe=False es necesario para devolver una lista de objetos JSON.
    return JsonResponse(results, safe=False)

@login_required
def search_sellers(request):
    """
    Vista para buscar vendedores vía AJAX para el autocompletado.
    """
    term = request.GET.get('term', '').strip()
    results = []
    if len(term) >= 2:
        sellers = Seller.objects.filter(name__icontains=term).order_by('name')[:10]
        for seller in sellers:
            results.append({
                "id": seller.id,
                "label": seller.name,
            })
    return JsonResponse(results, safe=False)



@require_POST
@login_required
def update_credit_status(request, pk):
    """
    Vista para actualizar el estado de un abono (FinancialRecord) vía AJAX.
    Solo accesible por superusuarios y validadores.
    """
    # 1. Verificar permisos
    if not (request.user.is_superuser or request.user.groups.filter(name='Validador').exists()):
        return JsonResponse({'success': False, 'message': 'No tienes permiso para realizar esta acción.'}, status=403)

    # 2. Obtener el abono y el nuevo estado
    credit = get_object_or_404(FinancialRecord, pk=pk)
    new_status = request.POST.get('payment_status')
    
    # 3. Validar el nuevo estado
    valid_statuses = [choice[0] for choice in FinancialRecord.APROVED_CHOICES]
    if new_status not in valid_statuses:
        return JsonResponse({'success': False, 'message': 'Estado no válido.'}, status=400)

    # 4. Actualizar y guardar
    try:
        credit.payment_status = new_status
        credit.save()
        # Devolvemos el nuevo estado y un mensaje de éxito
        return JsonResponse({'success': True, 'new_status': credit.get_payment_status_display(), 'message': 'Estado actualizado correctamente.'})
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


@require_POST
@login_required
@group_required('Admin', 'Digitador')
def create_credit_note_from_surplus(request, pk):
    """
    Crea una nota de crédito a partir del excedente de una transacción.
    Implementa una lógica de doble entrada:
    1. Crea un `FinancialRecord` positivo (saldo a favor) sin transacción asignada.
    2. Crea un `FinancialRecord` negativo (ajuste) DENTRO de la transacción actual para balancearla.
    3. Vincula ambos registros para mantener la trazabilidad.
    """
    try:
        transaction_obj = get_object_or_404(Transaction, pk=pk)

        # 1. Calcular la diferencia y asegurarse de que haya un excedente.
        surplus = -transaction_obj.difference
        if surplus <= 0:
            messages.error(request, "No hay un excedente en esta transacción para generar una nota de crédito.")
            return redirect('transaction_update', pk=transaction_obj.pk)

        # 2. Iniciar una transacción atómica para garantizar la integridad.
        with transaction.atomic():
            # 2.1. Obtener o crear el Banco y Origen por defecto para las Notas de Crédito.
            # Esto evita el error "NOT NULL constraint failed".
            credit_note_bank, _ = Bank.objects.get_or_create(name="NOTA DE CREDITO")
            credit_note_origin, _ = OrigenTransaccion.objects.get_or_create(name="NOTA DE CREDITO")

            # 2.1. Crear el SALDO A FAVOR (positivo, sin transacción)
            # Este es el abono que el cliente podrá usar en el futuro.
            positive_credit = FinancialRecord.objects.create(
                cliente=transaction_obj.cliente,
                fecha=timezone.now().date(),
                hora=timezone.now().time(),
                banco_llegada=credit_note_bank,
                origen_transaccion=credit_note_origin,
                comprobante=f"NC-FAVOR-{transaction_obj.unique_transaction_id}",
                valor=surplus,
                payment_status='Aprobado',
                uploaded_by=request.user,
                transaction=None, # CLAVE: Esto lo convierte en un saldo a favor.
                description=f"Saldo a favor generado por excedente en transacción {transaction_obj.unique_transaction_id}."
            )

            # 2.2. Crear el AJUSTE (negativo, DENTRO de la transacción)
            # Esto balancea la transacción actual para que su diferencia sea cero.
            negative_adjustment = FinancialRecord.objects.create(
                cliente=transaction_obj.cliente,
                fecha=timezone.now().date(),
                hora=timezone.now().time(),
                banco_llegada=credit_note_bank,
                origen_transaccion=credit_note_origin,
                comprobante=f"NC-AJUSTE-{transaction_obj.unique_transaction_id}",
                valor=-surplus, # CLAVE: Valor negativo.
                payment_status='Aprobado',
                uploaded_by=request.user,
                transaction=transaction_obj, # CLAVE: Se asocia a la transacción actual.
                description=f"Ajuste para balancear excedente en transacción {transaction_obj.unique_transaction_id}."
            )

            # 2.3. Vincular ambos registros.
            positive_credit.linked_credit_note = negative_adjustment
            positive_credit.save()
            negative_adjustment.linked_credit_note = positive_credit
            negative_adjustment.save()

        messages.success(
            request, 
            f"Nota de crédito por valor de ${surplus:,.2f} generada exitosamente. La transacción ha sido balanceada."
        )
        return redirect('transaction_update', pk=transaction_obj.pk)

    except Transaction.DoesNotExist:
        messages.error(request, "La transacción no existe.")
        return redirect('record_list')
    except Exception as e:
        messages.error(request, f"Ocurrió un error inesperado: {e}")
        return redirect('transaction_update', pk=pk)


class FinancialRecordFormSet(inlineformset_factory(Transaction, FinancialRecord, form=FinancialRecordForm, extra=0, can_delete=True)):
    
    def clean(self):
        super().clean()
        for form in self.forms:
            if not form.is_valid():
                continue

            # Lógica para impedir la eliminación de una nota de crédito en uso.
            if form.cleaned_data.get('DELETE', False):
                instance = form.instance
                # Verificamos si es una nota de crédito de ajuste (valor negativo y vinculada)
                if instance.pk and instance.valor < 0 and instance.linked_credit_note:
                    # Verificamos si su contraparte positiva ya fue usada en otra transacción.
                    if instance.linked_credit_note.transaction is not None:
                        # Si ya fue usada, no se puede eliminar.
                        form.add_error(
                            None, # Error no asociado a un campo específico del formulario.
                            f"No se puede eliminar el ajuste '{instance.comprobante}' porque su nota de crédito correspondiente "
                            f"ya fue aplicada en la transacción {instance.linked_credit_note.transaction.unique_transaction_id}."
                        )
