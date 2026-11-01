from django.contrib import admin

from .models import PlanFeature


@admin.register(PlanFeature)
class PlanFeatureAdmin(admin.ModelAdmin):
    """
    What each plan includes, to read (WhatsApp plan phase 3, decision 2). Read-only: a mistaken click
    here would switch a feature on or off for every organization on that plan, so rows change only
    through data migrations, with a test.
    """

    list_display = ("plan", "feature")
    list_filter = ("plan", "feature")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
