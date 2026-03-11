from datetime import timedelta

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group
from django.shortcuts import get_object_or_404
from django.db.models import Avg, Case, Count, DurationField, ExpressionWrapper, F, IntegerField, Q, Value, When
from django.db.models.functions import TruncDate
from django.http import HttpResponseForbidden
from django.shortcuts import redirect, render
from django.utils import timezone
from django.core.paginator import Paginator

from accounts.models import UserApproval
from accounts.models import AgentProfile, CustomerProfile, Team
from notifications.models import Notification
from tickets.models import (
    IntegrationConfig,
    KnowledgeBaseArticle,
    ServiceLevelPolicy,
    SupportChannel,
    Ticket,
    TicketCategory,
    TicketFeedback,
    TicketTag,
    TicketStatusTransition,
)

User = get_user_model()


def _is_admin(user: User) -> bool:
    return user.is_superuser or user.groups.filter(name="Admin").exists()


def _is_manager(user: User) -> bool:
    return _is_admin(user) or user.groups.filter(name="Support Manager").exists()


def _is_agent(user: User) -> bool:
    return user.groups.filter(name="Support Agent").exists()


def _is_customer(user: User) -> bool:
    return user.groups.filter(name="Customer").exists()


@login_required
def home(request):
    user = request.user

    # Scope tickets based on role
    if _is_manager(user):
        scope_label = "All queues"
        tickets_qs = Ticket.objects.all()
    elif _is_agent(user):
        scope_label = "Your assigned tickets"
        tickets_qs = Ticket.objects.filter(assigned_agent=user)
    else:
        scope_label = "Your tickets"
        tickets_qs = Ticket.objects.filter(customer=user)

    total_tickets = tickets_qs.count()
    open_tickets = tickets_qs.filter(status=Ticket.Status.OPEN).count()
    closed_tickets = tickets_qs.filter(
        status__in=[Ticket.Status.RESOLVED, Ticket.Status.CLOSED]
    ).count()
    high_priority_tickets = tickets_qs.filter(
        priority__in=[Ticket.Priority.HIGH, Ticket.Priority.URGENT]
    ).count()

    # Average resolution time based on created_at -> updated_at for resolved/closed tickets
    resolved_qs = tickets_qs.filter(
        status__in=[Ticket.Status.RESOLVED, Ticket.Status.CLOSED]
    )
    avg_resolution_hours = None
    if resolved_qs.exists():
        duration_expr = ExpressionWrapper(
            F("updated_at") - F("created_at"),
            output_field=DurationField(),
        )
        agg = resolved_qs.annotate(duration=duration_expr).aggregate(
            avg_duration=Avg("duration")
        )
        avg_duration: timedelta | None = agg["avg_duration"]
        if avg_duration:
            avg_resolution_hours = round(avg_duration.total_seconds() / 3600, 1)

    # Category distribution
    category_distribution = (
        tickets_qs.values("category__name")
        .annotate(count=Count("id"))
        .order_by("-count")
    )

    # Sentiment distribution
    sentiment_distribution = (
        tickets_qs.values("sentiment")
        .annotate(count=Count("id"))
        .order_by("-count")
    )

    recent_tickets = (
        tickets_qs.select_related("customer", "assigned_agent", "category")
        .order_by("-created_at")[:5]
    )

    notifications = (
        Notification.objects.filter(recipient=user)
        .select_related("ticket")
        .order_by("-created_at")[:8]
    )

    # Agent workspace metrics (for Agent Dashboard)
    agent_metrics = None
    if _is_agent(user):
        today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        my_tickets_qs = Ticket.objects.filter(assigned_agent=user)
        unassigned_tickets = Ticket.objects.filter(
            assigned_agent__isnull=True,
        ).exclude(
            status__in=[Ticket.Status.RESOLVED, Ticket.Status.CLOSED],
        ).count()
        urgent_tickets = Ticket.objects.filter(
            assigned_agent=user,
            priority__in=[Ticket.Priority.HIGH, Ticket.Priority.URGENT],
        ).exclude(
            status__in=[Ticket.Status.RESOLVED, Ticket.Status.CLOSED],
        ).count()
        # Also count urgent unassigned so agent knows what needs attention
        urgent_unassigned = Ticket.objects.filter(
            assigned_agent__isnull=True,
            priority__in=[Ticket.Priority.HIGH, Ticket.Priority.URGENT],
        ).exclude(
            status__in=[Ticket.Status.RESOLVED, Ticket.Status.CLOSED],
        ).count()
        resolved_today = my_tickets_qs.filter(
            status__in=[Ticket.Status.RESOLVED, Ticket.Status.CLOSED],
            updated_at__gte=today_start,
        ).count()
        agent_metrics = {
            "my_tickets": my_tickets_qs.exclude(
                status__in=[Ticket.Status.RESOLVED, Ticket.Status.CLOSED],
            ).count(),
            "unassigned_tickets": unassigned_tickets,
            "urgent_tickets": urgent_tickets + urgent_unassigned,
            "resolved_today": resolved_today,
        }

    # Manager queue metrics (global view)
    manager_metrics = None
    manager_queue = None
    if _is_manager(user):
        active_qs = Ticket.objects.exclude(status__in=[Ticket.Status.RESOLVED, Ticket.Status.CLOSED])
        unassigned_count = active_qs.filter(assigned_agent__isnull=True).count()
        high_priority_count = active_qs.filter(
            priority__in=[Ticket.Priority.HIGH, Ticket.Priority.URGENT]
        ).count()
        negative_sentiment_count = active_qs.filter(sentiment="negative").count()

        # SLA risk: tickets close to resolution target based on active SLA policies
        now = timezone.now()
        sla_threshold_q = Q()
        active_policies = ServiceLevelPolicy.objects.filter(is_active=True)
        minutes_by_priority = {p.priority: p.target_resolution_minutes for p in active_policies}
        # default fallbacks if no policy exists
        default_minutes = {
            Ticket.Priority.LOW: 1440,
            Ticket.Priority.MEDIUM: 480,
            Ticket.Priority.HIGH: 240,
            Ticket.Priority.URGENT: 120,
        }
        for pr in [Ticket.Priority.LOW, Ticket.Priority.MEDIUM, Ticket.Priority.HIGH, Ticket.Priority.URGENT]:
            target = minutes_by_priority.get(pr) or default_minutes.get(pr, 480)
            # at risk when elapsed >= 80% of target
            threshold_time = now - timedelta(minutes=int(target * 0.8))
            sla_threshold_q |= Q(priority=pr, created_at__lte=threshold_time)
        sla_risk_count = active_qs.filter(sla_threshold_q).count()

        manager_metrics = {
            "unassigned": unassigned_count,
            "high_priority": high_priority_count,
            "negative_sentiment": negative_sentiment_count,
            "sla_risk": sla_risk_count,
        }

        today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        resolved_today_total = Ticket.objects.filter(
            status__in=[Ticket.Status.RESOLVED, Ticket.Status.CLOSED],
            updated_at__gte=today_start,
        ).count()

        backlog_size = active_qs.count()
        negative_pct = 0.0
        if backlog_size:
            negative_pct = round((negative_sentiment_count / backlog_size) * 100, 1)

        # Tickets per agent (backlog + resolved today)
        agents_qs = User.objects.filter(groups__name="Support Agent").distinct()
        per_agent = (
            agents_qs.annotate(
                backlog=Count(
                    "assigned_tickets",
                    filter=Q(
                        assigned_tickets__status__in=[
                            Ticket.Status.OPEN,
                            Ticket.Status.ASSIGNED,
                            Ticket.Status.IN_PROGRESS,
                            Ticket.Status.WAITING_FOR_CUSTOMER,
                            Ticket.Status.ESCALATED,
                            Ticket.Status.REOPENED,
                        ]
                    ),
                ),
                resolved_today=Count(
                    "assigned_tickets",
                    filter=Q(
                        assigned_tickets__status__in=[Ticket.Status.RESOLVED, Ticket.Status.CLOSED],
                        assigned_tickets__updated_at__gte=today_start,
                    ),
                ),
            )
            .order_by("-backlog", "-resolved_today", "username")
        )

        # Queue sample: show top tickets to review (high priority first, then oldest)
        priority_order = Case(
            When(priority=Ticket.Priority.URGENT, then=Value(0)),
            When(priority=Ticket.Priority.HIGH, then=Value(1)),
            When(priority=Ticket.Priority.MEDIUM, then=Value(2)),
            When(priority=Ticket.Priority.LOW, then=Value(3)),
            default=Value(2),
            output_field=IntegerField(),
        )
        manager_queue = (
            active_qs.select_related("customer", "assigned_agent", "category")
            .annotate(priority_order=priority_order)
            .order_by("priority_order", "created_at")[:12]
        )

    # Admin system health metrics
    admin_metrics = None
    system_notifications = None
    admin_analytics = None
    if _is_admin(user):
        total_users = User.objects.count()
        agents_count = User.objects.filter(groups__name="Support Agent", is_active=True).distinct().count()
        managers_count = User.objects.filter(groups__name="Support Manager", is_active=True).distinct().count()
        open_tickets_global = Ticket.objects.filter(status=Ticket.Status.OPEN).count()
        admin_metrics = {
            "total_users": total_users,
            "agents": agents_count,
            "managers": managers_count,
            "open_tickets": open_tickets_global,
        }
        system_notifications = (
            Notification.objects.select_related("ticket", "recipient")
            .order_by("-created_at")[:10]
        )

        # Admin analytics (system-wide)
        window_days = 30
        start_day = timezone.localdate() - timedelta(days=window_days - 1)
        daily = (
            Ticket.objects.filter(created_at__date__gte=start_day)
            .annotate(day=TruncDate("created_at"))
            .values("day")
            .annotate(count=Count("id"))
            .order_by("day")
        )
        daily_map = {row["day"]: row["count"] for row in daily}
        trend = []
        max_count = max(daily_map.values()) if daily_map else 0
        for i in range(window_days):
            day = start_day + timedelta(days=i)
            c = int(daily_map.get(day, 0))
            pct = int(round((c / max_count) * 100)) if max_count else 0
            trend.append({"day": day, "label": day.strftime("%b %d"), "count": c, "pct": pct})

        csat = TicketFeedback.objects.aggregate(avg=Avg("rating"), total=Count("id"))
        csat_avg = csat["avg"]
        csat_total = int(csat["total"] or 0)
        csat_dist_raw = (
            TicketFeedback.objects.values("rating")
            .annotate(count=Count("id"))
            .order_by("rating")
        )
        csat_dist_map = {int(r["rating"]): int(r["count"]) for r in csat_dist_raw}
        csat_max = max(csat_dist_map.values()) if csat_dist_map else 0
        csat_dist = []
        for rating in range(1, 6):
            c = int(csat_dist_map.get(rating, 0))
            pct = int(round((c / csat_max) * 100)) if csat_max else 0
            csat_dist.append({"rating": rating, "count": c, "pct": pct})

        admin_analytics = {
            "total_tickets": Ticket.objects.count(),
            "avg_resolution_hours": avg_resolution_hours,
            "ticket_volume_trend": trend,
            "csat_avg": round(float(csat_avg), 2) if csat_avg is not None else None,
            "csat_total": csat_total,
            "csat_dist": csat_dist,
        }

    context = {
        "scope_label": scope_label,
        "is_manager": _is_manager(user),
        "is_agent": _is_agent(user),
        "is_customer": _is_customer(user),
        "is_admin": _is_admin(user),
        "ticket_stats": {
            "total": total_tickets,
            "open": open_tickets,
            "closed": closed_tickets,
            "high_priority": high_priority_tickets,
            "avg_resolution_hours": avg_resolution_hours,
        },
        "category_distribution": category_distribution,
        "sentiment_distribution": sentiment_distribution,
        "recent_tickets": recent_tickets,
        "notifications": notifications,
        "agent_metrics": agent_metrics,
        "manager_metrics": manager_metrics,
        "manager_queue": manager_queue,
        "manager_analytics": {
            "resolved_today_total": resolved_today_total,
            "avg_resolution_hours": avg_resolution_hours,
            "negative_pct": negative_pct,
            "backlog_size": backlog_size,
        }
        if _is_manager(user)
        else None,
        "tickets_per_agent": per_agent if _is_manager(user) else None,
        "admin_metrics": admin_metrics,
        "system_notifications": system_notifications,
        "admin_analytics": admin_analytics,
    }
    return render(request, "dashboard/home.html", context)


ROLE_CHOICES = [
    ("customer", "Customer"),
    ("agent", "Support Agent"),
    ("manager", "Support Manager"),
    ("admin", "Administrator"),
]


class AdminUserCreateForm(forms.Form):
    username = forms.CharField(max_length=150)
    email = forms.EmailField(required=False)
    password1 = forms.CharField(widget=forms.PasswordInput)
    password2 = forms.CharField(widget=forms.PasswordInput)
    role = forms.ChoiceField(choices=ROLE_CHOICES)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("password1") != cleaned.get("password2"):
            self.add_error("password2", "Passwords do not match.")
        return cleaned


class AdminUserUpdateForm(forms.Form):
    email = forms.EmailField(required=False)
    is_active = forms.BooleanField(required=False)
    role = forms.ChoiceField(choices=ROLE_CHOICES)


class CustomerProfileForm(forms.ModelForm):
    class Meta:
        model = CustomerProfile
        fields = ["organization", "phone_number"]


class AgentProfileForm(forms.ModelForm):
    class Meta:
        model = AgentProfile
        fields = ["teams", "phone_number"]


def _ensure_core_groups() -> None:
    for name in ["Admin", "Support Manager", "Support Agent", "Customer"]:
        Group.objects.get_or_create(name=name)


def _set_primary_role(user: User, role_key: str) -> None:
    _ensure_core_groups()
    role_to_group = {
        "admin": "Admin",
        "manager": "Support Manager",
        "agent": "Support Agent",
        "customer": "Customer",
    }
    # Remove from all core groups
    user.groups.remove(
        *Group.objects.filter(name__in=role_to_group.values())
    )
    group_name = role_to_group.get(role_key)
    if group_name:
        group = Group.objects.get(name=group_name)
        user.groups.add(group)

    # Set staff/superuser flags based on role
    if role_key == "admin":
        user.is_staff = True
        user.is_superuser = True
    elif role_key in ("manager", "agent"):
        user.is_staff = True
        user.is_superuser = False
    else:  # customer
        user.is_staff = False
        user.is_superuser = False
    user.save()


def _get_role_key_for_user(user: User) -> str:
    if _is_admin(user):
        return "admin"
    if user.groups.filter(name="Support Manager").exists():
        return "manager"
    if user.groups.filter(name="Support Agent").exists():
        return "agent"
    if user.groups.filter(name="Customer").exists():
        return "customer"
    return "customer"


@login_required
def admin_users_roles(request):
    if not _is_admin(request.user):
        return HttpResponseForbidden("Admins only.")

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "create":
            form = AdminUserCreateForm(request.POST)
            if form.is_valid():
                username = form.cleaned_data["username"]
                email = form.cleaned_data.get("email") or ""
                password = form.cleaned_data["password1"]
                role = form.cleaned_data["role"]
                user = User.objects.create_user(username=username, email=email, password=password)
                _set_primary_role(user, role)
                return redirect("dashboard:admin_users_roles")
        elif action == "update_role":
            user_id = request.POST.get("user_id")
            role = request.POST.get("role")
            if user_id and role in dict(ROLE_CHOICES):
                try:
                    user = User.objects.get(id=user_id)
                    _set_primary_role(user, role)
                except User.DoesNotExist:
                    pass
            return redirect("dashboard:admin_users_roles")
        elif action == "delete":
            user_id = request.POST.get("user_id")
            if user_id and str(request.user.id) != str(user_id):
                try:
                    User.objects.get(id=user_id).delete()
                except User.DoesNotExist:
                    pass
            return redirect("dashboard:admin_users_roles")
        elif action == "toggle_active":
            user_id = request.POST.get("user_id")
            if user_id and str(request.user.id) != str(user_id):
                try:
                    u = User.objects.get(id=user_id)
                    u.is_active = not u.is_active
                    u.save(update_fields=["is_active"])
                except User.DoesNotExist:
                    pass
            return redirect("dashboard:admin_users_roles")
    else:
        form = AdminUserCreateForm()

    users_qs = User.objects.all().prefetch_related("groups").order_by("username")
    for u in users_qs:
        u.primary_role = _get_role_key_for_user(u)

    paginator = Paginator(users_qs, 20)
    page_number = request.GET.get("page")
    users_page = paginator.get_page(page_number)

    return render(
        request,
        "dashboard/admin_users_roles.html",
        {
            "users": users_page,
            "users_page": users_page,
            "create_form": form,
            "role_choices": ROLE_CHOICES,
        },
    )


@login_required
def admin_user_edit(request, user_id: int):
    if not _is_admin(request.user):
        return HttpResponseForbidden("Admins only.")

    target_user = get_object_or_404(User, id=user_id)
    role_key = _get_role_key_for_user(target_user)

    try:
        customer_profile = CustomerProfile.objects.get(user=target_user)
    except CustomerProfile.DoesNotExist:
        customer_profile = None
    try:
        agent_profile = AgentProfile.objects.get(user=target_user)
    except AgentProfile.DoesNotExist:
        agent_profile = None

    if request.method == "POST":
        update_form = AdminUserUpdateForm(request.POST)
        customer_form = CustomerProfileForm(request.POST, instance=customer_profile) if role_key == "customer" else None
        agent_form = AgentProfileForm(request.POST, instance=agent_profile) if role_key == "agent" else None

        if update_form.is_valid():
            target_user.email = update_form.cleaned_data.get("email") or ""
            target_user.is_active = bool(update_form.cleaned_data.get("is_active"))
            target_user.save(update_fields=["email", "is_active"])

            new_role = update_form.cleaned_data.get("role")
            if new_role in dict(ROLE_CHOICES) and new_role != role_key:
                _set_primary_role(target_user, new_role)
                role_key = new_role

            if role_key == "customer":
                if customer_form and customer_form.is_valid():
                    obj = customer_form.save(commit=False)
                    obj.user = target_user
                    obj.save()
            elif role_key == "agent":
                if agent_form and agent_form.is_valid():
                    obj = agent_form.save(commit=False)
                    obj.user = target_user
                    obj.save()

            return redirect("dashboard:admin_users_roles")
    else:
        update_form = AdminUserUpdateForm(
            initial={
                "email": target_user.email,
                "is_active": target_user.is_active,
                "role": role_key,
            }
        )
        customer_form = CustomerProfileForm(instance=customer_profile) if role_key == "customer" else None
        agent_form = AgentProfileForm(instance=agent_profile) if role_key == "agent" else None

    return render(
        request,
        "dashboard/admin_user_edit.html",
        {
            "target_user": target_user,
            "role_key": role_key,
            "update_form": update_form,
            "customer_form": customer_form,
            "agent_form": agent_form,
            "teams": Team.objects.all().order_by("name"),
        },
    )


@login_required
def manager_approve_registrations(request):
    """Support Manager (or Admin) approves pending Customer and Support Agent registrations."""
    if not _is_manager(request.user):
        return HttpResponseForbidden("Support Manager or Admin access required.")

    pending = (
        UserApproval.objects.filter(
            is_approved=False,
            rejected_at__isnull=True,
            requested_role__in=[UserApproval.RequestedRole.CUSTOMER, UserApproval.RequestedRole.AGENT],
        )
        .select_related("user")
        .order_by("created_at")
    )

    if request.method == "POST":
        action = request.POST.get("action")
        approval_id = request.POST.get("approval_id")
        if action == "approve" and approval_id:
            try:
                approval = UserApproval.objects.get(
                    id=approval_id,
                    is_approved=False,
                    rejected_at__isnull=True,
                    requested_role__in=[UserApproval.RequestedRole.CUSTOMER, UserApproval.RequestedRole.AGENT],
                )
                approval.is_approved = True
                approval.approved_by = request.user
                approval.approved_at = timezone.now()
                approval.save()
            except UserApproval.DoesNotExist:
                pass
            return redirect("dashboard:manager_approve_registrations")
        if action == "reject" and approval_id:
            try:
                approval = UserApproval.objects.get(
                    id=approval_id,
                    is_approved=False,
                    rejected_at__isnull=True,
                    requested_role__in=[UserApproval.RequestedRole.CUSTOMER, UserApproval.RequestedRole.AGENT],
                )
                approval.rejected_at = timezone.now()
                approval.save()
            except UserApproval.DoesNotExist:
                pass
            return redirect("dashboard:manager_approve_registrations")

    return render(
        request,
        "dashboard/manager_approve_registrations.html",
        {"pending": pending},
    )


@login_required
def admin_approve_managers(request):
    """Admin approves pending Support Manager self-registrations."""
    if not _is_admin(request.user):
        return HttpResponseForbidden("Admin access required.")

    pending = (
        UserApproval.objects.filter(
            is_approved=False,
            rejected_at__isnull=True,
            requested_role=UserApproval.RequestedRole.MANAGER,
        )
        .select_related("user")
        .order_by("created_at")
    )

    if request.method == "POST":
        action = request.POST.get("action")
        approval_id = request.POST.get("approval_id")
        if action == "approve" and approval_id:
            try:
                approval = UserApproval.objects.get(
                    id=approval_id,
                    is_approved=False,
                    rejected_at__isnull=True,
                    requested_role=UserApproval.RequestedRole.MANAGER,
                )
                approval.is_approved = True
                approval.approved_by = request.user
                approval.approved_at = timezone.now()
                approval.save()

                # Ensure role & permissions are correctly applied on approval
                _set_primary_role(approval.user, "manager")

                Notification.objects.create(
                    recipient=approval.user,
                    ticket=None,
                    type=Notification.Type.UPDATED,
                    message="Your Support Manager account has been approved. You can now sign in.",
                )
            except UserApproval.DoesNotExist:
                pass
            return redirect("dashboard:admin_approve_managers")
        if action == "reject" and approval_id:
            try:
                approval = UserApproval.objects.get(
                    id=approval_id,
                    is_approved=False,
                    rejected_at__isnull=True,
                    requested_role=UserApproval.RequestedRole.MANAGER,
                )
                approval.rejected_at = timezone.now()
                approval.save()

                Notification.objects.create(
                    recipient=approval.user,
                    ticket=None,
                    type=Notification.Type.UPDATED,
                    message="Your Support Manager registration was rejected. Please contact support.",
                )
            except UserApproval.DoesNotExist:
                pass
            return redirect("dashboard:admin_approve_managers")

    return render(
        request,
        "dashboard/admin_approve_managers.html",
        {"pending": pending},
    )


class ServiceLevelPolicyForm(forms.ModelForm):
    class Meta:
        model = ServiceLevelPolicy
        fields = [
            "name",
            "description",
            "priority",
            "target_first_response_minutes",
            "target_resolution_minutes",
            "is_active",
        ]


class SupportChannelForm(forms.ModelForm):
    class Meta:
        model = SupportChannel
        fields = ["name", "slug", "description", "is_active"]


class IntegrationConfigForm(forms.ModelForm):
    class Meta:
        model = IntegrationConfig
        fields = ["name", "provider", "is_enabled", "config_json"]


class TicketStatusTransitionForm(forms.ModelForm):
    class Meta:
        model = TicketStatusTransition
        fields = ["from_status", "to_status", "is_active"]


class KnowledgeBaseArticleForm(forms.Form):
    title = forms.CharField(max_length=255)
    content = forms.CharField(widget=forms.Textarea)
    category = forms.ModelChoiceField(queryset=TicketCategory.objects.all().order_by("name"), required=False)
    tags = forms.CharField(
        required=False,
        help_text="Comma-separated (e.g., login, password)",
    )
    is_published = forms.BooleanField(required=False, initial=False)

    def clean_tags(self) -> list[str]:
        raw = (self.cleaned_data.get("tags") or "").strip()
        if not raw:
            return []
        parts = [p.strip().lower() for p in raw.split(",")]
        return [p for p in parts if p]


def _set_article_tags(article: KnowledgeBaseArticle, tag_names: list[str]) -> None:
    tags = []
    for name in tag_names:
        tag, _ = TicketTag.objects.get_or_create(name=name)
        tags.append(tag)
    article.tags.set(tags)


@login_required
def admin_ticket_config(request):
    if not _is_admin(request.user):
        return HttpResponseForbidden("Admins only.")

    if request.method == "POST" and request.POST.get("form_type") == "category":
        name = request.POST.get("name", "").strip()
        description = request.POST.get("description", "").strip()
        if name:
            TicketCategory.objects.get_or_create(
                name=name, defaults={"description": description}
            )
        return redirect("dashboard:admin_ticket_config")

    if request.method == "POST" and request.POST.get("form_type") == "category_update":
        category_id = (request.POST.get("category_id") or "").strip()
        name = request.POST.get("name", "").strip()
        description = request.POST.get("description", "").strip()
        if category_id.isdigit() and name:
            try:
                c = TicketCategory.objects.get(id=int(category_id))
                c.name = name
                c.description = description
                c.save(update_fields=["name", "description"])
            except TicketCategory.DoesNotExist:
                pass
        return redirect("dashboard:admin_ticket_config")

    if request.method == "POST" and request.POST.get("form_type") == "category_delete":
        category_id = (request.POST.get("category_id") or "").strip()
        if category_id.isdigit():
            try:
                TicketCategory.objects.get(id=int(category_id)).delete()
            except TicketCategory.DoesNotExist:
                pass
        return redirect("dashboard:admin_ticket_config")

    sla_form = ServiceLevelPolicyForm(request.POST or None)
    if request.method == "POST" and request.POST.get("form_type") == "sla" and sla_form.is_valid():
        sla_obj = sla_form.save()
        # Keep a single active policy per priority (simple & predictable)
        if sla_obj.is_active:
            ServiceLevelPolicy.objects.filter(priority=sla_obj.priority).exclude(id=sla_obj.id).update(is_active=False)
        return redirect("dashboard:admin_ticket_config")

    if request.method == "POST" and request.POST.get("form_type") == "sla_toggle":
        sla_id = (request.POST.get("sla_id") or "").strip()
        if sla_id.isdigit():
            try:
                p = ServiceLevelPolicy.objects.get(id=int(sla_id))
                p.is_active = not p.is_active
                p.save(update_fields=["is_active"])
                if p.is_active:
                    ServiceLevelPolicy.objects.filter(priority=p.priority).exclude(id=p.id).update(is_active=False)
            except ServiceLevelPolicy.DoesNotExist:
                pass
        return redirect("dashboard:admin_ticket_config")

    if request.method == "POST" and request.POST.get("form_type") == "sla_delete":
        sla_id = (request.POST.get("sla_id") or "").strip()
        if sla_id.isdigit():
            try:
                ServiceLevelPolicy.objects.get(id=int(sla_id)).delete()
            except ServiceLevelPolicy.DoesNotExist:
                pass
        return redirect("dashboard:admin_ticket_config")

    if request.method == "POST" and request.POST.get("form_type") == "sla_preset":
        preset = (request.POST.get("preset") or "").strip()
        presets = {
            "standard": [
                # respond within 1h / 4h / 24h; resolution defaults remain configurable
                (Ticket.Priority.HIGH, 60),
                (Ticket.Priority.URGENT, 60),
                (Ticket.Priority.MEDIUM, 240),
                (Ticket.Priority.LOW, 1440),
            ]
        }
        if preset in presets:
            for pr, first_resp in presets[preset]:
                obj, _ = ServiceLevelPolicy.objects.get_or_create(
                    name=f"Default SLA ({pr})",
                    defaults={
                        "description": "Preset SLA targets.",
                        "priority": pr,
                        "target_first_response_minutes": first_resp,
                        "target_resolution_minutes": 480 if pr == Ticket.Priority.MEDIUM else (1440 if pr == Ticket.Priority.LOW else 240),
                        "is_active": True,
                    },
                )
                obj.priority = pr
                obj.target_first_response_minutes = first_resp
                obj.is_active = True
                obj.save(update_fields=["priority", "target_first_response_minutes", "is_active"])
                ServiceLevelPolicy.objects.filter(priority=pr).exclude(id=obj.id).update(is_active=False)
        return redirect("dashboard:admin_ticket_config")

    transition_form = TicketStatusTransitionForm(request.POST or None)
    if (
        request.method == "POST"
        and request.POST.get("form_type") == "transition"
        and transition_form.is_valid()
    ):
        try:
            transition_form.save()
        except Exception:
            pass
        return redirect("dashboard:admin_ticket_config")

    if request.method == "POST" and request.POST.get("form_type") == "transition_delete":
        transition_id = (request.POST.get("transition_id") or "").strip()
        if transition_id.isdigit():
            try:
                TicketStatusTransition.objects.get(id=int(transition_id)).delete()
            except TicketStatusTransition.DoesNotExist:
                pass
        return redirect("dashboard:admin_ticket_config")

    categories = TicketCategory.objects.all().order_by("name")
    sla_policies = ServiceLevelPolicy.objects.all().order_by("-created_at")
    transitions = TicketStatusTransition.objects.all().order_by("from_status", "to_status")

    return render(
        request,
        "dashboard/admin_ticket_config.html",
        {
            "categories": categories,
            "sla_policies": sla_policies,
            "sla_form": sla_form,
            "transitions": transitions,
            "transition_form": transition_form,
            "priority_choices": Ticket.Priority.choices,
        },
    )


@login_required
def admin_channels_integrations(request):
    if not _is_admin(request.user):
        return HttpResponseForbidden("Admins only.")

    channel_form = SupportChannelForm(request.POST or None, prefix="ch")
    if request.method == "POST" and request.POST.get("form_type") == "channel" and channel_form.is_valid():
        channel_form.save()
        return redirect("dashboard:admin_channels_integrations")

    if request.method == "POST" and request.POST.get("form_type") == "channel_toggle":
        channel_id = (request.POST.get("channel_id") or "").strip()
        if channel_id.isdigit():
            try:
                ch = SupportChannel.objects.get(id=int(channel_id))
                ch.is_active = not ch.is_active
                ch.save(update_fields=["is_active"])
            except SupportChannel.DoesNotExist:
                pass
        return redirect("dashboard:admin_channels_integrations")

    if request.method == "POST" and request.POST.get("form_type") == "channel_delete":
        channel_id = (request.POST.get("channel_id") or "").strip()
        if channel_id.isdigit():
            try:
                SupportChannel.objects.get(id=int(channel_id)).delete()
            except SupportChannel.DoesNotExist:
                pass
        return redirect("dashboard:admin_channels_integrations")

    if request.method == "POST" and request.POST.get("form_type") == "channel_preset":
        # Seed common channels: Web form / Email / Live chat
        presets = [
            ("Web form", "web-form", "Tickets created from the website request form."),
            ("Email", "email", "Tickets created from support email."),
            ("Live chat", "live-chat", "Tickets created from live chat sessions."),
        ]
        for name, slug, desc in presets:
            SupportChannel.objects.get_or_create(
                slug=slug,
                defaults={"name": name, "description": desc, "is_active": True},
            )
        return redirect("dashboard:admin_channels_integrations")

    integration_form = IntegrationConfigForm(request.POST or None, prefix="int")
    if (
        request.method == "POST"
        and request.POST.get("form_type") == "integration"
        and integration_form.is_valid()
    ):
        integration_form.save()
        return redirect("dashboard:admin_channels_integrations")

    channels = SupportChannel.objects.all().order_by("name")
    integrations = IntegrationConfig.objects.all().order_by("-created_at")

    return render(
        request,
        "dashboard/admin_channels_integrations.html",
        {
            "channels": channels,
            "integrations": integrations,
            "channel_form": channel_form,
            "integration_form": integration_form,
        },
    )


@login_required
def admin_kb_articles(request):
    if not _is_admin(request.user):
        return HttpResponseForbidden("Admins only.")

    if request.method == "POST":
        form_type = request.POST.get("form_type")
        if form_type == "create":
            form = KnowledgeBaseArticleForm(request.POST)
            if form.is_valid():
                article = KnowledgeBaseArticle.objects.create(
                    title=form.cleaned_data["title"],
                    content=form.cleaned_data["content"],
                    category=form.cleaned_data.get("category"),
                    is_published=bool(form.cleaned_data.get("is_published")),
                    created_by=request.user,
                )
                _set_article_tags(article, form.cleaned_data["tags"])
                return redirect("dashboard:admin_kb_articles")
        elif form_type == "toggle_publish":
            article_id = (request.POST.get("article_id") or "").strip()
            if article_id.isdigit():
                try:
                    a = KnowledgeBaseArticle.objects.get(id=int(article_id))
                    a.is_published = not a.is_published
                    a.save(update_fields=["is_published"])
                except KnowledgeBaseArticle.DoesNotExist:
                    pass
            return redirect("dashboard:admin_kb_articles")
        elif form_type == "delete":
            article_id = (request.POST.get("article_id") or "").strip()
            if article_id.isdigit():
                try:
                    KnowledgeBaseArticle.objects.get(id=int(article_id)).delete()
                except KnowledgeBaseArticle.DoesNotExist:
                    pass
            return redirect("dashboard:admin_kb_articles")
    else:
        form = KnowledgeBaseArticleForm()

    articles = (
        KnowledgeBaseArticle.objects.select_related("category", "created_by")
        .prefetch_related("tags")
        .order_by("-created_at")[:200]
    )
    return render(
        request,
        "dashboard/admin_kb_articles.html",
        {"articles": articles, "form": form},
    )


@login_required
def admin_kb_article_edit(request, article_id: int):
    if not _is_admin(request.user):
        return HttpResponseForbidden("Admins only.")

    article = get_object_or_404(KnowledgeBaseArticle, id=article_id)
    initial = {
        "title": article.title,
        "content": article.content,
        "category": article.category_id,
        "tags": ", ".join([t.name for t in article.tags.all().order_by("name")]),
        "is_published": article.is_published,
    }

    if request.method == "POST":
        form = KnowledgeBaseArticleForm(request.POST)
        if form.is_valid():
            article.title = form.cleaned_data["title"]
            article.content = form.cleaned_data["content"]
            article.category = form.cleaned_data.get("category")
            article.is_published = bool(form.cleaned_data.get("is_published"))
            article.save(update_fields=["title", "content", "category", "is_published", "updated_at"])
            _set_article_tags(article, form.cleaned_data["tags"])
            return redirect("dashboard:admin_kb_articles")
    else:
        form = KnowledgeBaseArticleForm(initial=initial)

    return render(
        request,
        "dashboard/admin_kb_article_edit.html",
        {"article": article, "form": form},
    )


@login_required
def manager_teams(request):
    """
    Support Managers/Admins manage teams and assign existing agents to teams.
    """
    if not _is_manager(request.user):
        return HttpResponseForbidden("Support Manager or Admin access required.")

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "create_team":
            name = (request.POST.get("name") or "").strip()
            description = (request.POST.get("description") or "").strip()
            if name:
                Team.objects.get_or_create(name=name, defaults={"description": description})
            return redirect("dashboard:manager_teams")

    return render(request, "dashboard/manager_teams.html", {})


@login_required
def manager_teams_manage(request):
    """
    Detailed team management: view teams and assign/remove agents.
    """
    if not _is_manager(request.user):
        return HttpResponseForbidden("Support Manager or Admin access required.")

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "add_agent":
            team_id = (request.POST.get("team_id") or "").strip()
            agent_ids = request.POST.getlist("agent_ids")
            if team_id.isdigit() and agent_ids:
                try:
                    team = Team.objects.get(id=int(team_id))
                except Team.DoesNotExist:
                    team = None
                if team:
                    for aid in agent_ids:
                        if not aid.isdigit():
                            continue
                        profile, _ = AgentProfile.objects.get_or_create(user_id=int(aid))
                        profile.teams.add(team)
                        if profile.team is None:
                            profile.team = team
                            profile.save(update_fields=["team"])
            return redirect("dashboard:manager_teams_manage")

        if action == "remove_agent":
            profile_id = (request.POST.get("profile_id") or "").strip()
            team_id = (request.POST.get("team_id") or "").strip()
            if profile_id.isdigit() and team_id.isdigit():
                try:
                    profile = AgentProfile.objects.get(id=int(profile_id))
                    team = Team.objects.get(id=int(team_id))
                    profile.teams.remove(team)
                except (AgentProfile.DoesNotExist, Team.DoesNotExist):
                    pass
            return redirect("dashboard:manager_teams_manage")

    teams = Team.objects.all().order_by("name").prefetch_related("agent_members__user")
    agents = User.objects.filter(groups__name="Support Agent", is_active=True).order_by("username")

    return render(
        request,
        "dashboard/manager_teams_manage.html",
        {
            "teams": teams,
            "agents": agents,
        },
    )
