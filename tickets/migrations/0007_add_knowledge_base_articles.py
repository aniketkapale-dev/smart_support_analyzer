# Generated manually for Knowledge Base sample articles

from django.db import migrations


def create_kb_articles(apps, schema_editor):
    TicketCategory = apps.get_model("tickets", "TicketCategory")
    TicketTag = apps.get_model("tickets", "TicketTag")
    KnowledgeBaseArticle = apps.get_model("tickets", "KnowledgeBaseArticle")

    # Categories
    cat_account, _ = TicketCategory.objects.get_or_create(
        name="Account",
        defaults={"description": "Account, login, and password help"},
    )
    cat_billing, _ = TicketCategory.objects.get_or_create(
        name="Billing",
        defaults={"description": "Billing and payments"},
    )
    cat_technical, _ = TicketCategory.objects.get_or_create(
        name="Technical",
        defaults={"description": "Technical issues and troubleshooting"},
    )

    # Tags
    tag_password, _ = TicketTag.objects.get_or_create(name="password")
    tag_login, _ = TicketTag.objects.get_or_create(name="login")
    tag_reset, _ = TicketTag.objects.get_or_create(name="reset")
    tag_account, _ = TicketTag.objects.get_or_create(name="account")
    tag_recovery, _ = TicketTag.objects.get_or_create(name="recovery")
    tag_troubleshooting, _ = TicketTag.objects.get_or_create(name="troubleshooting")
    tag_billing, _ = TicketTag.objects.get_or_create(name="billing")
    tag_refund, _ = TicketTag.objects.get_or_create(name="refund")

    articles_data = [
        {
            "title": "Reset password steps",
            "category": cat_account,
            "tag_names": ["password", "reset", "account"],
            "content": """If you forgot your password, follow these steps to reset it:

1. Go to the login page and click "Forgot password?" below the sign-in form.
2. Enter the email address associated with your account.
3. Check your email for a password reset link. It may take a few minutes to arrive.
4. Click the link in the email (it expires after 24 hours for security).
5. Enter your new password twice to confirm.
6. Sign in with your new password.

If you don't receive the email, check your spam or junk folder. Make sure you entered the same email you used to register. If you still have trouble, create a support ticket and we'll help you recover your account.""",
        },
        {
            "title": "Account recovery",
            "category": cat_account,
            "tag_names": ["account", "recovery", "login"],
            "content": """If you're locked out of your account or can't sign in:

Option 1 — Password reset
Use "Forgot password?" on the login page. You'll receive an email with a link to set a new password.

Option 2 — Email not recognized
If the system says your email isn't found, double-check the address. Try the email you used when you first signed up. If you have multiple accounts, use the one linked to the account you need.

Option 3 — Account locked
After several failed login attempts, your account may be temporarily locked. Wait 15 minutes and try again, or use the password reset flow.

If none of these work, open a support ticket with your registered email and we'll verify your identity and help you regain access.""",
        },
        {
            "title": "Login troubleshooting",
            "category": cat_account,
            "tag_names": ["login", "troubleshooting", "password"],
            "content": """Common login issues and fixes:

• "Invalid username or password" — Make sure Caps Lock is off and you're using the correct username (often your email). Use "Forgot password?" if you're unsure.

• Page won't load — Clear your browser cache or try a different browser. Check that you have a stable internet connection.

• "Account pending approval" — New accounts must be approved by a support manager. You'll be able to sign in after approval. Check your email for updates.

• Session expired — You were signed out for security. Sign in again to continue.

• Two-factor or security prompt — If your organization uses extra verification, complete the step (email code, app, etc.) to sign in.

If your issue isn't listed here, search for more articles or create a support ticket.""",
        },
        {
            "title": "How to change your password",
            "category": cat_account,
            "tag_names": ["password", "account"],
            "content": """To change your password while you're already signed in:

1. Click your profile or account name (top right).
2. Select "Profile" or "Account settings".
3. Find the "Password" or "Security" section.
4. Click "Change password".
5. Enter your current password, then your new password twice.
6. Save changes.

Use a strong password that you don't use elsewhere. If you've forgotten your current password, use the "Forgot password?" flow on the login page instead.""",
        },
        {
            "title": "Request a refund",
            "category": cat_billing,
            "tag_names": ["refund", "billing"],
            "content": """Refund policy and how to request a refund:

Eligibility: Refunds are available within 30 days of purchase for most plans. Check your plan terms for exceptions.

Steps to request a refund:
1. Sign in to your account.
2. Go to Billing or Subscription.
3. Find the transaction you want refunded.
4. Click "Request refund" and briefly state the reason.
5. Our team will review and respond within 2–3 business days.

Alternatively, you can open a support ticket with the subject "Refund request" and include your order ID and reason. We'll process eligible refunds to the original payment method within 5–10 business days.""",
        },
        {
            "title": "Update payment method or billing info",
            "category": cat_billing,
            "tag_names": ["billing"],
            "content": """To update your payment method or billing information:

1. Sign in and go to Billing or Account settings.
2. Select "Payment method" or "Billing information".
3. Add a new card or update the existing one.
4. Set the new method as default if you have more than one.
5. Save changes.

To update your billing address or company name, use the same Billing section and edit the relevant fields. Changes take effect immediately. For invoice or tax ID updates, contact support via a ticket.""",
        },
        {
            "title": "Browser and device requirements",
            "category": cat_technical,
            "tag_names": ["troubleshooting"],
            "content": """For the best experience, use a supported browser and device:

Supported browsers (latest versions):
• Chrome
• Firefox
• Safari
• Edge

Recommended: Keep your browser updated. Clear cache and cookies if you see odd behavior.

Mobile: The site works on modern mobile browsers. For full features (e.g. file uploads, some admin tools), a desktop or laptop is recommended.

If something doesn't load or work as expected, try another browser or device. If the issue continues, create a support ticket with your browser name, version, and a short description of the problem.""",
        },
    ]

    for data in articles_data:
        tag_names = data.pop("tag_names")
        title = data.pop("title")
        category = data.pop("category")
        content = data.pop("content")
        article, created = KnowledgeBaseArticle.objects.get_or_create(
            title=title,
            defaults={
                "category": category,
                "content": content,
                "is_published": True,
            },
        )
        if created:
            for name in tag_names:
                tag = TicketTag.objects.get(name=name)
                article.tags.add(tag)


def remove_kb_articles(apps, schema_editor):
    """Reverse: remove only the articles we added (by title). Leave categories/tags."""
    KnowledgeBaseArticle = apps.get_model("tickets", "KnowledgeBaseArticle")
    titles = [
        "Reset password steps",
        "Account recovery",
        "Login troubleshooting",
        "How to change your password",
        "Request a refund",
        "Update payment method or billing info",
        "Browser and device requirements",
    ]
    KnowledgeBaseArticle.objects.filter(title__in=titles).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("tickets", "0006_integrationconfig_servicelevelpolicy_supportchannel"),
    ]

    operations = [
        migrations.RunPython(create_kb_articles, remove_kb_articles),
    ]
