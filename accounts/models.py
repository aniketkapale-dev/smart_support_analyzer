from django.conf import settings
from django.db import models


class Team(models.Model):
    name = models.CharField(max_length=150, unique=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.name


class UserApproval(models.Model):
    """Tracks self-registration and approval by manager/admin."""

    class RequestedRole(models.TextChoices):
        CUSTOMER = "customer", "Customer"
        AGENT = "agent", "Support Agent"
        MANAGER = "manager", "Support Manager"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="approval",
    )
    requested_role = models.CharField(
        max_length=20,
        choices=RequestedRole.choices,
    )
    is_approved = models.BooleanField(default=False)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_registrations",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    rejected_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.user.username} ({self.requested_role}) — {'Approved' if self.is_approved else 'Pending'}"


class CustomerProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    organization = models.CharField(max_length=255, blank=True)
    phone_number = models.CharField(max_length=32, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"CustomerProfile({self.user.username})"


class AgentProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    # Legacy single-team field (kept for backwards compatibility)
    team = models.ForeignKey(
        Team,
        on_delete=models.SET_NULL,
        related_name="agents_legacy",
        null=True,
        blank=True,
    )
    # New: allow an agent to belong to multiple teams
    teams = models.ManyToManyField(
        Team,
        related_name="agent_members",
        blank=True,
    )
    phone_number = models.CharField(max_length=32, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"AgentProfile({self.user.username})"

