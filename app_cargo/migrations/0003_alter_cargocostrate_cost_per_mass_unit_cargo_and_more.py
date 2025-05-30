# Generated by Django 5.1.7 on 2025-05-21 05:46

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("app_cargo", "0002_cargocostrate"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name="cargocostrate",
            name="cost_per_mass_unit",
            field=models.DecimalField(
                decimal_places=2, help_text="Стоимость за 1 т", max_digits=10
            ),
        ),
        migrations.CreateModel(
            name="Cargo",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("id_external", models.BigIntegerField(unique=True)),
                ("mass", models.FloatField(blank=True, null=True)),
                ("volume", models.FloatField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "city_from",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="cargoes_sent",
                        to="app_cargo.city",
                    ),
                ),
                (
                    "city_to",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="cargoes_received",
                        to="app_cargo.city",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="WorkUnit",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "work_type",
                    models.CharField(
                        choices=[("load", "Погрузка"), ("unload", "Разгрузка")],
                        max_length=10,
                    ),
                ),
                ("mass_units", models.FloatField(default=0)),
                ("volume_units", models.FloatField(default=0)),
                ("total_score", models.DecimalField(decimal_places=2, max_digits=10)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "cargo",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="work_units",
                        to="app_cargo.cargo",
                    ),
                ),
                (
                    "city",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT, to="app_cargo.city"
                    ),
                ),
            ],
            options={
                "unique_together": {("cargo", "city", "work_type")},
            },
        ),
        migrations.CreateModel(
            name="WorkDistribution",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("score_share", models.DecimalField(decimal_places=2, max_digits=10)),
                ("scanned_at", models.DateTimeField(auto_now_add=True)),
                (
                    "employee",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "work_unit",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="distributions",
                        to="app_cargo.workunit",
                    ),
                ),
            ],
            options={
                "unique_together": {("work_unit", "employee")},
            },
        ),
    ]
