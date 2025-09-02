# records/forms.py

from django import forms
from .models import FinancialRecord, Bank, DuplicateRecordAttempt
import json

class FinancialRecordForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request', None)
        super(FinancialRecordForm, self).__init__(*args, **kwargs)

    class Meta:
        model = FinancialRecord
        fields = ['fecha', 'hora', 'comprobante', 'banco_llegada', 'valor', 'cliente', 'vendedor']
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

        if fecha and hora and comprobante and banco_llegada and valor:
            qs = FinancialRecord.objects.filter(
                fecha=fecha,
                hora=hora,
                comprobante=comprobante,
                banco_llegada=banco_llegada,
                valor=valor
            )
            if self.instance and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)

            if qs.exists():
                # Log the duplicate attempt
                if self.request:
                    # Convert cleaned_data to a JSON serializable format
                    serializable_data = {k: str(v) for k, v in cleaned_data.items()}
                    DuplicateRecordAttempt.objects.create(
                        user=self.request.user,
                        data=serializable_data
                    )
                raise forms.ValidationError(
                    f"Registro duplicado: ya existe un registro con los mismos datos (Fecha: {fecha}, Hora: {hora}, Comprobante: {comprobante}, Banco: {banco_llegada}, Valor: {valor})."
                )
        return cleaned_data

class FinancialRecordUpdateForm(FinancialRecordForm):
    class Meta(FinancialRecordForm.Meta):
        fields = '__all__'

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

    
class BankForm(forms.ModelForm):
    class Meta:
        model = Bank
        fields = ['name']


class CSVUploadForm(forms.Form):
    csv_file = forms.FileField(label="Seleccionar archivo CSV")