from django.conf import settings
from django.db import models

from tickets.models import Ticket


class Notification(models.Model):
    class Type(models.TextChoices):
        NEW_TICKET = "new_ticket", "New ticket"
        ASSIGNED = "assigned", "Ticket assigned"
        UPDATED = "updated", "Ticket updated"
        RESOLVED = "resolved", "Ticket resolved"

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.CASCADE,
        related_name="notifications",
        null=True,
        blank=True,
    )
    type = models.CharField(max_length=32, choices=Type.choices)
    message = models.CharField(max_length=255)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Notification({self.recipient}, {self.type})"

