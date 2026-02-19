from django.urls import path

from .views import upload_vcf

urlpatterns = [
    path("", upload_vcf, name="upload_vcf"),
]
