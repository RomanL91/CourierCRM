from decimal import Decimal

from django.contrib.auth.models import AbstractUser
from django.db import models

from app_orders.models import Order
from app_cargo.models import City


class User(AbstractUser):
    phone_number = models.CharField(max_length=50, blank=True, null=True)
    chat_id = models.BigIntegerField(blank=True, null=True)  # Telegram chat_id
    city = models.ForeignKey(
        City,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="employees",
    )  # город сотрудника

    def __str__(self):
        # Можно выводить либо username, либо (username + телефон)
        return f"{self.username} ({self.phone_number or 'no phone'})"


class CourierScore(models.Model):
    """
    Хранит информацию о том, кому и за какой заказ
    начислены баллы.
    """

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="courier_scores"
    )
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="scores")
    points = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=Decimal("1.00"),
    )  # Количество баллов
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Score {self.points} for {self.user} (order: {self.order.order_code})"


class TelegramGroup(models.Model):
    chat_id = models.BigIntegerField(unique=True, help_text="Идентификатор чата группы")
    title = models.CharField(max_length=255, help_text="Название группы")
    description = models.TextField(
        blank=True, null=True, help_text="Описание группы (опционально)"
    )
    group_type = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="Тип группы (например, 'курьеры', 'менеджеры' и т.д.)",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.title} (chat_id={self.chat_id})"
