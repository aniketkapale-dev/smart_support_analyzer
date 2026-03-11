from django.urls import path
from . import views

app_name = "dashboard"

urlpatterns = [
    path("", views.home, name="home"),
    path("admin/users/", views.admin_users_roles, name="admin_users_roles"),
    path("admin/users/<int:user_id>/edit/", views.admin_user_edit, name="admin_user_edit"),
    path("admin/approve-managers/", views.admin_approve_managers, name="admin_approve_managers"),
    path("admin/ticket-config/", views.admin_ticket_config, name="admin_ticket_config"),
    path("admin/channels-integrations/", views.admin_channels_integrations, name="admin_channels_integrations"),
    path("admin/knowledge-base/", views.admin_kb_articles, name="admin_kb_articles"),
    path("admin/knowledge-base/<int:article_id>/edit/", views.admin_kb_article_edit, name="admin_kb_article_edit"),
    path("manager/teams/", views.manager_teams, name="manager_teams"),
    path("manager/teams/manage/", views.manager_teams_manage, name="manager_teams_manage"),
    path("approve-registrations/", views.manager_approve_registrations, name="manager_approve_registrations"),
]

