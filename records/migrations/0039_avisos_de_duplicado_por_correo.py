from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def crear_plantillas(apps, schema_editor):
    """Una plantilla por tipo de intento, INACTIVA: nada se envía hasta que un admin la active."""
    from records.alerts import DEFAULTS

    Template = apps.get_model('records', 'DuplicateAlertTemplate')
    for key, texts in DEFAULTS.items():
        Template.objects.get_or_create(key=key, defaults={
            'subject': texts['subject'], 'body': texts['body'], 'is_active': False,
        })


class Migration(migrations.Migration):

    dependencies = [
        ('records', '0038_api_llaves_y_sincronizacion'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='DuplicateAlertTemplate',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('key', models.CharField(choices=[('DUPLICATE', 'Duplicado exacto (bloqueado por el sistema)'), ('SIMILAR', 'Posible duplicado (confirmado por el digitador)')], max_length=20, unique=True, verbose_name='Tipo de aviso')),
                ('is_active', models.BooleanField(default=False, verbose_name='Enviar este aviso')),
                ('recipients', models.TextField(blank=True, help_text='Correos separados por coma o por línea.', verbose_name='Para')),
                ('cc', models.TextField(blank=True, verbose_name='Con copia')),
                ('subject', models.CharField(max_length=200, verbose_name='Asunto')),
                ('body', models.TextField(verbose_name='Mensaje')),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Aviso de duplicado por correo',
                'verbose_name_plural': 'Avisos de duplicado por correo',
                'ordering': ['key'],
            },
        ),
        migrations.RunPython(crear_plantillas, migrations.RunPython.noop),
    ]
