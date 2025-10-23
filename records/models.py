from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone
from simple_history.models import HistoricalRecords
from django.contrib.auth.models import User
from django.db.models import Sum



class Seller(models.Model):
    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name
    
    def save(self, *args,  **kwargs):
        self.name = self.name.upper()
        super(Seller, self).save(*args, **kwargs)
    
    class Meta:
        verbose_name = "Vendedor"
        verbose_name_plural = "Vendedores"


class AuthorizedUser(models.Model):
    email = models.EmailField(unique=True)

    class Meta:
        verbose_name = "Usuario Autorizado"
        verbose_name_plural = "Usuarios Autorizados"

    def __str__(self):
        return self.email

    def save(self, *args, **kwargs):
        self.email = self.email.lower()
        super(AuthorizedUser, self).save(*args, **kwargs)


class Bank(models.Model):
    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.name = self.name.upper()
        super(Bank, self).save(*args, **kwargs)

class Transaction(models.Model):
    STATUS_CHOICES = [
        ('Pendiente', 'Pendiente'),
        ('Facturado', 'Facturado'),
        ('Anulado', 'Anulado'),
    ]
    date = models.DateField(default=timezone.now, verbose_name="Fecha de Transacción")
    cliente = models.CharField(max_length=200, blank=True, null=True)
    vendedor = models.ForeignKey(Seller,on_delete=models.PROTECT, verbose_name="Vendedor")
    description = models.CharField(max_length=255, verbose_name="Descripción", blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Pendiente', verbose_name="Estado de Transacción")
    numero_factura = models.CharField(max_length=100, blank=True, null=True, verbose_name="# de Factura", default=None)
    facturador = models.CharField(max_length=100, blank=True, null=True, default=None)
    history = HistoricalRecords()
       

    @property
    def total_valor(self):
        return self.receipts.aggregate(total=Sum('valor'))['total'] or 0


    class Meta:
        verbose_name = "Transacción"
        verbose_name_plural = "Transacciones"

    def __str__(self):
        return self.description if self.description else f"Transacción {self.id}"


class FinancialRecord(models.Model):
    fecha = models.DateField()
    hora = models.TimeField()
    comprobante = models.CharField(max_length=200, verbose_name="# Comprobante")
    banco_llegada = models.ForeignKey(Bank, on_delete=models.PROTECT, verbose_name="Banco Llegada")
    valor = models.DecimalField(max_digits=10, decimal_places=2)
    transaction = models.ForeignKey(
        'Transaction', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='receipts',
        verbose_name="Transacción"
    )
    history = HistoricalRecords()
    creado = models.DateTimeField(auto_now_add=True)
    modificado = models.DateTimeField(auto_now=True)
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='uploaded_financial_records')

    class Meta:
        verbose_name = "Registro Financiero"
        verbose_name_plural = "Registros Financieros"
        unique_together = ['fecha', 'hora', 'comprobante', 'banco_llegada', 'valor']

    def __str__(self):
        return f"{self.fecha} - {self.comprobante} - {self.valor}"

    # Puedes agregar validaciones adicionales aquí si es necesario
    def clean(self):
        # Ejemplo de validación adicional si 'valor' no puede ser negativo
        if self.valor is not None and self.valor < 0:
            raise ValidationError({'valor': 'El valor no puede ser negativo.'})



class DuplicateRecordAttempt(models.Model):
    ATTEMPT_TYPE_CHOICES = [
        ('DUPLICATE', 'Duplicado Exacto'),
        ('SIMILAR', 'Posible Duplicado (Confirmado)'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    timestamp = models.DateTimeField(auto_now_add=True)
    data = models.JSONField()
    is_resolved = models.BooleanField(default=False)
    resolved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='resolved_attempts')
    resolved_at = models.DateTimeField(null=True, blank=True)
    attempt_type = models.CharField(max_length=20, choices=ATTEMPT_TYPE_CHOICES, default='DUPLICATE') # Nuevo campo

    def __str__(self):
        return f"{self.get_attempt_type_display()} by {self.user} at {self.timestamp}"

class AccessRequest(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    approved = models.BooleanField(default=False)
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Access request from {self.user.username}"




