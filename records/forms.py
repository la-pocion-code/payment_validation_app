# records/forms.py

from django import forms
from .models import FinancialRecord, Bank, DuplicateRecordAttempt
import json
from django.contrib.auth.models import User, Group # New import for Group
from django.contrib.auth.forms import UserChangeForm # New import
from .models import AccessRequest # New import for AccessRequest
from django.utils.html import format_html

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

        if not self.instance.pk and not (self.request and self.request.user.is_superuser):
            hidden_fields =  ['numero_factura', 'facturador', 'status']
            for field in hidden_fields:
                if field in self.fields:
                    del self.fields[field]


    class Meta:
        model = FinancialRecord
        fields = ['fecha', 'hora', 'comprobante', 'banco_llegada', 'valor', 'cliente', 'vendedor', 'facturador', 'status', 'numero_factura']
        widgets = {
            'fecha': forms.DateInput(attrs={'type': 'date'}),
            'hora': forms.TimeInput(attrs={'type': 'time'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        cliente = cleaned_data.get('cliente')
        vendedor = cleaned_data.get('vendedor')
        comprobante = cleaned_data.get('comprobante')

        if cliente:
            cleaned_data['cliente'] = cliente.strip().title()
        
        if vendedor:
            cleaned_data['vendedor'] = vendedor.strip().title()
        
        if comprobante:
            cleaned_data['comprobante'] = comprobante.strip()

        fecha = cleaned_data.get('fecha')
        hora = cleaned_data.get('hora')
        banco_llegada = cleaned_data.get('banco_llegada')
        valor = cleaned_data.get('valor')

        # Solo realizamos estas verificaciones para nuevos registros
        if not self.instance.pk:
            # 1. Verificación de duplicado EXACTO (bloquea la creación) - ESTA DEBE IR PRIMERO
            if fecha and hora and comprobante and banco_llegada and valor:
                exact_qs = FinancialRecord.objects.filter(
                    fecha=fecha,
                    hora=hora,
                    comprobante=comprobante,
                    banco_llegada=banco_llegada,
                    valor=valor
                )
                if exact_qs.exists():
                    # Log del intento de duplicado EXACTO
                    if self.request:
                        serializable_data = {k: str(v) for k, v in cleaned_data.items()}
                        DuplicateRecordAttempt.objects.create(
                            user=self.request.user,
                            data=serializable_data,
                            attempt_type='DUPLICATE' # Tipo 'DUPLICATE'
                        )
                    raise forms.ValidationError(
                        format_html('<div id="exact-duplicate-error">Registro duplicado exacto: ya existe un registro con los mismos datos (Fecha: {}, Hora: {}, Comprobante: {}, Banco: {}, Valor: {}).</div>', fecha, hora, comprobante, banco_llegada.name, valor)
                    )

            # 2. Verificación de registro SIMILAR (para confirmación del usuario) - ESTA DEBE IR SEGUNDO
            # Esta verificación se ejecuta si no se encontró un duplicado exacto.
            if fecha and banco_llegada and valor:
                similar_qs = FinancialRecord.objects.filter(
                    fecha=fecha,
                    banco_llegada=banco_llegada,
                    valor=valor
                )
                # Excluimos los registros que ya habrían sido capturados como duplicados exactos
                # Esto asegura que solo marquemos como "similar" lo que no es un duplicado exacto.
                if fecha and hora and comprobante and banco_llegada and valor:
                    similar_qs = similar_qs.exclude(
                        fecha=fecha,
                        hora=hora,
                        comprobante=comprobante,
                        banco_llegada=banco_llegada,
                        valor=valor
                    )

                if similar_qs.exists():
                    self.existing_record = similar_qs.first()
                    # NO RETORNAR AQUÍ. Permitir que el método clean() termine.
        
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
            self.fields['cliente'].disabled = True
            self.fields['vendedor'].disabled = True

            if user.groups.filter(name='Facturador').exists():
                self.instance.facturador = user.username
                self.fields['facturador'].disabled = True
            else:
                self.fields['facturador'].disabled = True

    
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
