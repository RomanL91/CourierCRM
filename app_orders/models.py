from django.db import models

from django.conf import settings
from django.core.validators import (
    MinValueValidator,
    MaxValueValidator,
    FileExtensionValidator,
)


class Order(models.Model):
    order_code = models.CharField(max_length=50, unique=True)
    customer_firstname = models.CharField(max_length=100, blank=True)
    customer_lastname = models.CharField(max_length=100, blank=True)
    phone_number = models.CharField(max_length=50, blank=True)
    total_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    order_status = models.CharField(max_length=50, blank=True)

    # Дополнительно можно хранить сырые данные (JSONField, если нужно)
    raw_json = models.JSONField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Order {self.order_code} ({self.order_status})"

    def get_last_user_in_history(self):
        users = self.history.latest("create_date")
        return users


class OrderEntry(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="entries")

    entry_id = models.IntegerField(null=True, blank=True)
    name = models.CharField(max_length=200)
    quantity = models.IntegerField(default=1)
    weight = models.FloatField(default=0.0)
    base_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    master_product_code = models.CharField(max_length=50, blank=True)
    master_product_url = models.URLField(max_length=500, blank=True)
    master_product_name = models.CharField(max_length=200, blank=True)

    merchant_product_sku = models.CharField(max_length=100, blank=True)
    merchant_product_name = models.CharField(max_length=200, blank=True)

    # unit (если хотим хранить подробно)
    unit_code = models.CharField(max_length=50, blank=True)
    unit_display_name = models.CharField(max_length=100, blank=True)
    unit_type = models.CharField(max_length=50, blank=True)

    images = models.JSONField(null=True, blank=True)  # Или отдельная модель EntryImage

    raw_entry = models.JSONField(null=True, blank=True)  # можно сохранить сырое всё

    class Meta:
        unique_together = (
            "order",
            "entry_id",
        )

    def __str__(self):
        return f"Order#{self.order.order_code} - EntryID {self.entry_id} - {self.name}"


class OrderHistory(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="history")
    create_date = models.DateTimeField()
    action = models.CharField(max_length=100, blank=True)
    user_type = models.CharField(max_length=100, blank=True)
    user_name = models.CharField(max_length=150, blank=True)
    user_email = models.EmailField(blank=True)
    user_phone = models.CharField(max_length=50, blank=True)
    description = models.TextField(blank=True)
    raw_data = models.JSONField(null=True, blank=True)

    # Новое поле:
    processed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="order_history_entries",
    )

    def __str__(self):
        return f"[{self.order.order_code}] {self.action} ({self.user_type})"


class ConsumerSentiment(models.Model):
    """
    Модель для хранения индекса настроения потребителя (ИНП).
    Предполагается, что для каждой заявки (Order) курьер оставляет один рейтинг.
    """

    SENTIMENT_CHOICES = (
        ("excellent", "Отлично"),
        ("not_excellent", "Не отлично"),
    )

    order = models.OneToOneField(
        "Order",
        on_delete=models.CASCADE,
        related_name="consumer_sentiment",
        help_text="Заявка, для которой оставлен ИНП",
    )
    courier = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="sentiments",
        help_text="Курьер, оставивший оценку",
    )
    rating = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(10)],
        help_text="Оценка настроения потребителя (от 1 до 10)",
        blank=True,
        null=True,
    )
    sentiment = models.CharField(
        max_length=20,
        choices=SENTIMENT_CHOICES,
        help_text="Оценка настроения потребителя (Отлично или Не отлично)",
    )
    comment = models.TextField(
        blank=True, help_text="Опциональный комментарий курьера о настроении клиента"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        sent = "Отлично" if self.sentiment == "excellent" else "Не отлично"
        return f"ИНП для заказа {self.order.order_code}: {sent}"


class DeliveryProof(models.Model):
    """
    Модель для хранения видео-доказательства доставки.
    Каждый заказ может иметь одно видео, подтверждающее передачу товара.
    """

    order = models.OneToOneField(
        "Order",
        on_delete=models.CASCADE,
        related_name="delivery_proof",
        help_text="Заявка, к которой приложено видео-доказательство",
    )
    courier = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="delivery_proofs",
        help_text="Курьер, загрузивший видео",
    )
    video = models.FileField(
        upload_to="delivery_proofs/",
        null=True,
        blank=True,
        validators=[
            FileExtensionValidator(allowed_extensions=["mp4", "mov", "avi", "mkv"])
        ],
        help_text="Видео-доказательство доставки (опционально). Допустимые форматы: mp4, mov, avi, mkv.",
    )
    uploaded_at = models.DateTimeField(
        auto_now_add=True, help_text="Дата и время загрузки видео"
    )

    def __str__(self):
        return f"Видео доставки для заказа {self.order.order_code}"


class OrderPreparation(models.Model):
    order_code = models.CharField(max_length=50)
    preparation_type = models.CharField(max_length=20)
    telegram_chat_id = models.CharField(max_length=30)
    executor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="order_preparition",
    )

    class Meta:
        # считаем дубликатом полностью одинаковое сообщение из RabbitMQ
        constraints = [
            models.UniqueConstraint(
                fields=["order_code", "preparation_type", "telegram_chat_id"],
                name="uniq_prep_event",
            )
        ]

    def __str__(self):
        who = self.executor or "- unknow -"
        return f"Подотовил {self.order_code} - {self.preparation_type} - {who}"
