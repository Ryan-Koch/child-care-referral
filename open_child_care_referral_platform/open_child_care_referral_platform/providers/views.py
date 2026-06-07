from django.views.generic import ListView

from open_child_care_referral_platform.providers.models import Provider


class ProviderListView(ListView):
    model = Provider
    context_object_name = "providers"
    paginate_by = 24
    ordering = ["provider_name"]


provider_list_view = ProviderListView.as_view()
