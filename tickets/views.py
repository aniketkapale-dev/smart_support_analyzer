from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.db.models import Case, IntegerField, Q, Value, When
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from django.core.paginator import Paginator

from ai_engine.services import analyze_ticket
from notifications.models import Notification
from .services import auto_assign_ticket
from .forms import TicketCreateForm, TicketReplyForm, TicketFeedbackForm
from .models import (
    AuditLog,
    KnowledgeBaseArticle,
    Ticket,
    TicketAttachment,
    TicketCategory,
    TicketFeedback,
    TicketReply,
    TicketStatusTransition,
)
from accounts.models import AgentProfile, CustomerProfile, Team

User = get_user_model()

KB_STOPWORDS = frozenset(
    {
        "how",
        "to",
        "my",
        "the",
        "a",
        "an",
        "is",
        "are",
        "can",
        "do",
        "does",
        "i",
        "me",
        "we",
        "what",
        "why",
        "when",
        "where",
        "which",
        "and",
        "or",
        "but",
        "if",
        "then",
        "that",
        "this",
        "it",
        "its",
        "in",
        "on",
        "at",
        "for",
        "with",
        "of",
        "as",
    }
)


def _kb_suggestions_for_ticket(ticket: Ticket, limit: int = 5):
    query_parts = [ticket.subject or ""]
    if ticket.category_id and ticket.category:
        query_parts.append(ticket.category.name)
    query = " ".join([p for p in query_parts if p]).strip()
    if not query:
        return KnowledgeBaseArticle.objects.none()

    words = [
        w.lower()
        for w in query.split()
        if len(w) >= 2 and w.lower() not in KB_STOPWORDS
    ]
    if not words:
        words = [query.lower()]

    q = Q()
    for word in words[:8]:
        q |= Q(title__icontains=word) | Q(content__icontains=word)

    return (
        KnowledgeBaseArticle.objects.filter(is_published=True)
        .filter(q)
        .select_related("category")
        .order_by("-created_at")[:limit]
    )


def _is_manager(user: User) -> bool:
    return user.is_superuser or user.groups.filter(name__in=["Admin", "Support Manager"]).exists()


def _is_agent(user: User) -> bool:
    return user.groups.filter(name="Support Agent").exists()


def _is_customer(user: User) -> bool:
    return user.groups.filter(name="Customer").exists()


def _priority_order_annotation():
    """Annotate queryset with priority_order so urgent/high appear first."""
    return Case(
        When(priority=Ticket.Priority.URGENT, then=Value(0)),
        When(priority=Ticket.Priority.HIGH, then=Value(1)),
        When(priority=Ticket.Priority.MEDIUM, then=Value(2)),
        When(priority=Ticket.Priority.LOW, then=Value(3)),
        default=Value(2),
        output_field=IntegerField(),
    )


@login_required
def ticket_list(request):
    qs = (
        Ticket.objects.select_related("customer", "assigned_agent", "category")
        .annotate(priority_order=_priority_order_annotation())
        .order_by("priority_order", "-created_at")
    )
    list_filter = None
    if _is_manager(request.user):
        # managers/admins see all tickets
        pass
    elif _is_agent(request.user):
        assigned = request.GET.get("assigned")
        priority = request.GET.get("priority")
        if assigned == "unassigned":
            qs = qs.filter(assigned_agent__isnull=True).exclude(
                status__in=[Ticket.Status.RESOLVED, Ticket.Status.CLOSED],
            )
            list_filter = "Unassigned"
        elif priority == "urgent":
            qs = qs.filter(
                priority__in=[Ticket.Priority.HIGH, Ticket.Priority.URGENT],
            ).exclude(
                status__in=[Ticket.Status.RESOLVED, Ticket.Status.CLOSED],
            )
            qs = qs.filter(Q(assigned_agent=request.user) | Q(assigned_agent__isnull=True))
            list_filter = "Urgent"
        else:
            qs = qs.filter(assigned_agent=request.user)
            list_filter = "My tickets"
    elif _is_customer(request.user):
        qs = qs.filter(customer=request.user)

    active_tickets = None
    history_tickets = None
    if _is_customer(request.user):
        active_tickets = qs.exclude(status__in=[Ticket.Status.RESOLVED, Ticket.Status.CLOSED])
        history_tickets = qs.filter(status__in=[Ticket.Status.RESOLVED, Ticket.Status.CLOSED])

    # Filters for agents and managers: status, priority, assigned_agent, category
    show_queue_filters = _is_agent(request.user) or _is_manager(request.user)
    filter_status = request.GET.get("status")
    filter_priority = request.GET.get("priority")
    filter_sentiment = request.GET.get("sentiment")
    filter_sla_risk = request.GET.get("sla_risk")
    filter_agent = request.GET.get("agent")
    filter_category = request.GET.get("category")
    filter_agent_id = None
    filter_category_id = None
    if show_queue_filters:
        filter_agent_id = int(filter_agent) if filter_agent and filter_agent.isdigit() else None
        filter_category_id = int(filter_category) if filter_category and filter_category.isdigit() else None
    if show_queue_filters:
        if filter_status:
            qs = qs.filter(status=filter_status)
        if filter_priority:
            if filter_priority == "high_urgent":
                qs = qs.filter(priority__in=[Ticket.Priority.HIGH, Ticket.Priority.URGENT])
            else:
                qs = qs.filter(priority=filter_priority)
        if filter_sentiment:
            qs = qs.filter(sentiment=filter_sentiment)
        if filter_sla_risk == "1":
            # Simple SLA risk approximation using created_at age by priority.
            now = timezone.now()
            thresholds = {
                Ticket.Priority.LOW: now - timedelta(minutes=int(1440 * 0.8)),
                Ticket.Priority.MEDIUM: now - timedelta(minutes=int(480 * 0.8)),
                Ticket.Priority.HIGH: now - timedelta(minutes=int(240 * 0.8)),
                Ticket.Priority.URGENT: now - timedelta(minutes=int(120 * 0.8)),
            }
            sla_q = Q()
            for pr, t in thresholds.items():
                sla_q |= Q(priority=pr, created_at__lte=t)
            qs = qs.exclude(status__in=[Ticket.Status.RESOLVED, Ticket.Status.CLOSED]).filter(sla_q)
        if filter_agent:
            if filter_agent == "unassigned":
                qs = qs.filter(assigned_agent__isnull=True)
            elif filter_agent_id:
                qs = qs.filter(assigned_agent_id=filter_agent_id)
        if filter_category and filter_category_id:
            qs = qs.filter(category_id=filter_category_id)

    agents = []
    categories = []
    if show_queue_filters:
        agents = User.objects.filter(groups__name="Support Agent").order_by("username")
        categories = TicketCategory.objects.all().order_by("name")

    tickets_page = None
    if not _is_customer(request.user):
        paginator = Paginator(qs, 25)
        page_number = request.GET.get("page")
        tickets_page = paginator.get_page(page_number)

    context = {
        "tickets": tickets_page or qs,
        "list_filter": list_filter,
        "is_manager": _is_manager(request.user),
        "is_agent": _is_agent(request.user),
        "is_customer": _is_customer(request.user),
        "active_tickets": active_tickets,
        "history_tickets": history_tickets,
        "show_queue_filters": show_queue_filters,
        "filter_status": filter_status,
        "filter_priority": filter_priority,
        "filter_sentiment": filter_sentiment,
        "filter_sla_risk": filter_sla_risk,
        "filter_agent": filter_agent,
        "filter_category": filter_category,
        "filter_agents": agents,
        "filter_categories": categories,
        "filter_agent_id": filter_agent_id,
        "filter_category_id": filter_category_id,
        "tickets_page": tickets_page,
    }
    return render(request, "tickets/list.html", context)


@login_required
def ticket_create(request):
    if request.method == "POST":
        form = TicketCreateForm(request.POST, request.FILES)
        if form.is_valid():
            ticket = form.save(commit=False)
            ticket.customer = request.user

            # Use customer's chosen category and priority from the form
            # AI only for sentiment
            text = f"{ticket.subject}\n\n{ticket.description}"
            result = analyze_ticket(text)
            ticket.sentiment = result.sentiment
            ticket.ai_suggested_category = (result.category or "").capitalize()
            if result.priority == "high":
                ticket.ai_suggested_priority = Ticket.Priority.HIGH
            elif result.priority == "medium":
                ticket.ai_suggested_priority = Ticket.Priority.MEDIUM
            else:
                ticket.ai_suggested_priority = Ticket.Priority.LOW

            ticket.save()
            form.save_m2m()

            AuditLog.objects.create(
                ticket=ticket,
                action="Created ticket",
                performed_by=request.user,
                from_status="",
                to_status=ticket.status,
            )

            for uploaded in request.FILES.getlist("attachments"):
                TicketAttachment.objects.create(
                    ticket=ticket,
                    file=uploaded,
                    uploaded_by=request.user,
                )

            # Auto assignment (rules/automation)
            auto_assign_ticket(ticket)

            # Notify managers
            for manager in User.objects.filter(
                groups__name__in=["Admin", "Support Manager"]
            ).distinct():
                Notification.objects.create(
                    recipient=manager,
                    ticket=ticket,
                    type=Notification.Type.NEW_TICKET,
                    message=f"New ticket {ticket.ticket_id} created by {request.user.username}",
                )

            # Confirmation notification for customer (dashboard 🔔)
            Notification.objects.create(
                recipient=request.user,
                ticket=ticket,
                type=Notification.Type.NEW_TICKET,
                message=f"Your ticket {ticket.ticket_id} has been submitted. Support team will respond shortly.",
            )

            detail_url = reverse("tickets:detail", kwargs={"ticket_id": ticket.ticket_id})
            return redirect(f"{detail_url}?submitted=1")
    else:
        form = TicketCreateForm()
    return render(request, "tickets/create.html", {"form": form})


@login_required
def ticket_detail(request, ticket_id: str):
    ticket = get_object_or_404(
        Ticket.objects.select_related("customer", "assigned_agent", "category"),
        ticket_id=ticket_id,
    )

    # Customers see only their own tickets; agents see only assigned tickets;
    # managers/admins can see all.
    if _is_customer(request.user) and ticket.customer_id != request.user.id:
        return HttpResponseForbidden("You do not have access to this ticket.")
    if _is_agent(request.user) and not _is_manager(request.user):
        if ticket.assigned_agent_id != request.user.id:
            return HttpResponseForbidden("You are not assigned to this ticket.")

    if request.method == "POST":
        reply_form = TicketReplyForm(request.POST)
        if reply_form.is_valid():
            reply = reply_form.save(commit=False)
            reply.ticket = ticket
            reply.author = request.user
            reply.save()

            for uploaded in request.FILES.getlist("attachments"):
                TicketAttachment.objects.create(
                    ticket=ticket,
                    reply=reply,
                    file=uploaded,
                    uploaded_by=request.user,
                )

            AuditLog.objects.create(
                ticket=ticket,
                action="Updated ticket (reply)",
                performed_by=request.user,
                from_status=ticket.status,
                to_status=ticket.status,
            )

            # Notify opposite party
            recipients = []
            if _is_customer(request.user):
                if ticket.assigned_agent:
                    recipients = [ticket.assigned_agent]
            else:
                recipients = [ticket.customer]

            for u in recipients:
                Notification.objects.create(
                    recipient=u,
                    ticket=ticket,
                    type=Notification.Type.UPDATED,
                    message=f"Ticket {ticket.ticket_id} has a new reply.",
                )

            return redirect("tickets:detail", ticket_id=ticket.ticket_id)
    else:
        reply_form = TicketReplyForm()

    replies_qs = (
        ticket.replies.select_related("author")
        .prefetch_related("attachments")
        .order_by("created_at")
    )
    # Customers should not see internal notes
    if _is_customer(request.user):
        replies_qs = replies_qs.filter(is_internal=False)

    # Attachments not tied to a reply (e.g. from ticket creation)
    attachments_no_reply = ticket.attachments.filter(reply__isnull=True)

    # Customer info & history (for agents/managers)
    customer_profile = None
    customer_past_tickets = []
    suggested_articles = []
    if _is_agent(request.user) or _is_manager(request.user):
        try:
            customer_profile = CustomerProfile.objects.get(user=ticket.customer)
        except CustomerProfile.DoesNotExist:
            customer_profile = None
        customer_past_tickets = (
            Ticket.objects.filter(customer=ticket.customer)
            .exclude(id=ticket.id)
            .select_related("category", "assigned_agent")
            .order_by("-created_at")[:8]
        )
        suggested_articles = list(_kb_suggestions_for_ticket(ticket, limit=5))

    team_agent_map = {}
    if _is_manager(request.user):
        # Map team_id -> list of agent user_ids for client-side filtering (supports multi-team)
        for team in Team.objects.all().order_by("id").prefetch_related("agent_members__user"):
            user_ids = [p.user_id for p in team.agent_members.all()]
            if user_ids:
                team_agent_map[str(team.id)] = user_ids

    # CSAT feedback (only for resolved/closed tickets)
    try:
        feedback = ticket.feedback
    except TicketFeedback.DoesNotExist:
        feedback = None
    feedback_form = None
    show_feedback_form = (
        _is_customer(request.user)
        and ticket.customer_id == request.user.id
        and ticket.status in (Ticket.Status.RESOLVED, Ticket.Status.CLOSED)
        and feedback is None
    )
    if show_feedback_form:
        feedback_form = TicketFeedbackForm()

    context = {
        "ticket": ticket,
        "replies": replies_qs,
        "attachments": ticket.attachments.all(),
        "attachments_no_reply": attachments_no_reply,
        "reply_form": reply_form,
        "is_manager": _is_manager(request.user),
        "is_agent": _is_agent(request.user),
        "is_customer": _is_customer(request.user),
        "agents": User.objects.filter(groups__name="Support Agent").order_by("username"),
        "teams": Team.objects.all().order_by("name"),
        "team_agent_map": team_agent_map,
        "show_submission_confirmation": request.GET.get("submitted") == "1",
        "feedback": feedback,
        "feedback_form": feedback_form,
        "show_feedback_form": show_feedback_form,
        "customer_profile": customer_profile,
        "customer_past_tickets": customer_past_tickets,
        "suggested_articles": suggested_articles,
    }
    return render(request, "tickets/detail.html", context)


@login_required
def assign_ticket(request, ticket_id: str):
    if not _is_manager(request.user):
        return HttpResponseForbidden("Only managers can assign tickets.")

    ticket = get_object_or_404(Ticket, ticket_id=ticket_id)
    team_id = (request.POST.get("team_id") or "").strip()
    agent_id = request.POST.get("agent_id")
    if agent_id:
        agent = get_object_or_404(User, id=agent_id, groups__name="Support Agent")
        if team_id and team_id.isdigit():
            # Ensure the agent is in the selected team (supports multi-team)
            if not AgentProfile.objects.filter(user=agent, teams__id=int(team_id)).exists():
                return HttpResponseForbidden("Selected agent is not part of the chosen team.")
        from_status = ticket.status
        ticket.assigned_agent = agent
        ticket.status = Ticket.Status.ASSIGNED
        ticket.save(update_fields=["assigned_agent", "status"])

        AuditLog.objects.create(
            ticket=ticket,
            action="Assigned ticket",
            performed_by=request.user,
            from_status=from_status,
            to_status=Ticket.Status.ASSIGNED,
        )

        Notification.objects.create(
            recipient=agent,
            ticket=ticket,
            type=Notification.Type.ASSIGNED,
            message=f"New ticket assigned: {ticket.ticket_id}",
        )

    return redirect("tickets:detail", ticket_id=ticket.ticket_id)


@login_required
def update_status(request, ticket_id: str):
    ticket = get_object_or_404(Ticket, ticket_id=ticket_id)

    if not _is_agent(request.user) and not _is_manager(request.user):
        return HttpResponseForbidden("Only agents or managers can change status.")
    # Agents may only change status on tickets assigned to them
    if _is_agent(request.user) and not _is_manager(request.user):
        if ticket.assigned_agent_id != request.user.id:
            return HttpResponseForbidden("You are not assigned to this ticket.")

    new_status = request.POST.get("status")
    allowed_statuses = {
        Ticket.Status.IN_PROGRESS,
        Ticket.Status.WAITING_FOR_CUSTOMER,
        Ticket.Status.ESCALATED,
        Ticket.Status.RESOLVED,
        Ticket.Status.CLOSED,
    }
    if new_status in allowed_statuses:
        from_status = ticket.status

        # Enforce configured workflow transitions if any exist
        if TicketStatusTransition.objects.exists():
            if not TicketStatusTransition.objects.filter(
                from_status=from_status, to_status=new_status, is_active=True
            ).exists():
                return HttpResponseForbidden(
                    "This status change is not allowed by the configured workflow."
                )

        ticket.status = new_status
        ticket.save(update_fields=["status"])
        AuditLog.objects.create(
            ticket=ticket,
            action="Updated status",
            performed_by=request.user,
            from_status=from_status,
            to_status=new_status,
        )

        if new_status == Ticket.Status.RESOLVED:
            Notification.objects.create(
                recipient=ticket.customer,
                ticket=ticket,
                type=Notification.Type.RESOLVED,
                message=f"Your ticket {ticket.ticket_id} has been resolved by support. You can view it in your tickets.",
            )
        elif new_status == Ticket.Status.CLOSED:
            Notification.objects.create(
                recipient=ticket.customer,
                ticket=ticket,
                type=Notification.Type.UPDATED,
                message=(
                    f"Your ticket {ticket.ticket_id} has been closed. "
                    "Please rate your support experience (CSAT) from the ticket page."
                ),
            )
        elif new_status == Ticket.Status.ESCALATED:
            # Notify managers/admins for escalation
            for manager in User.objects.filter(groups__name__in=["Admin", "Support Manager"]).distinct():
                Notification.objects.create(
                    recipient=manager,
                    ticket=ticket,
                    type=Notification.Type.UPDATED,
                    message=f"Ticket escalated: {ticket.ticket_id} ({ticket.subject})",
                )

    return redirect("tickets:detail", ticket_id=ticket.ticket_id)


@login_required
def escalate_ticket(request, ticket_id: str):
    """
    Agent escalates a ticket to Support Manager/Admin (policy/urgent/technical decision).
    Creates an internal note and switches status to ESCALATED.
    """
    ticket = get_object_or_404(Ticket, ticket_id=ticket_id)
    if not _is_agent(request.user) and not _is_manager(request.user):
        return HttpResponseForbidden("Only agents or managers can escalate tickets.")
    if _is_agent(request.user) and not _is_manager(request.user):
        if ticket.assigned_agent_id != request.user.id:
            return HttpResponseForbidden("You are not assigned to this ticket.")

    if request.method == "POST":
        reason = (request.POST.get("reason") or "").strip()
        from_status = ticket.status
        ticket.status = Ticket.Status.ESCALATED
        ticket.save(update_fields=["status"])

        AuditLog.objects.create(
            ticket=ticket,
            action="Escalated to manager",
            performed_by=request.user,
            from_status=from_status,
            to_status=Ticket.Status.ESCALATED,
        )

        if reason:
            TicketReply.objects.create(
                ticket=ticket,
                author=request.user,
                message=reason,
                is_internal=True,
            )

        for manager in User.objects.filter(groups__name__in=["Admin", "Support Manager"]).distinct():
            Notification.objects.create(
                recipient=manager,
                ticket=ticket,
                type=Notification.Type.UPDATED,
                message=f"Ticket escalated: {ticket.ticket_id} ({ticket.subject})",
            )

    return redirect("tickets:detail", ticket_id=ticket.ticket_id)


@login_required
def customer_mark_resolved(request, ticket_id: str):
    """Customer marks the ticket as resolved (issue fixed from their side)."""
    ticket = get_object_or_404(Ticket, ticket_id=ticket_id)
    if not _is_customer(request.user) or ticket.customer_id != request.user.id:
        return HttpResponseForbidden("Only the ticket owner can mark it resolved.")

    if request.method == "POST" and ticket.status not in {
        Ticket.Status.RESOLVED,
        Ticket.Status.CLOSED,
    }:
        from_status = ticket.status
        ticket.status = Ticket.Status.RESOLVED
        ticket.save(update_fields=["status"])
        AuditLog.objects.create(
            ticket=ticket,
            action="Customer marked as resolved",
            performed_by=request.user,
            from_status=from_status,
            to_status=Ticket.Status.RESOLVED,
        )
        if ticket.assigned_agent:
            Notification.objects.create(
                recipient=ticket.assigned_agent,
                ticket=ticket,
                type=Notification.Type.RESOLVED,
                message=f"Customer marked ticket {ticket.ticket_id} as resolved.",
            )

    return redirect("tickets:detail", ticket_id=ticket.ticket_id)


@login_required
def submit_feedback(request, ticket_id: str):
    """Customer submits CSAT feedback (star rating + optional comment) for a resolved ticket."""
    ticket = get_object_or_404(Ticket, ticket_id=ticket_id)
    if not _is_customer(request.user) or ticket.customer_id != request.user.id:
        return HttpResponseForbidden("Only the ticket owner can submit feedback.")
    if ticket.status not in (Ticket.Status.RESOLVED, Ticket.Status.CLOSED):
        return HttpResponseForbidden("Feedback is only for resolved or closed tickets.")
    try:
        ticket.feedback
        return HttpResponseForbidden("You have already submitted feedback for this ticket.")
    except TicketFeedback.DoesNotExist:
        pass

    if request.method == "POST":
        form = TicketFeedbackForm(request.POST)
        if form.is_valid():
            feedback = form.save(commit=False)
            feedback.ticket = ticket
            feedback.submitted_by = request.user
            feedback.save()
            return redirect("tickets:detail", ticket_id=ticket.ticket_id)
    return redirect("tickets:detail", ticket_id=ticket.ticket_id)


@login_required
def reopen_ticket(request, ticket_id: str):
    ticket = get_object_or_404(Ticket, ticket_id=ticket_id)

    if not _is_customer(request.user) or ticket.customer_id != request.user.id:
        return HttpResponseForbidden("Only the ticket owner can reopen it.")

    if ticket.status in {Ticket.Status.RESOLVED, Ticket.Status.CLOSED}:
        from_status = ticket.status
        ticket.status = Ticket.Status.REOPENED
        ticket.save(update_fields=["status"])
        AuditLog.objects.create(
            ticket=ticket,
            action="Reopened ticket",
            performed_by=request.user,
            from_status=from_status,
            to_status=Ticket.Status.REOPENED,
        )

    return redirect("tickets:detail", ticket_id=ticket.ticket_id)
