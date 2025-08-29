# records/forms.py

from django import forms
from .models import FinancialRecord

class FinancialRecordForm(forms.ModelForm):
    class Meta:
        model = FinancialRecord
        fields = ['fecha', 'hora', 'comprobante', 'banco_llegada', 'valor', 'cliente']
        widgets = {
            'fecha': forms.DateInput(attrs={'type': 'date'}),
            'hora': forms.TimeInput(attrs={'type': 'time'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        fecha = cleaned_data.get('fecha')
        hora = cleaned_data.get('hora')
        comprobante = cleaned_data.get('comprobante')
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
                raise forms.ValidationError(
                    "¡Este registro financiero ya existe! Los campos Fecha, Hora, # Comprobante, Banco Llegada y Valor coinciden con un registro existente."
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

    
class CSVUploadForm(forms.Form):
    csv_file = forms.FileField(label="Seleccionar archivo CSV")