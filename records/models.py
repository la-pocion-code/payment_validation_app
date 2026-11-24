from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone
from simple_history.models import HistoricalRecords
from django.contrib.auth.models import User
from django.db.models import Sum, Q
from datetime import datetime
from decimal import Decimal
from .utils import calculate_effective_date
import hashlib
import secrets
import re


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



class Client(models.Model):
    name = models.CharField("Nombre del Cliente", max_length=255)

    # DNI como texto para permitir letras y guiones
    dni = models.CharField("Documento", max_length=50, unique=True)

    # Referencia cruzada con Odoo (res.partner). La escribe la integración por API.
    odoo_id = models.PositiveBigIntegerField("ID en Odoo", null=True, blank=True, db_index=True)

    @property
    def available_balance(self):
        """
        Calcula el saldo a favor disponible para un cliente.
        Suma el valor de todos los recibos (FinancialRecord) que:
        1. Pertenecen a este cliente.
        2. Tienen estado 'Aprobado'.
        3. No están asociados a ninguna transacción (transaction is NULL).
        """
        total = self.financialrecord_set.filter(
            payment_status__in=['Aprobado', 'Pendiente'],
            transaction__isnull=True
        ).aggregate(
            total_balance=Sum('valor')
        )['total_balance']
        
        return total or Decimal('0.00')

    def save(self, *args, **kwargs):
        # Limpieza del campo DNI antes de guardar
        if self.dni:
            # Permitir solo letras, números y guiones
            self.dni = re.sub(r"[^A-Za-z0-9\-]", "", self.dni)
        # Limpiar nombre (permite letras y espacios)
        if self.name:
            # Mayúsculas
            self.name = self.name.upper()

            # Eliminar cualquier caracter que NO sea letra o espacio
            self.name = re.sub(r"[^A-Z\s]", "", self.name)

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.dni})"

    class Meta:
        verbose_name = "Cliente"
        verbose_name_plural = "Clientes"

class TransactionType(models.Model):
    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name
    
    def save(self, *args, **kwargs):
        self.name = self.name.upper()
        super(TransactionType, self).save(*args, **kwargs)
    
    class Meta:
        verbose_name = "Tipo de Transacción"
        verbose_name_plural = "Tipos de Transacción"


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

class Bank(models.Model):
    name = models.CharField(max_length=100, unique=True)
    

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.name = self.name.upper()
        super(Bank, self).save(*args, **kwargs)

class PaymentDocument(models.Model):
    name = models.CharField(max_length=100, unique=True)
    bank = models.ForeignKey(Bank, on_delete=models.PROTECT, verbose_name="Banco", null=True, blank=True)

    
    def __str__(self):
        return self.name

    def get_prefix(self):
        return self.name[:4].upper()

    def save(self, *args, **kwargs):
        self.name = self.name.upper()
        super(PaymentDocument, self).save(*args, **kwargs)

    class Meta:
        verbose_name = "Documento de Pago"
        verbose_name_plural = "Documentos de Pago"

class OrigenTransaccion(models.Model):
    name = models.CharField(max_length=100, unique=True)
    dias_efectivo = models.IntegerField(default=0, verbose_name="Días para ser efectivo")

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.name = self.name.upper()
        super(OrigenTransaccion, self).save(*args, **kwargs)

    class Meta:
        verbose_name = "Origen de Transacción"
        verbose_name_plural = "Origenes de Transacción"


class Transaction(models.Model):
    STATUS_CHOICES = [
        ('Pendiente', 'Pendiente'),
        ('Facturado', 'Facturado'),
        ('Anulado', 'Anulado'),
        ('No Facturable', 'No Facturable'),
    ]
    date = models.DateField(default=timezone.now, verbose_name="Fecha Pedido")
    cliente = models.ForeignKey(Client, on_delete=models.PROTECT, verbose_name="Cliente", null=True, blank=True)
    vendedor = models.ForeignKey(Seller,on_delete=models.PROTECT, verbose_name="Vendedor")
    transaction_type = models.ForeignKey(TransactionType, on_delete=models.PROTECT, verbose_name="Tipo de Transacción")
    description = models.CharField(max_length=255, verbose_name="Observación", blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Pendiente', verbose_name="Estado de Transacción")
    numero_factura = models.CharField(max_length=100, blank=True, null=True, verbose_name="# de Factura", default=None)
    facturador = models.CharField(max_length=100, blank=True, null=True, default=None)
    expected_amount = models.DecimalField(max_digits=12, decimal_places=2,  verbose_name="Valor Venta")
    unique_transaction_id = models.CharField(max_length=100, unique=True, null=True, blank=True, verbose_name="ID unico")
    creat_at = models.DateTimeField(auto_now_add=True, null=True, blank=True, verbose_name="Fecha de Creación")
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="transactions_created", verbose_name="Creado por")
    # Marca de última modificación: permite a Odoo / la intranet pedir por API solo
    # lo que cambió desde su última sincronización (?updated_since=).
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True, db_index=True, verbose_name="Última modificación")
    # Referencia cruzada con Odoo (account.move). La escribe la integración por API.
    odoo_id = models.PositiveBigIntegerField("ID en Odoo", null=True, blank=True, db_index=True)
    # updated_at cambia en cada guardado: fuera del historial para no ensuciar los diffs.
    history = HistoricalRecords(excluded_fields=['updated_at'])

    def save(self, *args, **kwargs):
        # Guarda para obtener el ID si es una transaccion nueva
        is_new = self._state.adding
        super().save(*args, **kwargs)
        # Generamos el ID único solo si es una transacción nueva y bo tiene uno
        if is_new and not self.unique_transaction_id:
            date_part = self.creat_at.strftime('%b%d%y').upper()
            
            
            user_part = 'na' # 'no asignado' por si no hay usuario
            if self.created_by:
                user_part = self.created_by.username[:2].upper()
                user_part = user_part.upper()

            sequence_part = str(self.id).zfill(6)
            randon_part = secrets.token_hex(2).upper()


            self.unique_transaction_id = f"{date_part}{user_part}{sequence_part}{randon_part}"
            # Usamao .update() para guardar solo este campo y evitar un bucle
            Transaction.objects.filter(id=self.id).update(unique_transaction_id=self.unique_transaction_id)

    # @property
    # def total_valor(self):
    #     return self.receipts.aggregate(total=Sum('valor'))['total'] or 0
    @property
    def receipts_total(self):
        """
        Suma el valor de todos los recibos (FinancialRecord) asociados.
        Devuelve un objeto Decimal.
        """
        total = self.receipts.aggregate(valor_total=Sum('valor'))['valor_total']
        return total or Decimal('0.00')

    @property
    def difference(self):
        """
        Calcula la diferencia entre el monto esperado y el total de recibos.
        Devuelve un objeto Decimal.
        """
        return self.expected_amount - self.receipts_total


    class Meta:
        verbose_name = "Transacción"
        verbose_name_plural = "Transacciones"
        indexes = [
            # La lista de inicio filtra por estado y ordena por -id.
            models.Index(fields=['status', '-id'], name='trx_status_id_idx'),
            models.Index(fields=['date'], name='trx_date_idx'),
        ]

    def __str__(self):
        return self.description if self.description else f"Transacción {self.id}"


class FinancialRecord(models.Model):
    APROVED_CHOICES = [
        ('Pendiente', 'Pendiente'),
        ('Aprobado', 'Aprobado'),
        ('Rechazado', 'Rechazado')
    ]
    fecha = models.DateField()
    hora = models.TimeField() 
    comprobante = models.CharField(max_length=200, verbose_name="# Comprobante")
    cliente = models.ForeignKey(Client, on_delete=models.PROTECT, verbose_name="Cliente", null=True, blank=True)
    banco_llegada = models.ForeignKey(Bank, on_delete=models.PROTECT, verbose_name="Banco Llegada")
    origen_transaccion = models.ForeignKey('OrigenTransaccion', on_delete=models.PROTECT, verbose_name="Origen de Transacción")
    valor = models.DecimalField(max_digits=12, decimal_places=2)
    payment_status = models.CharField(max_length=20, choices=APROVED_CHOICES, default='Pendiente', verbose_name="Estado de pago")
    payment_document = models.CharField(
        max_length=200,
        verbose_name="Documento de Pago",
        blank=True,
        null=True,
        help_text="Número del documento de pago. Debe iniciar con el prefijo del banco (ej: BAN-25154)."
    )
    note = models.TextField(max_length=200, verbose_name="Nota", blank=True, null=True)
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
    description = models.CharField(max_length=255, verbose_name="Descripción", blank=True, null=True)
    # En records/models.py, dentro de la clase FinancialRecord:
    linked_credit_note = models.OneToOneField(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='related_credit_note_pair',
        help_text='Vincula este saldo a favor con su contraparte (positiva o negativa).'
    )
    revisado = models.BooleanField(default=False, verbose_name="Revisado")




    class Meta:
        verbose_name = "Registro Financiero"
        verbose_name_plural = "Registros Financieros"
        unique_together = ['fecha', 'hora', 'comprobante', 'banco_llegada', 'valor']
        indexes = [
            models.Index(fields=['payment_status'], name='rec_status_idx'),
            # Recibos de una transacción por estado (lista del Facturador).
            models.Index(fields=['transaction', 'payment_status'], name='rec_trx_status_idx'),
            # Saldo a favor de un cliente (Client.available_balance).
            models.Index(fields=['cliente', 'payment_status'], name='rec_client_status_idx'),
            # La lista de recibos ordena por -creado.
            models.Index(fields=['-creado'], name='rec_creado_idx'),
        ]

    def display_client(self):
        """
        Retorna el cliente asociado al recibo.
        Si el recibo tiene un cliente directo (es un abono), lo retorna.
        Si el recibo está asociado a una transacción, retorna el cliente de esa transacción.
        """
        if self.cliente:
            return self.cliente
        elif self.transaction and self.transaction.cliente:
            return self.transaction.cliente
        return "N/A" # O puedes retornar None o una cadena vacía si prefieres


    def __str__(self):
        return f"{self.fecha} - {self.comprobante} - {self.valor}"

    def effective_date_message(self):
        """
        Genera un mensaje sobre la fecha de pago efectiva si el recibo está
        pendiente y tiene días de efectividad configurados.
        """
        # Condiciones: estado pendiente y un origen con días de efectividad > 1
        if (self.payment_status == 'Pendiente' and 
            self.origen_transaccion and 
            self.origen_transaccion.dias_efectivo > 1):

            dias = self.origen_transaccion.dias_efectivo
            fecha_efectiva = calculate_effective_date(self.fecha, dias)
            fecha_formateada = fecha_efectiva.strftime('%d/%m/%Y')

            return (
                f"{dias} días hábiles. "
                f"Fecha esperada: {fecha_formateada}."
            )

        # Si no se cumplen las condiciones, no devolvemos nada
        return None


    # def clean(self):
    #     # Ejemplo de validación adicional si 'valor' no puede ser negativo
    #     if self.valor is not None and self.valor < 0:
    #         raise ValidationError({'valor': 'El valor no puede ser negativo.'})



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


class FormSubmission(models.Model):
    """
    Llave de idempotencia de un envío de formulario.

    Cada render de un formulario de captura incluye un token UUID. Si el POST se
    reenvía (doble clic, F5 -> "reenviar formulario", o reintento del navegador o
    del proxy cuando la conexión se cae antes de recibir la respuesta), llega el
    mismo token y la escritura NO se vuelve a ejecutar: se responde con un redirect
    al resultado del envío original.

    La fila se inserta DENTRO del mismo transaction.atomic() que hace el guardado,
    así que solo es visible para otras conexiones si el guardado hizo commit. Si el
    guardado falla, el rollback libera el token y el usuario puede reenviar.
    """
    # La PK es el token: el índice único lo da la propia PK, y el INSERT en
    # conflicto es exactamente la señal de "esto ya se procesó".
    token = models.UUIDField(primary_key=True, editable=False, verbose_name="Token")
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='form_submissions',
        verbose_name="Usuario"
    )
    scope = models.CharField(max_length=100, verbose_name="Vista")
    result_url = models.CharField(max_length=500, blank=True, default='', verbose_name="URL del resultado")
    result_pk = models.BigIntegerField(null=True, blank=True, verbose_name="PK creada")
    result_label = models.CharField(max_length=100, blank=True, default='', verbose_name="Etiqueta del resultado")
    retry_count = models.PositiveIntegerField(default=0, verbose_name="Reenvíos absorbidos")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name="Fecha de creación")

    class Meta:
        verbose_name = "Envío de formulario"
        verbose_name_plural = "Envíos de formulario"
        indexes = [models.Index(fields=['scope', 'created_at'])]

    def __str__(self):
        return f"{self.scope} · {self.token}"


class ApiKey(models.Model):
    """
    Llave de acceso a la API REST para una integración (Odoo, la intranet...).

    La llave completa solo se muestra una vez, al crearla: aquí se guarda su hash.
    Cada llave tiene un usuario de servicio propio, de modo que el historial de
    cambios (django-simple-history) registra qué integración hizo cada escritura.
    """
    name = models.CharField("Integración", max_length=100, unique=True)
    prefix = models.CharField("Prefijo", max_length=12, unique=True, editable=False)
    hashed_key = models.CharField(max_length=64, editable=False)
    user = models.OneToOneField(
        User, on_delete=models.PROTECT, editable=False, related_name='api_key',
        verbose_name="Usuario de servicio",
    )
    can_write = models.BooleanField(
        "Puede escribir", default=False,
        help_text="Sin marcar, la llave solo puede consultar (GET).",
    )
    is_active = models.BooleanField("Activa", default=True)
    created_at = models.DateTimeField("Creada", auto_now_add=True)
    last_used_at = models.DateTimeField("Último uso", null=True, blank=True)

    class Meta:
        verbose_name = "Llave de API"
        verbose_name_plural = "Llaves de API"

    def __str__(self):
        return f"{self.name} ({self.prefix}…)"

    @staticmethod
    def hash_key(raw_key):
        return hashlib.sha256(raw_key.encode('utf-8')).hexdigest()

    @classmethod
    def issue(cls, name, can_write=False):
        """Crea la llave y devuelve (api_key, llave_en_claro). La llave no se puede recuperar después."""
        from django.utils.text import slugify

        prefix = secrets.token_hex(4)
        raw_key = f"pv_{prefix}_{secrets.token_urlsafe(32)}"
        username = f"api-{slugify(name) or prefix}"[:150]
        if User.objects.filter(username=username).exists():
            username = f"{username[:140]}-{prefix}"
        user = User(username=username, is_active=True)
        user.set_unusable_password()
        user.save()
        api_key = cls.objects.create(
            name=name, prefix=prefix, hashed_key=cls.hash_key(raw_key),
            user=user, can_write=can_write,
        )
        return api_key, raw_key
