from django.contrib import admin

from .models import AgentProfile, CustomerProfile, Team, UserApproval


@admin.register(UserApproval)
class UserApprovalAdmin(admin.ModelAdmin):
    list_display = ("user", "requested_role", "is_approved", "approved_by", "approved_at", "created_at")
    list_filter = ("requested_role", "is_approved")
    search_fields = ("user__username", "user__email")
    raw_id_fields = ("user", "approved_by")


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ("name", "created_at")
    search_fields = ("name",)


@admin.register(AgentProfile)
class AgentProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "team", "phone_number", "created_at")
    list_filter = ("team",)
    search_fields = ("user__username", "user__email", "phone_number")


@admin.register(CustomerProfile)
class CustomerProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "organization", "phone_number", "created_at")
    search_fields = ("user__username", "user__email", "organization")

