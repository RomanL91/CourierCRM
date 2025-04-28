from django.contrib import admin


class RelatedExistsFilter(admin.SimpleListFilter):
    """
    Базовый фильтр «есть / нет» для связанных объектов.
    Задать в наследнике:
      • title            – заголовок в сайдбаре
      • parameter_name   – параметр в URL (?some=yes|no)
      • field_name       – имя relation-поля в модели (строка)
      • yes_label / no_label – человекочитаемые подписи
    """

    title = ""
    parameter_name = ""
    field_name = ""

    yes_label = "Есть"
    no_label = "Нет"

    def lookups(self, request, model_admin):
        return (("yes", self.yes_label), ("no", self.no_label))

    def queryset(self, request, queryset):
        match self.value():
            case "yes":
                return queryset.filter(**{f"{self.field_name}__isnull": False})
            case "no":
                return queryset.filter(**{f"{self.field_name}__isnull": True})
            case _:
                return queryset


class HasSentimentFilter(RelatedExistsFilter):
    title = "Оценка ИНП"
    parameter_name = "has_sent"
    field_name = "consumer_sentiment"
    yes_label = "Есть оценка"
    no_label = "Нет оценки"


class HasVideoProofsFilter(RelatedExistsFilter):
    title = "Видео отчёт"
    parameter_name = "has_video"
    field_name = "delivery_proof"
    yes_label = "Есть видео отчёт"
    no_label = "Нет видео отчёта"
