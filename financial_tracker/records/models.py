from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone
from simple_history.models import HistoricalRecords

class FinancialRecord(models.Model):
    STATUS_CHOICES = [
        ('Pendiente', 'Pendiente'),
        ('Facturado', 'Facturado'),
        ('Anulado', 'Anulado'),
    ]
    fecha = models.DateField()
    hora = models.TimeField()
    comprobante = models.CharField(max_length=200, verbose_name="# Comprobante")
    banco_llegada = models.CharField(max_length=100, verbose_name="Banco Llegada")
    valor = models.DecimalField(max_digits=10, decimal_places=2)
    cliente = models.CharField(max_length=200, blank=True, null=True)
    vendedor = models.CharField(max_length=100, blank=True, null=True)
    # status = models.CharField(max_length=50, blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Pendiente')
    numero_factura = models.CharField(max_length=100, blank=True, null=True, verbose_name="# de Factura", default=None)
    facturador = models.CharField(max_length=100, blank=True, null=True, default=None)
    history = HistoricalRecords()
    creado = models.DateTimeField(auto_now_add=True)
    modificado = models.DateTimeField(auto_now=True)

    class Meta:
        # Define la combinación única de campos
        unique_together = ('fecha', 'hora', 'comprobante', 'banco_llegada', 'valor')
        verbose_name = "Registro Financiero"
        verbose_name_plural = "Registros Financieros"

    def __str__(self):
        return f"{self.fecha} - {self.comprobante} - {self.valor}"

    # Puedes agregar validaciones adicionales aquí si es necesario
    def clean(self):
        # Ejemplo de validación adicional si 'valor' no puede ser negativo
        if self.valor is not None and self.valor < 0:
            raise ValidationError({'valor': 'El valor no puede ser negativo.'})