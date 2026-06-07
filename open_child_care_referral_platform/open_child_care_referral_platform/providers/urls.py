from django.urls import path

from .views import provider_detail_view
from .views import provider_list_view

app_name = "providers"
urlpatterns = [
    path("", view=provider_list_view, name="list"),
    path("<int:pk>/", view=provider_detail_view, name="detail"),
]
