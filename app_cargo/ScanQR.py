from decimal import Decimal

from app_accounts.models import User

from app_cargo.models import (
    WorkType,
    Cargo,
    City,
    WorkUnit,
    WorkDistribution,
    CargoCostRate,
)


def calculate_score(city: City, mass: float, volume: float) -> Decimal:
    try:
        rate = CargoCostRate.objects.get(city=city)
    except CargoCostRate.DoesNotExist:
        raise ValueError(f"Для города '{city.name}' не найдены тарифы CargoCostRate")

    mass_score = Decimal(mass) * rate.cost_per_mass_unit
    volume_score = Decimal(volume) * rate.cost_per_volume_unit
    return mass_score + volume_score


def scan_qr(employee: User, qr_data: dict):
    mass = qr_data.get("m", 0)
    volume = qr_data.get("v", 0)
    id_external = qr_data["id"]

    # Определение города сканирования
    employee_city = employee.city

    city_from = qr_data.get("city_from")
    city_to = qr_data.get("city_to")

    # Определение, работа это погрузка или разгрузка
    if city_from and city_from == employee_city.name:
        work_type = WorkType.LOAD
    elif city_to and city_to == employee_city.name:
        work_type = WorkType.UNLOAD
    elif city_from and city_from == employee_city.name:
        work_type = WorkType.LOAD
    else:
        raise ValueError(
            f"Сотрудник {employee!r} из {employee_city!r} не задействован в маршруте {city_from or '—'} → {city_to or '—'}"
        )

    # Создаём груз, если ещё не существует
    cargo, _ = Cargo.objects.get_or_create(
        id_external=id_external,
        defaults={
            "mass": mass,
            "volume": volume,
            "city_from": City.objects.filter(name=city_from).first(),
            "city_to": City.objects.filter(name=city_to).first(),
        },
    )

    # Ищем или создаём WorkUnit
    work_unit, created = WorkUnit.objects.get_or_create(
        cargo=cargo,
        city=employee_city,
        work_type=work_type,
        defaults={
            "mass_units": mass,
            "volume_units": volume,
            "total_score": calculate_score(employee_city, mass, volume),
        },
    )

    # Проверяем — участвовал ли сотрудник
    if WorkDistribution.objects.filter(work_unit=work_unit, employee=employee).exists():
        return  # ничего не меняем, он уже учтён

    # Добавляем нового участника
    WorkDistribution.objects.create(
        work_unit=work_unit, employee=employee, score_share=0
    )

    # Перерасчёт долей
    participants = work_unit.distributions.all()
    new_share = work_unit.total_score / participants.count()

    for dist in participants:
        dist.score_share = new_share
        dist.save()
