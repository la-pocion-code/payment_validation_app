# records/forms.py

from django import forms
from django.forms import modelformset_factory, BaseModelFormSet
from .models import FinancialRecord, Bank, DuplicateRecordAttempt, AccessRequest, Transaction, Seller, OrigenTransaccion
import json
from django.contrib.auth.models import User, Group
from django.contrib.auth.forms import UserChangeForm
from django.utils.html import format_html
from django.utils import timezone

class AccessRequestApprovalForm(forms.ModelForm):
    ACTION_CHOICES = [
        ('approve', 'Aprobar'),
        ('deny', 'Denegar'),
    ]
    approval_action = forms.ChoiceField(choices=ACTION_CHOICES, widget=forms.RadioSelect, initial='approve', label="Acción")
    groups = forms.ModelMultipleChoiceField(
        queryset=Group.objects.all(),
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label="Asignar Grupos (si se aprueba)"
    )

    class Meta:
        model = AccessRequest
        fields = [] # No direct fields from AccessRequest model, handled by action field

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.user:
            # Pre-populate groups if the user already belongs to some
            self.fields['groups'].initial = self.instance.user.groups.all()

    def clean(self):
        cleaned_data = super().clean()
        action = cleaned_data.get('approval_action')
        groups = cleaned_data.get('groups')

        if action == 'approve' and (not groups or groups.count() == 0):
            raise forms.ValidationError("Debe seleccionar al menos un grupo si aprueba la solicitud.")

        return cleaned_data


class FinancialRecordForm(forms.ModelForm):
    # Campo para confirmar duplicados
    confirm_duplicate = forms.BooleanField(
        required=False,
        widget=forms.HiddenInput(), # Inicialmente oculto
        label="Entiendo que este registro es similar a uno existente y deseo guardarlo de todos modos."
    )

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request', None)
        super(FinancialRecordForm, self).__init__(*args, **kwargs)
        self.similar_records = None


        # --- INICIO DE LA LÓGICA DE ROLES ---
        user = self.request.user if self.request else None

        # Aplicar restricciones solo si estamos editando un registro existente y el usuario no es superusuario
        if user and self.instance.pk and not user.is_superuser:
            # Por defecto, deshabilitar todos los campos
            for field in self.fields.values():
                field.disabled = True

            # Habilitar campos específicos según el grupo del usuario
            if user.groups.filter(name='Validador').exists():
                # Si es Validador, solo puede editar el estado de pago
                self.fields['payment_status'].disabled = False
  

        # Lógica original del formulario para valores por defecto y campos ocultos
        self.fields['payment_status'].required = False
        if not self.instance.pk:
            self.fields['payment_status'].initial = 'Pendiente'
            self.fields['payment_status'].widget = forms.HiddenInput()

        # Atributo para la validación de duplicados
        self.existing_record = None

    class Meta:
        model = FinancialRecord
        fields = ['origen_transaccion', 'fecha', 'hora', 'comprobante', 'banco_llegada',  'valor', 'payment_status']
        widgets = {
            'fecha': forms.DateInput(attrs={'type': 'date'}),
            'hora': forms.TimeInput(attrs={'type': 'time', 'step': '1'}),
            'valor': forms.TextInput(),
        }

    def clean(self):
        cleaned_data = super().clean()
        comprobante = cleaned_data.get('comprobante')
        if comprobante:
            cleaned_data['comprobante'] = comprobante.strip()

        fecha = cleaned_data.get('fecha')
        hora = cleaned_data.get('hora')
        banco_llegada = cleaned_data.get('banco_llegada')
        valor = cleaned_data.get('valor')

        # Obtener el valor de confirm_duplicate
        confirm_duplicate = cleaned_data.get('confirm_duplicate')

        # Solo realizamos estas verificaciones para nuevos registros
        if not self.instance.pk:
            # --- Verificación de Duplicados ---

            # 1. Verificación de duplicado EXACTO
            if fecha and hora and comprobante and banco_llegada and valor:
                exact_qs = FinancialRecord.objects.filter(
                    fecha=fecha,
                    hora=hora,
                    comprobante=comprobante,
                    banco_llegada=banco_llegada,
                    valor=valor
                )
                if exact_qs.exists():
                    if self.request:
                        serializable_data = {k: str(v) for k, v in cleaned_data.items()}
                        DuplicateRecordAttempt.objects.create(
                            user=self.request.user,
                            data=serializable_data,
                            attempt_type='DUPLICATE'
                        )
                    raise forms.ValidationError(
                        format_html('<div id="exact-duplicate-error">Registro duplicado exacto: ya existe un registro con los mismos datos (Fecha: {}, Hora: {}, Comprobante: {}, Banco: {}, Valor: {}).</div>', fecha, hora, comprobante, banco_llegada.name, valor)
                    )

            # 2. Verificación de registro SIMILAR (más específica)
            if fecha and hora and banco_llegada and valor:
                similar_qs = FinancialRecord.objects.filter(
                    fecha=fecha,
                    hora=hora,
                    banco_llegada=banco_llegada,
                    valor=valor
                )
                
                # Excluimos el duplicado exacto si el comprobante también está presente.
                if comprobante:
                    similar_qs = similar_qs.exclude(comprobante=comprobante)

                if similar_qs.exists() and not confirm_duplicate:
                    self.add_error(
                        'confirm_duplicate', # Adjuntar el error al nuevo campo
                        format_html('<div id=\"similar-duplicate-warning\">ADVERTENCIA: Posible registro duplicado. Ya existe un registro con la misma Fecha, Hora, Banco y Valor. Si estás seguro de que no es un duplicado, marca la casilla de confirmación.</div>')
                    )
                    # Almacenar los registros similares para mostrarlos en la plantilla
                    self.similar_records = similar_qs

                    # if self.request:
                    #     serializable_data = {k: str(v) for k, v in cleaned_data.items()}
                    #     DuplicateRecordAttempt.objects.create(
                    #         user=self.request.user,
                    #         data=serializable_data,
                    #         attempt_type='SIMILAR'
                    #     )
                    # raise forms.ValidationError(
                    #     format_html('<div id="similar-duplicate-error">Posible registro duplicado: ya existe un registro con la misma Fecha, Hora, Banco y Valor. Por favor, revisa los registros existentes.</div>')
                    # )

        # Para nuevos registros, si payment_status no se envía, establece el valor por defecto.
        if not self.instance.pk and not cleaned_data.get('payment_status'):
            cleaned_data['payment_status'] = 'Pendiente'

        return cleaned_data



class FinancialRecordUpdateForm(FinancialRecordForm):
    class Meta(FinancialRecordForm.Meta):
        exclude = ['uploaded_by']

    
class BankForm(forms.ModelForm):
    class Meta:
        model = Bank
        fields = ['name']

class OrigenTransaccionForm(forms.ModelForm):
    class Meta:
        model = OrigenTransaccion
        fields = ['name', 'dias_efectivo']


class CSVUploadForm(forms.Form):
    csv_file = forms.FileField(label="Seleccionar archivo CSV", max_length=5 * 1024 * 1024) # Added max_length for file size limit

class UserUpdateForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['is_active', 'is_superuser', 'groups']
        widgets = {
            'groups': forms.CheckboxSelectMultiple
        }

# --- New Forms for Bulk Receipt Creation ---

class BaseFinancialRecordFormSet(BaseModelFormSet):
    def clean(self):
        if any(self.errors):
            return
        
        receipts = []
        for form in self.forms:
            if form.cleaned_data and not form.cleaned_data.get('DELETE'):
                receipts_identifier = (
                    form.cleaned_data.get('fecha'),
                    form.cleaned_data.get('hora'),
                    form.cleaned_data.get('comprobante'),
                    form.cleaned_data.get('banco_llegada'),
                    form.cleaned_data.get('valor')
                )
                print(f"DEBUG: Formset clean - receipts_identifier: {receipts_identifier}")
                print(f"DEBUG: Formset clean - current receipts list: {receipts}")
                if receipts_identifier in receipts:
                    print(f"DEBUG: Formset clean - DUPLICATE DETECTED: {receipts_identifier}")
                    form.add_error(None, "Hay registros duplicados en el conjunto de formularios.")
                receipts.append(receipts_identifier)

                
class TransactionForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        user = kwargs.get('user', None) # Get user, but don't pop yet
        
        # Create a new kwargs dictionary for super().__init__
        # This ensures 'user' is not passed to the parent constructor
        super_kwargs = {k: v for k, v in kwargs.items() if k != 'user'}
        
        super().__init__(*args, **super_kwargs)

        # Inicializa y oculta campos
        if not self.instance.pk:
            self.fields['status'].initial = 'Pendiente'
            self.fields['status'].widget = forms.HiddenInput()
            self.fields['date'].initial = timezone.now().date()
            self.fields['created_by'].widget = forms.HiddenInput()

        if user and not user.is_superuser:
            if user.groups.filter(name='Facturador').exists():
                allowed_fields = ['description', 'status', 'numero_factura']
                for field_name, field in self.fields.items():
                    if field_name not in allowed_fields:
                        field.disabled = True
            else:
                for field in self.fields.values():
                    field.disabled = True

        if self.instance.pk:  # If it's an existing instance (update)
            del self.fields['expected_amount']

    class Meta:
        model = Transaction
        fields = ['date', 'cliente', 'vendedor','description', 'status', 'numero_factura', 'facturador', 'created_by', 'expected_amount']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date', 'id': 'id_transaction_date', 'class': 'form-control'}),
            'expected_amount': forms.TextInput(),
        }


FinancialRecordFormSet = modelformset_factory(
    FinancialRecord,
    form=FinancialRecordForm,
    formset=BaseFinancialRecordFormSet,
    fields=['origen_transaccion', 'fecha', 'hora', 'comprobante', 'banco_llegada',  'valor', 'payment_status'],
    extra=1,
    can_delete=True
)


class SellerForm(forms.ModelForm):
    class Meta:
        model = Seller
        fields =['name']
        widgets = {
            'name' : forms.TextInput(attrs={'class': 'form-control', 'placeholder':'Nombre del Vendedor'})
        }
        labels = {
            'name' : 'Nombre del Vendedor'
        }