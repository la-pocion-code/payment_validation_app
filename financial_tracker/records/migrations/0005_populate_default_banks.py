from django.db import migrations

def populate_default_banks(apps, schema_editor):
    Bank = apps.get_model('records', 'Bank')
    default_banks = ['BANCOLOMBIA', 'AV VILLAS', 'POPULAR']
    for bank_name in default_banks:
        Bank.objects.get_or_create(name=bank_name)

class Migration(migrations.Migration):

    dependencies = [
        ('records', '0004_bank_alter_financialrecord_banco_llegada_and_more'),
    ]

    operations = [
        migrations.RunPython(populate_default_banks),
    ]