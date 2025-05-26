from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin

from app_accounts.models import CourierScore, TelegramGroup

User = get_user_model()


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    """
    Класс админки для нашей кастомной модели пользователя.
    Наследуемся от стандартного UserAdmin, чтобы унаследовать
    функции управления паролем, группами и т.д.
    """

    # Если вы добавили поле phone_number, то его нужно
    # указать в fieldsets, list_display и т.д.
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        (
            "Personal info",
            {
                "fields": (
                    "first_name",
                    "last_name",
                    "email",
                    "phone_number",  # <-- кастомное поле
                    "chat_id",  # <-- кастомное поле
                    "city",  # <-- кастомное поле
                )
            },
        ),
        (
            "Permissions",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )

    # какие поля показывать в списке пользователей
    list_display = [
        "username",
        "email",
        "phone_number",
        "chat_id",
        "is_staff",
        "is_superuser",
    ]

    # по каким полям делать поиск
    search_fields = ["username", "email", "phone_number"]


@admin.register(CourierScore)
class CourierScoreAdmin(admin.ModelAdmin):
    list_display = ("user", "order", "points", "created_at")
    search_fields = ("user__username", "order__order_code")
    list_filter = ("points", "created_at")


@admin.register(TelegramGroup)
class TelegramGroupAdmin(admin.ModelAdmin):
    list_display = ("title", "chat_id", "group_type", "created_at")
    search_fields = ("title", "chat_id", "group_type")
    list_filter = ("group_type", "created_at")
