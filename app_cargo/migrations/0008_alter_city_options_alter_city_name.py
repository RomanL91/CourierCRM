# Generated by Django 5.1.7 on 2025-05-26 01:54

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("app_cargo", "0007_alter_workdistribution_options_and_more"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="city",
            options={"verbose_name": "Город", "verbose_name_plural": "Города"},
        ),
        migrations.AlterField(
            model_name="city",
            name="name",
            field=models.CharField(
                help_text="Город (уникальное значение)",
                max_length=100,
                unique=True,
                verbose_name="Город",
            ),
        ),
    ]
