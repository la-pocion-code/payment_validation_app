# records/forms.py

from django import forms
from django.forms import modelformset_factory, BaseModelFormSet
from .models import FinancialRecord, Bank, DuplicateRecordAttempt, AccessRequest, Transaction, Seller
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
    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request', None)
        super(FinancialRecordForm, self).__init__(*args, **kwargs)
        # Atributo para guardar el registro similar encontrado
        self.existing_record = None
        print(f"DEBUG: FinancialRecordForm __init__ - instance.pk: {self.instance.pk}, request: {self.request is not None}") # AÑADIR ESTO

    class Meta:
        model = FinancialRecord
        fields = ['fecha', 'hora', 'comprobante', 'banco_llegada', 'valor']
        widgets = {
            'fecha': forms.DateInput(attrs={'type': 'date'}),
            'hora': forms.TimeInput(attrs={'type': 'time', 'step': '1'}),
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

                if similar_qs.exists():
                    if self.request:
                        serializable_data = {k: str(v) for k, v in cleaned_data.items()}
                        DuplicateRecordAttempt.objects.create(
                            user=self.request.user,
                            data=serializable_data,
                            attempt_type='SIMILAR'
                        )
                    raise forms.ValidationError(
                        format_html('<div id="similar-duplicate-error">Posible registro duplicado: ya existe un registro con la misma Fecha, Hora, Banco y Valor. Por favor, revisa los registros existentes.</div>')
                    )

        return cleaned_data



class FinancialRecordUpdateForm(FinancialRecordForm):
    class Meta(FinancialRecordForm.Meta):
        exclude = ['uploaded_by']

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)


        if user and not user.is_superuser:
            self.fields['fecha'].disabled = True
            self.fields['hora'].disabled = True
            self.fields['comprobante'].disabled = True
            self.fields['banco_llegada'].disabled = True
            self.fields['valor'].disabled = True


            # if user.groups.filter(name='Facturador').exists():
            #     self.instance.facturador = user.username
            #     self.fields['facturador'].disabled = True
            # else:
            #     self.fields['facturador'].disabled = True

    
class BankForm(forms.ModelForm):
    class Meta:
        model = Bank
        fields = ['name']


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
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        # For new transactions, set status to 'Pendiente' and hide the field.
        if not self.instance.pk:
            self.fields['status'].initial = 'Pendiente'
            self.fields['status'].widget = forms.HiddenInput()
            self.fields['date'].initial = timezone.now().date()

        if user and not user.is_superuser:
            if user.groups.filter(name='Facturador').exists():
                allowed_fields = ['description', 'status', 'numero_factura']
                for field_name, field in self.fields.items():
                    if field_name not in allowed_fields:
                        field.disabled = True
            else:
                for field in self.fields.values():
                    field.disabled = True

    class Meta:
        model = Transaction
        fields = ['date', 'cliente', 'vendedor','description', 'status', 'numero_factura', 'facturador']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date', 'id': 'id_transaction_date', 'class': 'form-control'}),
        }

FinancialRecordFormSet = modelformset_factory(
    FinancialRecord,
    form=FinancialRecordForm,
    formset=BaseFinancialRecordFormSet,
    fields=['fecha', 'hora', 'comprobante', 'banco_llegada', 'valor'],
    extra=0,
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