from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0002_add_user_approval"),
    ]

    operations = [
        migrations.AlterField(
            model_name="agentprofile",
            name="team",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.SET_NULL,
                related_name="agents_legacy",
                to="accounts.team",
            ),
        ),
        migrations.AddField(
            model_name="agentprofile",
            name="teams",
            field=models.ManyToManyField(
                blank=True,
                related_name="agent_members",
                to="accounts.team",
            ),
        ),
    ]

