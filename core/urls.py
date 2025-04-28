from django.contrib import admin
from django.urls import path, include
from django.conf.urls.static import static
from django.conf import settings

from app_orders.urls import urlpatterns as urlpatterns_video

urlpatterns = (
    [
        path("admin/", admin.site.urls),
        path("v1/", include(urlpatterns_video)),
    ]
    + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    + static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
)

admin.site.site_header = "ЦРМ Курьера (альфа)"
admin.site.index_title = "ЦРМ Курьера (альфа)"  # default: "Site administration"
admin.site.site_title = "ЦРМ Курьера (альфа)"  # default: "Django site admin"
admin.site.site_url = None
# admin.site.disable_action('delete_selected')
