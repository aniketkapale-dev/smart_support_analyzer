from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db.models import Count, Q

from accounts.models import AgentProfile
from notifications.models import Notification

from .models import AuditLog, Ticket, TicketAssignmentRule

User = get_user_model()


def _least_loaded_agent_queryset(base_qs):
    """
    Order agents by fewest active assigned tickets (open/in progress/etc.).
    """
    active_statuses = [
        Ticket.Status.OPEN,
        Ticket.Status.ASSIGNED,
        Ticket.Status.IN_PROGRESS,
        Ticket.Status.WAITING_FOR_CUSTOMER,
        Ticket.Status.REOPENED,
    ]
    return (
        base_qs.annotate(
            active_assigned=Count(
                "assigned_tickets",
                filter=Q(assigned_tickets__status__in=active_statuses),
            )
        )
        .order_by("active_assigned", "username")
    )


def _pick_agent_for_rule(rule: TicketAssignmentRule) -> User | None:
    if rule.strategy == TicketAssignmentRule.Strategy.DIRECT_AGENT:
        return rule.assign_to_agent

    if rule.strategy == TicketAssignmentRule.Strategy.TEAM_LEAST_LOADED and rule.assign_to_team_id:
        team_agent_ids = AgentProfile.objects.filter(team_id=rule.assign_to_team_id).values_list(
            "user_id", flat=True
        )
        qs = User.objects.filter(id__in=team_agent_ids, groups__name="Support Agent").distinct()
        return _least_loaded_agent_queryset(qs).first()

    if rule.strategy == TicketAssignmentRule.Strategy.GLOBAL_LEAST_LOADED:
        qs = User.objects.filter(groups__name="Support Agent").distinct()
        return _least_loaded_agent_queryset(qs).first()

    return None


def auto_assign_ticket(ticket: Ticket) -> User | None:
    """
    Auto-assign a newly created ticket based on rules.

    - If a matching active rule exists, use it.
    - Otherwise: assign to the global least-loaded agent.
    - If no agent exists, leave unassigned.
    """
    if ticket.assigned_agent_id:
        return ticket.assigned_agent

    rules = TicketAssignmentRule.objects.filter(is_active=True).select_related(
        "match_category", "assign_to_agent", "assign_to_team"
    )
    # If there are no active rules, keep ticket unassigned for manager review.
    if not rules.exists():
        return None
    for rule in rules:
        if rule.match_category_id and rule.match_category_id != ticket.category_id:
            continue
        if rule.match_priority and rule.match_priority != ticket.priority:
            continue
        agent = _pick_agent_for_rule(rule)
        if agent:
            _apply_assignment(ticket, agent, action="Auto-assigned ticket")
            return agent

    # Fallback: least-loaded agent
    agent = _pick_agent_for_rule(
        TicketAssignmentRule(strategy=TicketAssignmentRule.Strategy.GLOBAL_LEAST_LOADED)
    )
    if agent:
        _apply_assignment(ticket, agent, action="Auto-assigned ticket (fallback)")
        return agent

    return None


def _apply_assignment(ticket: Ticket, agent: User, action: str) -> None:
    from_status = ticket.status
    ticket.assigned_agent = agent
    ticket.status = Ticket.Status.ASSIGNED
    ticket.save(update_fields=["assigned_agent", "status"])

    AuditLog.objects.create(
        ticket=ticket,
        action=action,
        performed_by=None,
        from_status=from_status,
        to_status=Ticket.Status.ASSIGNED,
    )

    Notification.objects.create(
        recipient=agent,
        ticket=ticket,
        type=Notification.Type.ASSIGNED,
        message=f"New ticket assigned: {ticket.ticket_id}",
    )

