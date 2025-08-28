# records/forms.py

from django import forms
from .models import FinancialRecord

class FinancialRecordForm(forms.ModelForm):
    class Meta:
        model = FinancialRecord
        fields = '__all__' # Incluye todos los campos del modelo
        widgets = {
            'fecha': forms.DateInput(attrs={'type': 'date'}),
            'hora': forms.TimeInput(attrs={'type': 'time'}),
        }

    def clean(self):
        # Llama a la validación base del formulario (incluyendo unique_together)
        cleaned_data = super().clean()

        # Si ya existe un error de unique_together, no es necesario hacer la consulta.
        # Django maneja esto automáticamente a nivel de base de datos cuando se guarda.
        # Sin embargo, podemos agregar una verificación aquí para un mensaje más amigable
        # antes de intentar guardar y que la DB lance la excepción.

        # Esta es una validación adicional a nivel de formulario para un mensaje más directo.
        # La validación a nivel de BD con unique_together es la que asegura la integridad.
        fecha = cleaned_data.get('fecha')
        hora = cleaned_data.get('hora')
        comprobante = cleaned_data.get('comprobante')
        banco_llegada = cleaned_data.get('banco_llegada')
        valor = cleaned_data.get('valor')

        if fecha and hora and comprobante and banco_llegada and valor:
            # Excluye el propio objeto si estamos actualizando
            qs = FinancialRecord.objects.filter(
                fecha=fecha,
                hora=hora,
                comprobante=comprobante,
                banco_llegada=banco_llegada,
                valor=valor
            )
            if self.instance and self.instance.pk: # Si estamos actualizando un registro existente
                qs = qs.exclude(pk=self.instance.pk)

            if qs.exists():
                raise forms.ValidationError(
                    "¡Este registro financiero ya existe! Los campos Fecha, Hora, # Comprobante, Banco Llegada y Valor coinciden con un registro existente."
                )
        return cleaned_data
    
# class CSVUploadForm(forms.Form):
#     csv_file = forms.FileField(label="Seleccionar archivo CSV")