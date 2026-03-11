from django.urls import path
from . import views

app_name = "tickets"

urlpatterns = [
    path("", views.ticket_list, name="list"),
    path("create/", views.ticket_create, name="create"),
    path("<str:ticket_id>/", views.ticket_detail, name="detail"),
    path("<str:ticket_id>/assign/", views.assign_ticket, name="assign"),
    path("<str:ticket_id>/status/", views.update_status, name="update_status"),
    path("<str:ticket_id>/escalate/", views.escalate_ticket, name="escalate_ticket"),
    path("<str:ticket_id>/mark-resolved/", views.customer_mark_resolved, name="customer_mark_resolved"),
    path("<str:ticket_id>/feedback/", views.submit_feedback, name="submit_feedback"),
    path("<str:ticket_id>/reopen/", views.reopen_ticket, name="reopen"),
]

