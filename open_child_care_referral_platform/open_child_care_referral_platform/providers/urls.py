from django.urls import path

from .views import provider_list_view

app_name = "providers"
urlpatterns = [
    path("", view=provider_list_view, name="list"),
]
