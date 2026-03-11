from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group, User
from django.shortcuts import redirect, render
from django.urls import reverse

from .models import AgentProfile, CustomerProfile, UserApproval


def _get_role_redirect_url(user: User) -> str:
    if user.is_superuser:
        return reverse("dashboard:home")
    if user.groups.filter(name="Admin").exists():
        return reverse("dashboard:home")
    if user.groups.filter(name="Support Manager").exists():
        return reverse("dashboard:home")
    if user.groups.filter(name="Support Agent").exists():
        return reverse("dashboard:home")
    if user.groups.filter(name="Customer").exists():
        return reverse("tickets:list")
    return reverse("dashboard:home")


def landing_page(request):
    """Modern SaaS marketing landing page."""
    if request.method == "POST":
        email = (request.POST.get("email") or "").strip()
        if email:
            messages.success(request, "Thanks! We’ll reach out with setup guidance.")
        return redirect("accounts:landing")
    return render(request, "landing.html")


def role_select(request):
    """
    Get started: user chooses role, then proceeds to login or register.
    """
    return render(request, "accounts/role_select.html")


def login_view(request):
    selected_role = request.GET.get("role") or ""
    role_label = {
        "admin": "Admin",
        "manager": "Support Manager",
        "agent": "Support Agent",
        "customer": "Customer",
    }.get(selected_role, "")

    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")
        user = authenticate(request, username=username, password=password)
        if user is not None:
            try:
                approval = user.approval
            except UserApproval.DoesNotExist:
                approval = None
            if approval is not None:
                if approval.rejected_at:
                    messages.error(
                        request,
                        "Your account was not approved. Please contact support.",
                    )
                    return render(request, "accounts/login.html", {"role_label": role_label})
                if not approval.is_approved:
                    messages.warning(
                        request,
                        "Your account is pending approval. You will be able to sign in after a manager or admin approves your registration.",
                    )
                    return render(request, "accounts/login.html", {"role_label": role_label})

            # Enforce role-specific login when coming from get-started links
            if selected_role:
                has_role = False
                if selected_role == "admin":
                    has_role = user.is_superuser or user.groups.filter(name="Admin").exists()
                elif selected_role == "manager":
                    has_role = user.groups.filter(name="Support Manager").exists()
                elif selected_role == "agent":
                    has_role = user.groups.filter(name="Support Agent").exists()
                elif selected_role == "customer":
                    has_role = user.groups.filter(name="Customer").exists()

                if not has_role:
                    messages.error(
                        request,
                        f"This login is only for {role_label or 'the selected role'} accounts. "
                        "Please use the correct login option for your role.",
                    )
                    return render(request, "accounts/login.html", {"role_label": role_label})

            login(request, user)
            return redirect(_get_role_redirect_url(user))
        messages.error(request, "Invalid username or password.")
    return render(request, "accounts/login.html", {"role_label": role_label})


def logout_view(request):
    logout(request)
    messages.info(request, "You have been logged out.")
    return redirect("accounts:landing")


def _ensure_groups_exist() -> None:
    for name in ["Admin", "Support Manager", "Support Agent", "Customer"]:
        Group.objects.get_or_create(name=name)


REGISTER_ROLES = [
    ("customer", "Customer"),
    ("agent", "Support Agent"),
    ("manager", "Support Manager"),
]


def register_view(request):
    """
    Self-registration. Role from GET/POST 'role' (customer, agent, manager).
    User is created but must be approved before they can log in.
    Customer & Agent → approved by Support Manager. Support Manager → approved by Admin.
    """
    role_key = request.GET.get("role") or request.POST.get("role") or "customer"
    if role_key not in dict(REGISTER_ROLES):
        role_key = "customer"

    if request.method == "POST":
        username = request.POST.get("username")
        email = request.POST.get("email")
        password = request.POST.get("password")
        confirm_password = request.POST.get("confirm_password")

        if password != confirm_password:
            messages.error(request, "Passwords do not match.")
            return render(request, "accounts/register.html", {"role_key": role_key, "register_roles": REGISTER_ROLES})

        if User.objects.filter(username=username).exists():
            messages.error(request, "Username is already taken.")
            return render(request, "accounts/register.html", {"role_key": role_key, "register_roles": REGISTER_ROLES})

        _ensure_groups_exist()
        user = User.objects.create_user(username=username, email=email, password=password)

        group_name = {"customer": "Customer", "agent": "Support Agent", "manager": "Support Manager"}[role_key]
        group = Group.objects.get(name=group_name)
        user.groups.add(group)

        if role_key in ("manager", "agent"):
            user.is_staff = True
        user.save()

        if role_key == "customer":
            CustomerProfile.objects.create(user=user)
        elif role_key == "agent":
            AgentProfile.objects.create(user=user)

        UserApproval.objects.create(
            user=user,
            requested_role=role_key,
            is_approved=False,
        )

        messages.success(
            request,
            "Registration successful. Your account is pending approval. "
            "You will be able to sign in once a Support Manager (for Customer/Agent) or Admin (for Support Manager) approves your account.",
        )
        return redirect("accounts:login")

    return render(request, "accounts/register.html", {"role_key": role_key, "register_roles": REGISTER_ROLES})


@login_required
def profile_view(request):
    agent_profile = None
    customer_profile = None
    try:
        agent_profile = AgentProfile.objects.get(user=request.user)
    except AgentProfile.DoesNotExist:
        agent_profile = None
    try:
        customer_profile = CustomerProfile.objects.get(user=request.user)
    except CustomerProfile.DoesNotExist:
        customer_profile = None

    context = {
        "agent_profile": agent_profile,
        "customer_profile": customer_profile,
    }
    return render(request, "accounts/profile.html", context)

