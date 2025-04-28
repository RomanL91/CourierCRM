from decimal import Decimal

from django.contrib import admin

from django.db.models import Sum, Value
from django.db.models.functions import Coalesce

from app_orders.FiltersAdmin import HasSentimentFilter, HasVideoProofsFilter
from app_orders.models import (
    Order,
    OrderEntry,
    OrderHistory,
    ConsumerSentiment,
    DeliveryProof,
    OrderPreparation,
)


class ConsumerSentimentInline(admin.TabularInline):
    """Inline для отзывов клиентов (ConsumerSentiment) в заказе"""

    model = ConsumerSentiment
    # extra = 0
    fields = (
        "courier",
        "sentiment",
        # "comment",
        "created_at",
    )
    readonly_fields = ("created_at",)
    verbose_name = "Отзыв курьера"
    verbose_name_plural = "Отзывы курьеров"


class DeliveryProofInline(admin.TabularInline):
    """Inline для подтверждения доставки (DeliveryProof)"""

    model = DeliveryProof
    # extra = 0
    fields = ("courier", "video", "uploaded_at")
    readonly_fields = ("uploaded_at",)
    verbose_name = "Видео подтверждение"
    verbose_name_plural = "Видео подтверждения"


class OrderEntryInline(admin.TabularInline):
    model = OrderEntry
    extra = 0
    fields = (
        "name",
        "quantity",
        "base_price",
        "total_price",
        "master_product_url",
        # "raw_entry",
    )
    readonly_fields = (
        "name",
        "quantity",
        "base_price",
        "total_price",
        "master_product_url",
        # "raw_entry",
    )


class OrderHistoryInline(admin.TabularInline):
    model = OrderHistory
    extra = 0
    fields = (
        "create_date",
        "action",
        # "user_type",
        # "user_name",
        "user_email",
        "user_phone",
        "processed_by",
        # "description",
        # "raw_data",
    )
    readonly_fields = (
        "create_date",
        "action",
        # "user_type",
        # "user_name",
        "user_email",
        "user_phone",
        "processed_by",
        # "description",
        # "raw_data",
    )


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "order_code",
        "customer_full_name",
        # "order_status",
        "total_price",
        "consumer_sentiment",
        "delivery_proof",
        "show_merchant_users",
        "points_total",
        "created_at",
    )
    search_fields = (
        "order_code",
        "customer_firstname",
        "customer_lastname",
        "phone_number",
        "history__processed_by__username__istartswith",
        "history__processed_by__username__icontains",
        "history__processed_by__username__iendswith",
    )
    list_filter = (
        "order_status",
        "created_at",
        "consumer_sentiment__sentiment",
        "history__user_type",
        HasSentimentFilter,
        HasVideoProofsFilter,
    )
    date_hierarchy = "created_at"
    inlines = [
        OrderEntryInline,
        OrderHistoryInline,
        ConsumerSentimentInline,
        DeliveryProofInline,
    ]

    fieldsets = (
        (
            "Основное",
            {
                "fields": (
                    "order_code",
                    ("customer_firstname", "customer_lastname"),
                    "phone_number",
                    "order_status",
                    "total_price",
                )
            },
        ),
        (
            "Служебное",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                    # "raw_json",
                )
            },
        ),
    )
    readonly_fields = ("created_at", "updated_at", "raw_json")

    def customer_full_name(self, obj):
        return f"{obj.customer_firstname} {obj.customer_lastname}".strip()

    customer_full_name.short_description = "Покупатель"

    def show_merchant_users(self, obj):
        user = obj.get_last_user_in_history()
        return f"[{user.user_type}] {user.user_name} {user.user_phone}"

    show_merchant_users.short_description = "Доставил"

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.annotate(  # points_sum появится на каждом объекте
            points_sum=Coalesce(
                Sum("scores__points"),  # суммируем связанные CourierScore
                Value(Decimal("0.00")),  # если нет баллов → 0
            )
        )

    # ②  Выводим значение в колонке
    def points_total(self, obj):
        return obj.points_sum  # Decimal со 2 знаками после запятой

    points_total.short_description = "Баллы"
    points_total.admin_order_field = "points_sum"


@admin.register(OrderEntry)
class OrderEntryAdmin(admin.ModelAdmin):
    list_display = ("order", "name", "quantity", "base_price", "total_price")


@admin.register(OrderHistory)
class OrderHistoryAdmin(admin.ModelAdmin):
    list_display = ("order", "action", "user_type", "create_date", "user_name")
    list_filter = ("user_type", "action", "create_date", "user_name")
    search_fields = ("order__order_code", "user_name", "user_email")
    readonly_fields = ("raw_data",)


@admin.register(ConsumerSentiment)
class ConsumerSentimentAdmin(admin.ModelAdmin):
    date_hierarchy = "created_at"
    list_display = ("order", "courier", "sentiment", "comment", "created_at")
    search_fields = ("order__order_code", "courier__username", "courier__phone_number")
    list_filter = ("sentiment", "created_at")
    exclude = ("rating",)


@admin.register(DeliveryProof)
class DeliveryProofAdmin(admin.ModelAdmin):
    list_display = ("order", "courier", "video", "uploaded_at")
    search_fields = ("order__order_code", "courier__username", "courier__phone_number")


@admin.register(OrderPreparation)
class OrderPreparationAdmin(admin.ModelAdmin):
    pass
