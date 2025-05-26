from django.contrib import admin

from app_cargo.models import City, CargoCostRate, Cargo, WorkUnit, WorkDistribution


@admin.register(City)
class CityAdmin(admin.ModelAdmin):
    pass


@admin.register(CargoCostRate)
class CargoCostRateAdmin(admin.ModelAdmin):
    pass


@admin.register(Cargo)
class CargoAdmin(admin.ModelAdmin):
    readonly_fields = ("created_at",)


@admin.register(WorkUnit)
class WorkUnitAdmin(admin.ModelAdmin):
    readonly_fields = ("created_at",)


@admin.register(WorkDistribution)
class WorkDistributionAdmin(admin.ModelAdmin):
    readonly_fields = ("scanned_at",)
