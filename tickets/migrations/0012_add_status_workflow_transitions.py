from django.db import migrations, models


def seed_default_workflow(apps, schema_editor):
    TicketStatusTransition = apps.get_model("tickets", "TicketStatusTransition")

    defaults = [
        ("open", "assigned"),
        ("assigned", "in_progress"),
        ("in_progress", "resolved"),
        ("resolved", "closed"),
        # Useful operational transitions
        ("in_progress", "waiting_for_customer"),
        ("waiting_for_customer", "in_progress"),
        ("waiting_for_customer", "resolved"),
        ("closed", "reopened"),
        ("reopened", "assigned"),
        ("reopened", "in_progress"),
    ]

    for from_s, to_s in defaults:
        TicketStatusTransition.objects.get_or_create(
            from_status=from_s,
            to_status=to_s,
            defaults={"is_active": True},
        )


class Migration(migrations.Migration):
    dependencies = [
        ("tickets", "0011_add_ai_suggestions"),
    ]

    operations = [
        migrations.CreateModel(
            name="TicketStatusTransition",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("from_status", models.CharField(choices=[("open", "Open"), ("assigned", "Assigned"), ("in_progress", "In Progress"), ("waiting_for_customer", "Pending (Waiting for Customer)"), ("escalated", "Escalated to Manager"), ("resolved", "Resolved"), ("closed", "Closed"), ("reopened", "Reopened")], max_length=20)),
                ("to_status", models.CharField(choices=[("open", "Open"), ("assigned", "Assigned"), ("in_progress", "In Progress"), ("waiting_for_customer", "Pending (Waiting for Customer)"), ("escalated", "Escalated to Manager"), ("resolved", "Resolved"), ("closed", "Closed"), ("reopened", "Reopened")], max_length=20)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "ordering": ["from_status", "to_status", "id"],
                "unique_together": {("from_status", "to_status")},
            },
        ),
        migrations.RunPython(seed_default_workflow, migrations.RunPython.noop),
    ]

