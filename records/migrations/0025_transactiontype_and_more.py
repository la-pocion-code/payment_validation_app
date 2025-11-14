import django.db.models.deletion
from django.db import migrations, models


def create_default_transaction_type(apps, schema_editor):
    TransactionType = apps.get_model('records', 'TransactionType')
    # Crear o asegurar que existe el registro con ID 1
    TransactionType.objects.update_or_create(
        id=1,
        defaults={"name": "SIN DEFINIR"}
    )


class Migration(migrations.Migration):

    dependencies = [
        ('records', '0024_alter_historicaltransaction_expected_amount_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='TransactionType',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100, unique=True)),
            ],
            options={
                'verbose_name': 'Tipo de Transacción',
                'verbose_name_plural': 'Tipos de Transacción',
            },
        ),

        migrations.RunPython(create_default_transaction_type),

        migrations.AddField(
            model_name='historicaltransaction',
            name='transaction_type',
            field=models.ForeignKey(
                blank=True,
                db_constraint=False,
                null=True,
                on_delete=django.db.models.deletion.DO_NOTHING,
                related_name='+',
                to='records.transactiontype',
                verbose_name='Tipo de Transacción'
            ),
        ),

        migrations.AddField(
            model_name='transaction',
            name='transaction_type',
            field=models.ForeignKey(
                default=1,
                on_delete=django.db.models.deletion.PROTECT,
                to='records.transactiontype',
                verbose_name='Tipo de Transacción'
            ),
            preserve_default=False,
        ),
    ]
