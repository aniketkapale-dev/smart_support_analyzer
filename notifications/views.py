from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from .models import Notification


@login_required
def notification_center(request):
    notifications = Notification.objects.filter(recipient=request.user).order_by(
        "-created_at"
    )
    context = {"notifications": notifications}
    return render(request, "notifications/center.html", context)
