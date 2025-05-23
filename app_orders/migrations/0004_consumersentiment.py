# Generated by Django 5.1.7 on 2025-03-14 21:01

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("app_orders", "0003_orderentry_entry_id_orderentry_images_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ConsumerSentiment",
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
                    "rating",
                    models.PositiveSmallIntegerField(
                        help_text="Оценка настроения потребителя (например, от 1 до 10)"
                    ),
                ),
                (
                    "comment",
                    models.TextField(
                        blank=True,
                        help_text="Опциональный комментарий курьера о настроении клиента",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "courier",
                    models.ForeignKey(
                        help_text="Курьер, оставивший оценку",
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="sentiments",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "order",
                    models.OneToOneField(
                        help_text="Заявка, для которой оставлен ИНП",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="consumer_sentiment",
                        to="app_orders.order",
                    ),
                ),
            ],
        ),
    ]
