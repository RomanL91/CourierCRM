from django.urls import path
from .views import DeliveryProofUploadView

urlpatterns = [
    path("api/upload_video/", DeliveryProofUploadView.as_view(), name="upload-video"),
]
