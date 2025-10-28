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
from .filters import FinancialRecordFilter, DuplicateRecordAttemptFilter, TransactionFilter
from django_filters.views import FilterView
from django.forms import inlineformset_factory
from .forms import FinancialRecordForm, FinancialRecordUpdateForm, CSVUploadForm, BankForm, UserUpdateForm, TransactionForm, FinancialRecordFormSet, SellerForm, OrigenTransaccionForm
from .models import FinancialRecord, Bank, DuplicateRecordAttempt, AccessRequest, Transaction, Seller, OrigenTransaccion
from django.contrib.auth.views import LoginView
from django.contrib.auth.models import Group, User
from .decorators import group_required
from django.utils.decorators import method_decorator
from .services import CSVProcessor # Importar la nueva clase de servicio
from django.template.loader import render_to_string
from .forms import AccessRequestApprovalForm # New import


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




@method_decorator(group_required('Admin', 'Facturador'), name='dispatch')
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


# Vista para crear Vendedores (maneja modales AJAX)
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


# Vista para actualizar Vendedores
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
        context['title'] = 'Editar Vendor'
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

# Vista para eliminar Vendedores
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

@method_decorator(group_required('Admin', 'Digitador', 'Facturador'), name='dispatch')
class TransactionListView(LoginRequiredMixin, FilterView): # Changed to FilterView
    model = Transaction
    template_name = 'records/records_list.html'
    context_object_name = 'object_list'
    filterset_class = TransactionFilter # Added filterset_class
    paginate_by = 50

    def get_queryset(self):
        return super().get_queryset().prefetch_related('receipts').order_by('-id') # Use super().get_queryset() for filtering


class TransactionDetailView(LoginRequiredMixin, DetailView):
    model = Transaction
    template_name = 'records/transaction_detail.html'
    context_object_name = 'transaction'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        history = self.object.history.all()
        for h in history:
            if h.prev_record:
                h.delta = h.diff_against(h.prev_record)
        context['history'] = history
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

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Editar Transacción'
        context['is_facturador'] = self.request.user.groups.filter(name='facturador').exists()
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

        with transaction.atomic():
            self.object = form.save()

            if not is_facturador or is_superuser:
                if formset.is_valid():
                    formset.instance = self.object
                    formset.save()
                else:
                    return self.form_invalid(form)

        messages.success(self.request, self.success_message)
        return redirect(self.get_success_url())

    def form_invalid(self, form):
        messages.error(self.request, 'Por favor, corrija los errores en el formulario.')
        return self.render_to_response(self.get_context_data(form=form))

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
    if not request.user.is_superuser:
        messages.error(request, 'No tienes permisos para realizar esta acción.')
        return redirect('record_list')

    filterset = TransactionFilter(request.GET, queryset=Transaction.objects.all().order_by('-date'))

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="transactions.csv"'

    writer = csv.writer(response)
    writer.writerow([
        'FECHA', 'DESCRIPCION', 'CLIENTE', 'VALOR_TOTAL'
    ])

    for transaction_obj in filterset.qs:
        writer.writerow([
            transaction_obj.date.strftime('%d/%m/%Y'),
            transaction_obj.description,
            transaction_obj.cliente,
            transaction_obj.total_valor,
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

            except Exception as e:
                # Capturamos cualquier error inesperado durante el procesamiento
                messages.error(request, f'Ocurrió un error inesperado: {e}')
            
            return redirect('record_list')
    else:
        form = CSVUploadForm()

    return render(request, 'records/csv_upload_form.html', {'form': form})

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

@login_required
@group_required('Admin', 'Digitador')
def create_bulk_receipts(request):
    # The FinancialRecordForm needs the request object for its duplicate check logic.
    # We can pass it to the formset constructor with form_kwargs.
    form_kwargs = {'request': request}

    if request.method == 'POST':
        transaction_form = TransactionForm(request.POST)
        formset = FinancialRecordFormSet(request.POST, form_kwargs=form_kwargs)

        if transaction_form.is_valid() and formset.is_valid():
            # Use a database transaction to ensure all or nothing is saved.
            with transaction.atomic():
                # Crear la instancia de Transaction directamente desde los datos limpios del formulario
                new_transaction = Transaction(
                    date=transaction_form.cleaned_data['date'],
                    cliente=transaction_form.cleaned_data['cliente'],
                    vendedor=transaction_form.cleaned_data['vendedor'],
                    description=transaction_form.cleaned_data['description'],
                    status='Pendiente', # Siempre 'Pendiente' para nuevas transacciones
                    numero_factura=transaction_form.cleaned_data['numero_factura'],
                    facturador=transaction_form.cleaned_data['facturador'],
                    created_by=request.user # Asignar created_by explícitamente aquí
                )
                new_transaction.save() # Esto llamará al método save del modelo

                # Now, iterate through the forms in the formset.
                for form in formset:
                    # Check if the form has changed and has data
                    if form.has_changed() and form.cleaned_data:
                        # Check if the user marked this form for deletion
                        if form.cleaned_data.get('DELETE'):
                            # If the instance exists in the DB, delete it.
                            if form.instance.pk:
                                form.instance.delete()
                        else:
                            # This is a form with data to be saved.
                            receipt = form.save(commit=False)
                            receipt.transaction = new_transaction
                            receipt.uploaded_by = request.user
                            receipt.save()
            
            messages.success(request, 'Transacción y recibos guardados exitosamente.')
            return redirect('record_list') # Redirect to a relevant page
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

    writer = csv.writer(response)
    writer.writerow([
        'FECHA', 'HORA', '#COMPROBANTE', 'BANCO LLEGADA', 'VALOR'
    ])

    return response 