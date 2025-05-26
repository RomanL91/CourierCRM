from django.db import models

from django.conf import settings


class City(models.Model):
    name = models.CharField(
        max_length=100,
        unique=True,
        verbose_name="Город",
        help_text="Город (уникальное значение)",
    )

    class Meta:
        verbose_name = "Город"
        verbose_name_plural = "Города"

    def __str__(self):
        return self.name


class CargoCostRate(models.Model):
    city = models.OneToOneField(
        City,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        unique=True,  # чтобы не было больше 1 тарифа на город
        related_name="cost_rate",
        help_text="Выбирите Город для которого нжно установить тариф",
        verbose_name="Город",
    )
    cost_per_mass_unit = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Укажите сколько баллов за 1 тонну в этом Городе",
        verbose_name="Стоимость за 1 т",
    )
    cost_per_volume_unit = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Укажите сколько баллов за 1 м³ в этом Городе",
        verbose_name="Стоимость за 1 м³",
    )

    class Meta:
        verbose_name = "Ставка стоимости груза"
        verbose_name_plural = "Ставки стоимости грузов"

    def __str__(self):
        return f"{self.city.name}: {self.cost_per_mass_unit} бал/т, {self.cost_per_volume_unit} бал/м³"


class Cargo(models.Model):
    id_external = models.BigIntegerField(
        unique=True,
        verbose_name="Внешний ИД",
        help_text="ID из другой системы с уникальным значеним",
    )
    mass = models.FloatField(
        null=True,
        blank=True,
        verbose_name="Масса",
        help_text="Показывает какая масса этого грузза",
    )
    volume = models.FloatField(
        null=True,
        blank=True,
        verbose_name="Объём",
        help_text="Показывает какой объём этого груза",
    )
    city_from = models.ForeignKey(
        City,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="cargoes_sent",
        verbose_name="Город отправки",
        help_text="Город отправления, может быть пустым если от постовщика",
    )
    city_to = models.ForeignKey(
        City,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="cargoes_received",
        verbose_name="Город приема",
        help_text="Город, который ожидает прием товара, так же может быть пустым, если отгржаем оптовику",
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Дата/Время",
        help_text="Дата и Время создания записи о грузе",
    )

    class Meta:
        verbose_name = "Груз"
        verbose_name_plural = "Грузы"

    def __str__(self):
        return f"Cargo {self.id_external}"


class WorkType(models.TextChoices):
    LOAD = "load", "Погрузка"
    UNLOAD = "unload", "Разгрузка"


class WorkUnit(models.Model):
    cargo = models.ForeignKey(
        Cargo,
        on_delete=models.CASCADE,
        related_name="work_units",
        verbose_name="Груз",
        help_text="Груз с которым производятся раюоты",
    )
    city = models.ForeignKey(
        City,
        on_delete=models.PROTECT,
        verbose_name="Город",
        help_text="Город в котором производятся работы",
    )
    work_type = models.CharField(
        max_length=10,
        choices=WorkType.choices,
        verbose_name="Тип работы",
        help_text="Тип производимой работы",
    )
    mass_units = models.FloatField(default=0, verbose_name="Масса")
    volume_units = models.FloatField(default=0, verbose_name="Объём")
    total_score = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name="Сумма баллов",
        help_text="Суммарное количество баллов за работу по этому Грузу в этом Городе",
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Дата/Время",
        help_text="Дата и Время создания записи",
    )

    class Meta:
        unique_together = ("cargo", "city", "work_type")
        verbose_name = "Работа с грузом"
        verbose_name_plural = "Работы с грузами"

    def __str__(self):
        return f"{self.get_work_type_display()} – {self.city.name} – {self.total_score} баллов"


class WorkDistribution(models.Model):
    work_unit = models.ForeignKey(
        WorkUnit,
        on_delete=models.CASCADE,
        related_name="distributions",
        verbose_name="Работа с грузом",
        help_text="Указывает на конкретную работу с/над грузом",
    )
    employee = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, verbose_name="Струдик"
    )
    score_share = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name="Баллы",
        help_text="Баллы, которые получил сотрудник выполняя работу с грузом",
    )
    scanned_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Дата/Время",
        help_text="Дата и Время создания записи",
    )

    class Meta:
        unique_together = ("work_unit", "employee")
        verbose_name = "Распределение работы и баллов сотрудника"
        verbose_name_plural = "Распределение работ и баллы сотрудников"

    def __str__(self):
        return f"{self.employee.username} → {self.score_share} баллов"
