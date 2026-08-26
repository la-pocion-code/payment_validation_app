"""
Informe de solo lectura sobre duplicados de recibos.

Sirve para medir el problema de los reenvíos por red inestable ANTES y DESPUÉS de
desplegar la llave de idempotencia. No escribe nada en la base de datos.

Uso:
    python manage.py diagnose_duplicates
    railway run python manage.py diagnose_duplicates      # contra producción
"""

from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand
from django.db.models import Count, Sum
from django.utils import timezone

from records.models import (
    DuplicateRecordAttempt,
    FinancialRecord,
    FormSubmission,
    Transaction,
)

# Un intento de duplicado registrado a menos de este margen del guardado real, por
# el mismo usuario y con los mismos datos, es un reenvío de red, no un duplicado.
VENTANA_REINTENTO = timedelta(seconds=120)

# Dos transacciones idénticas creadas dentro de este margen son sospechosas de ser
# el caso "creí que no se guardó y volví a digitar".
VENTANA_GEMELAS = timedelta(minutes=10)


class Command(BaseCommand):
    help = (
        'Informe de solo lectura sobre duplicados de recibos: cuántos "duplicados" '
        'son en realidad reenvíos por red inestable, y cuántos duplicados reales '
        'se colaron.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=None,
            help='Analizar solo los últimos N días (por defecto: todo el histórico).'
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=15,
            help='Máximo de ejemplos a listar por sección (por defecto: 15).'
        )

    # ------------------------------------------------------------------ helpers

    def titulo(self, texto):
        self.stdout.write('')
        self.stdout.write(self.style.MIGRATE_HEADING(texto))
        self.stdout.write('-' * len(texto))

    def _parse_fecha(self, valor):
        for fmt in ('%Y-%m-%d', '%d-%m-%Y', '%d/%m/%Y'):
            try:
                return datetime.strptime(valor, fmt).date()
            except (ValueError, TypeError):
                continue
        return None

    def _parse_hora(self, valor):
        for fmt in ('%H:%M:%S', '%H:%M'):
            try:
                return datetime.strptime(valor, fmt).time()
            except (ValueError, TypeError):
                continue
        return None

    def _parse_valor(self, valor):
        try:
            return Decimal(str(valor))
        except (InvalidOperation, TypeError, ValueError):
            return None

    # -------------------------------------------------------------------- handle

    def handle(self, *args, **options):
        limite = options['limit']
        desde = None
        if options['days']:
            desde = timezone.now() - timedelta(days=options['days'])
            self.stdout.write(self.style.NOTICE(
                f'Ventana de análisis: últimos {options["days"]} días '
                f'(desde {desde:%d-%m-%Y}).'
            ))
        else:
            self.stdout.write(self.style.NOTICE('Ventana de análisis: histórico completo.'))

        self.seccion_reintentos(desde, limite)
        self.seccion_transacciones_gemelas(desde, limite)
        self.seccion_recibos_casi_identicos(desde, limite)
        self.seccion_notas_credito(limite)
        self.seccion_tokens(desde)

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('Informe terminado. No se modificó ningún dato.'))

    # ------------------------------------------------- 1. falsos por reintento

    def seccion_reintentos(self, desde, limite):
        self.titulo('1. Intentos de duplicado que en realidad son reenvíos de red')

        intentos = DuplicateRecordAttempt.objects.filter(attempt_type='DUPLICATE')
        if desde:
            intentos = intentos.filter(timestamp__gte=desde)
        intentos = intentos.select_related('user').order_by('-timestamp')

        total = intentos.count()
        if not total:
            self.stdout.write('No hay intentos de duplicado exacto registrados.')
            return

        reintentos = []
        sin_pareja = 0

        for intento in intentos.iterator():
            data = intento.data or {}
            fecha = self._parse_fecha(data.get('fecha'))
            hora = self._parse_hora(data.get('hora'))
            comprobante = (data.get('comprobante') or '').strip()
            valor = self._parse_valor(data.get('valor'))

            if not (fecha and hora and comprobante and valor is not None):
                sin_pareja += 1
                continue

            # El recibo que hizo que este intento fuera rechazado.
            existente = FinancialRecord.objects.filter(
                fecha=fecha, hora=hora, comprobante=comprobante, valor=valor
            ).select_related('uploaded_by').first()

            if existente is None or existente.creado is None:
                sin_pareja += 1
                continue

            mismo_usuario = existente.uploaded_by_id == intento.user_id
            delta = abs(existente.creado - intento.timestamp)

            if mismo_usuario and delta <= VENTANA_REINTENTO:
                reintentos.append((intento, existente, delta))

        pct = (len(reintentos) / total * 100) if total else 0
        self.stdout.write(f'Intentos de duplicado exacto analizados: {total}')
        self.stdout.write(self.style.WARNING(
            f'Compatibles con un reenvío del propio usuario: {len(reintentos)} ({pct:.1f}%)'
        ))
        self.stdout.write(f'Sin recibo emparejable (datos incompletos o recibo borrado): {sin_pareja}')

        if reintentos:
            self.stdout.write('')
            self.stdout.write(f'Ejemplos (hasta {limite}):')
            for intento, existente, delta in reintentos[:limite]:
                self.stdout.write(
                    f'  · {intento.timestamp:%d-%m-%Y %H:%M:%S} '
                    f'usuario={intento.user} '
                    f'comprobante={existente.comprobante} '
                    f'valor={existente.valor} '
                    f'(+{delta.total_seconds():.0f}s del guardado real, recibo #{existente.pk})'
                )

    # ------------------------------------------- 2. transacciones gemelas

    def seccion_transacciones_gemelas(self, desde, limite):
        self.titulo('2. Transacciones gemelas (posible re-digitación tras un "duplicado")')

        transacciones = Transaction.objects.all()
        if desde:
            transacciones = transacciones.filter(creat_at__gte=desde)

        campos = ['cliente', 'vendedor', 'date', 'transaction_type', 'expected_amount', 'created_by']
        grupos = (
            transacciones.values(*campos)
            .annotate(n=Count('id'))
            .filter(n__gt=1)
            .order_by('-n')
        )

        sospechosas = []
        for grupo in grupos:
            filtro = {campo: grupo[campo] for campo in campos}
            filas = list(
                transacciones.filter(**filtro)
                .select_related('cliente', 'vendedor', 'created_by')
                .order_by('creat_at')
            )
            for anterior, siguiente in zip(filas, filas[1:]):
                if not (anterior.creat_at and siguiente.creat_at):
                    continue
                if siguiente.creat_at - anterior.creat_at <= VENTANA_GEMELAS:
                    sospechosas.append((anterior, siguiente))

        if not sospechosas:
            self.stdout.write('Sin transacciones gemelas dentro de la ventana de 10 minutos.')
            return

        self.stdout.write(self.style.WARNING(
            f'Pares de transacciones idénticas creadas en menos de 10 minutos: {len(sospechosas)}'
        ))
        self.stdout.write('')
        self.stdout.write(f'Ejemplos (hasta {limite}):')
        for anterior, siguiente in sospechosas[:limite]:
            delta = (siguiente.creat_at - anterior.creat_at).total_seconds()
            self.stdout.write(
                f'  · {anterior.unique_transaction_id} y {siguiente.unique_transaction_id} '
                f'| cliente={anterior.cliente} | valor={anterior.expected_amount} '
                f'| usuario={anterior.created_by} | separadas {delta:.0f}s'
            )

    # -------------------------------------- 3. recibos que difieren solo en hora

    def seccion_recibos_casi_identicos(self, desde, limite):
        self.titulo('3. Recibos casi idénticos (difieren solo en la hora)')

        recibos = FinancialRecord.objects.all()
        if desde:
            recibos = recibos.filter(creado__gte=desde)

        campos = ['fecha', 'comprobante', 'banco_llegada', 'valor']
        grupos = (
            recibos.values(*campos)
            .annotate(n=Count('id'))
            .filter(n__gt=1)
            .order_by('-n')
        )
        grupos = list(grupos)

        if not grupos:
            self.stdout.write(
                'Sin recibos que compartan fecha, comprobante, banco y valor. '
                'El unique_together no dejó escapar nada por diferencia de hora.'
            )
            return

        total_extra = sum(g['n'] - 1 for g in grupos)
        self.stdout.write(self.style.WARNING(
            f'Grupos afectados: {len(grupos)} | recibos excedentes: {total_extra}'
        ))
        self.stdout.write(
            'Estos SÍ son duplicados reales: el unique_together incluye la hora, '
            'así que no los bloqueó.'
        )
        self.stdout.write('')
        self.stdout.write(f'Ejemplos (hasta {limite}):')
        for grupo in grupos[:limite]:
            filas = recibos.filter(**{c: grupo[c] for c in campos}).order_by('hora')
            horas = ', '.join(str(r.hora) for r in filas)
            self.stdout.write(
                f'  · {grupo["fecha"]} | comprobante={grupo["comprobante"]} '
                f'| valor={grupo["valor"]} | {grupo["n"]} recibos | horas: {horas}'
            )

    # ----------------------------------------- 4. notas crédito duplicadas

    def seccion_notas_credito(self, limite):
        self.titulo('4. Saldos a favor / ajustes duplicados (SF-FAVOR-*, SF-AJUSTE-*)')

        grupos = list(
            FinancialRecord.objects
            .filter(comprobante__startswith='SF-')
            .values('comprobante')
            .annotate(n=Count('id'))
            .filter(n__gt=1)
            .order_by('-n')
        )

        if not grupos:
            self.stdout.write('Sin saldos a favor ni ajustes duplicados.')
            return

        self.stdout.write(self.style.ERROR(
            f'Comprobantes SF- repetidos: {len(grupos)} '
            f'(excedentes: {sum(g["n"] - 1 for g in grupos)})'
        ))
        self.stdout.write('')
        self.stdout.write(f'Ejemplos (hasta {limite}):')
        for grupo in grupos[:limite]:
            filas = FinancialRecord.objects.filter(comprobante=grupo['comprobante']).order_by('hora')
            detalle = ', '.join(f'#{r.pk}@{r.hora}' for r in filas)
            self.stdout.write(f'  · {grupo["comprobante"]} | {grupo["n"]} registros | {detalle}')

    # ------------------------------------- 5. reenvíos absorbidos por el token

    def seccion_tokens(self, desde):
        self.titulo('5. Reenvíos absorbidos por la llave de idempotencia')

        tokens = FormSubmission.objects.all()
        if desde:
            tokens = tokens.filter(created_at__gte=desde)

        total = tokens.count()
        if not total:
            self.stdout.write(
                'Todavía no hay envíos registrados. Si la llave de idempotencia ya '
                'está desplegada, esta sección se irá poblando con el uso.'
            )
            return

        con_reintento = tokens.filter(retry_count__gt=0)
        suma = con_reintento.aggregate(total=Sum('retry_count'))['total'] or 0

        self.stdout.write(f'Envíos registrados: {total}')
        self.stdout.write(self.style.SUCCESS(
            f'Envíos que recibieron al menos un reenvío: {con_reintento.count()} '
            f'| reenvíos totales bloqueados: {suma}'
        ))
        self.stdout.write('')
        self.stdout.write('Por vista:')
        for fila in tokens.values('scope').annotate(n=Count('token'), reenvios=Sum('retry_count')).order_by('-n'):
            self.stdout.write(
                f'  · {fila["scope"]}: {fila["n"]} envíos, '
                f'{fila["reenvios"] or 0} reenvíos bloqueados'
            )
