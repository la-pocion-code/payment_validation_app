from django.shortcuts import render, redirect
from django.contrib import messages # Para mostrar mensajes al usuario
from django.db import IntegrityError # Para capturar el error de unique_together
from .forms import FinancialRecordForm
from .models import FinancialRecord

def record_create_view(request):
    form = FinancialRecordForm() # Inicializa el formulario fuera del POST para el GET request

    if request.method == 'POST':
        form = FinancialRecordForm(request.POST) # Instancia el formulario con los datos POST
        if form.is_valid():
            try:
                record = form.save(commit=False) # No guarda aún, permite validaciones extra si fuera necesario
                record.save()
                messages.success(request, '¡Registro financiero guardado exitosamente!')
                return redirect('record_list') # Redirige a una lista de registros (la crearemos más tarde)
            except IntegrityError:
                # Este error se captura si la validación a nivel de formulario falló,
                # o si la BD (por alguna razón) es la primera en detectar el duplicado.
                messages.error(request, 'Error: Ya existe un registro con los mismos datos clave (Fecha, Hora, # Comprobante, Banco Llegada, Valor).')
            except Exception as e:
                messages.error(request, f'Ocurrió un error inesperado al guardar el registro: {e}')
        else:
            # Los errores de validación del formulario (incluyendo el de duplicidad custom)
            # se añadirán automáticamente al formulario y se mostrarán en la plantilla.
            messages.error(request, 'Por favor, corrige los errores en el formulario.')

    # Para requests GET o si el formulario no es válido en POST
    context = {'form': form}
    return render(request, 'records/records_form.html', context)

def record_list_view(request):
    records = FinancialRecord.objects.all().order_by('-fecha', '-hora')
    context = {'records': records}
    return render(request, 'records/records_list.html', context)