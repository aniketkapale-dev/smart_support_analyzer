from django.conf import settings
from django.db import models


class TicketCategory(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)

    def __str__(self) -> str:
        return self.name


class TicketTag(models.Model):
    name = models.CharField(max_length=50, unique=True)

    def __str__(self) -> str:
        return self.name


class TicketAssignmentRule(models.Model):
    """
    Automation rules for assigning new tickets to agents.

    Rules are evaluated by ascending priority_order; first match wins.
    """

    class Strategy(models.TextChoices):
        DIRECT_AGENT = "direct_agent", "Direct agent"
        TEAM_LEAST_LOADED = "team_least_loaded", "Team least-loaded agent"
        GLOBAL_LEAST_LOADED = "global_least_loaded", "Global least-loaded agent"

    name = models.CharField(max_length=150, unique=True)
    is_active = models.BooleanField(default=True)
    priority_order = models.PositiveIntegerField(default=100)

    match_category = models.ForeignKey(
        TicketCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assignment_rules",
    )
    match_priority = models.CharField(
        max_length=20,
        choices=[
            ("low", "Low"),
            ("medium", "Medium"),
            ("high", "High"),
            ("urgent", "Urgent"),
        ],
        null=True,
        blank=True,
    )

    strategy = models.CharField(
        max_length=40,
        choices=Strategy.choices,
        default=Strategy.GLOBAL_LEAST_LOADED,
    )
    assign_to_agent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ticket_assignment_rules",
    )
    assign_to_team = models.ForeignKey(
        "accounts.Team",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ticket_assignment_rules",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["priority_order", "id"]

    def __str__(self) -> str:
        return f"{self.name} ({'active' if self.is_active else 'inactive'})"


class Ticket(models.Model):
    class Priority(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"
        URGENT = "urgent", "Urgent"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        ASSIGNED = "assigned", "Assigned"
        IN_PROGRESS = "in_progress", "In Progress"
        WAITING_FOR_CUSTOMER = "waiting_for_customer", "Pending (Waiting for Customer)"
        ESCALATED = "escalated", "Escalated to Manager"
        RESOLVED = "resolved", "Resolved"
        CLOSED = "closed", "Closed"
        REOPENED = "reopened", "Reopened"

    id = models.BigAutoField(primary_key=True)
    ticket_id = models.CharField(max_length=20, unique=True, blank=True)
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="customer_tickets",
    )
    subject = models.CharField(max_length=255)
    description = models.TextField()
    category = models.ForeignKey(
        TicketCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tickets",
    )
    sentiment = models.CharField(max_length=30, blank=True)
    ai_suggested_category = models.CharField(max_length=100, blank=True)
    ai_suggested_priority = models.CharField(
        max_length=20,
        choices=Priority.choices,
        blank=True,
    )
    priority = models.CharField(
        max_length=20,
        choices=Priority.choices,
        default=Priority.MEDIUM,
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.OPEN,
    )
    assigned_agent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_tickets",
    )
    tags = models.ManyToManyField(TicketTag, blank=True, related_name="tickets")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.ticket_id} - {self.subject}"

    def save(self, *args, **kwargs):
        if not self.ticket_id:
            last = Ticket.objects.order_by("-id").first()
            last_number = 0
            if last and last.ticket_id and last.ticket_id.startswith("TKT-"):
                try:
                    last_number = int(last.ticket_id.split("-")[1])
                except (IndexError, ValueError):
                    last_number = last.id
            self.ticket_id = f"TKT-{last_number + 1:04d}"
        super().save(*args, **kwargs)


class TicketStatusTransition(models.Model):
    """Configurable workflow transitions for ticket statuses."""

    from_status = models.CharField(max_length=20, choices=Ticket.Status.choices)
    to_status = models.CharField(max_length=20, choices=Ticket.Status.choices)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("from_status", "to_status")]
        ordering = ["from_status", "to_status", "id"]

    def __str__(self) -> str:
        return f"{self.from_status} → {self.to_status}"


class TicketReply(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="replies")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ticket_replies",
    )
    message = models.TextField()
    is_internal = models.BooleanField(
        default=False,
        help_text="Internal note visible only to agents and managers.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"Reply to {self.ticket.ticket_id} by {self.author or 'System'}"


class TicketAttachment(models.Model):
    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.CASCADE,
        related_name="attachments",
    )
    reply = models.ForeignKey(
        "TicketReply",
        on_delete=models.CASCADE,
        related_name="attachments",
        null=True,
        blank=True,
    )
    file = models.FileField(upload_to="ticket_attachments/")
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ticket_attachments",
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"Attachment for {self.ticket.ticket_id}"


class TicketFeedback(models.Model):
    """Customer satisfaction (CSAT) feedback after ticket resolution."""

    ticket = models.OneToOneField(
        Ticket,
        on_delete=models.CASCADE,
        related_name="feedback",
    )
    rating = models.PositiveSmallIntegerField(
        help_text="1-5 stars",
        choices=[(i, str(i)) for i in range(1, 6)],
    )
    comment = models.TextField(blank=True)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ticket_feedbacks",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"Feedback for {self.ticket.ticket_id}: {self.rating} stars"


class AuditLog(models.Model):
    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.CASCADE,
        related_name="audit_logs",
    )
    action = models.CharField(max_length=255)
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ticket_audit_entries",
    )
    from_status = models.CharField(max_length=20, blank=True)
    to_status = models.CharField(max_length=20, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"AuditLog({self.ticket.ticket_id} - {self.action})"


class KnowledgeBaseArticle(models.Model):
    title = models.CharField(max_length=255)
    content = models.TextField()
    category = models.ForeignKey(
        TicketCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="articles",
    )
    tags = models.ManyToManyField(TicketTag, blank=True, related_name="articles")
    is_published = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_articles",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return self.title


class ServiceLevelPolicy(models.Model):
    """
    High-level SLA configuration for response and resolution times per priority.
    """

    name = models.CharField(max_length=150, unique=True)
    description = models.TextField(blank=True)
    priority = models.CharField(
        max_length=20,
        choices=Ticket.Priority.choices,
        default=Ticket.Priority.MEDIUM,
    )
    target_first_response_minutes = models.PositiveIntegerField(default=60)
    target_resolution_minutes = models.PositiveIntegerField(default=480)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.name


class SupportChannel(models.Model):
    """
    Channels through which tickets can enter the system (email, chat, phone, etc.).
    """

    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self) -> str:
        return self.name


class IntegrationConfig(models.Model):
    """
    Simple representation of external integrations (Slack, Jira, etc.).
    Configuration details can be stored as JSON text for now.
    """

    PROVIDER_CHOICES = [
        ("slack", "Slack"),
        ("email", "Email"),
        ("jira", "Jira"),
        ("other", "Other"),
    ]

    name = models.CharField(max_length=150, unique=True)
    provider = models.CharField(max_length=50, choices=PROVIDER_CHOICES)
    is_enabled = models.BooleanField(default=False)
    config_json = models.JSONField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.name

