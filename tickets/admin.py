from django.contrib import admin

from .models import (
    AuditLog,
    IntegrationConfig,
    KnowledgeBaseArticle,
    ServiceLevelPolicy,
    SupportChannel,
    Ticket,
    TicketAttachment,
    TicketAssignmentRule,
    TicketCategory,
    TicketFeedback,
    TicketReply,
    TicketTag,
)


@admin.register(TicketCategory)
class TicketCategoryAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)


@admin.register(TicketTag)
class TicketTagAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)


class TicketReplyInline(admin.TabularInline):
    model = TicketReply
    extra = 0


class TicketAttachmentInline(admin.TabularInline):
    model = TicketAttachment
    extra = 0


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = (
        "ticket_id",
        "subject",
        "customer",
        "category",
        "priority",
        "status",
        "assigned_agent",
        "created_at",
    )
    list_filter = ("status", "priority", "category", "created_at")
    search_fields = ("ticket_id", "subject", "customer__username", "assigned_agent__username")
    raw_id_fields = ("customer", "assigned_agent")
    inlines = [TicketReplyInline, TicketAttachmentInline]


@admin.register(TicketReply)
class TicketReplyAdmin(admin.ModelAdmin):
    list_display = ("ticket", "author", "created_at")
    search_fields = ("ticket__ticket_id", "author__username", "message")


@admin.register(TicketAttachment)
class TicketAttachmentAdmin(admin.ModelAdmin):
    list_display = ("ticket", "uploaded_by", "uploaded_at")
    search_fields = ("ticket__ticket_id", "uploaded_by__username", "file")


@admin.register(TicketFeedback)
class TicketFeedbackAdmin(admin.ModelAdmin):
    list_display = ("ticket", "rating", "comment_preview", "submitted_by", "created_at")
    list_filter = ("rating", "created_at")
    search_fields = ("ticket__ticket_id", "comment", "submitted_by__username")
    raw_id_fields = ("ticket", "submitted_by")

    def comment_preview(self, obj):
        return (obj.comment[:50] + "…") if obj.comment and len(obj.comment) > 50 else (obj.comment or "—")

    comment_preview.short_description = "Comment"


@admin.register(TicketAssignmentRule)
class TicketAssignmentRuleAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "is_active",
        "priority_order",
        "match_category",
        "match_priority",
        "strategy",
        "assign_to_agent",
        "assign_to_team",
        "created_at",
    )
    list_filter = ("is_active", "strategy", "match_priority", "match_category")
    search_fields = ("name",)
    raw_id_fields = ("assign_to_agent",)
    ordering = ("priority_order", "id")


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("ticket", "action", "performed_by", "from_status", "to_status", "created_at")
    list_filter = ("from_status", "to_status", "created_at")
    search_fields = ("ticket__ticket_id", "action", "performed_by__username")


@admin.register(KnowledgeBaseArticle)
class KnowledgeBaseArticleAdmin(admin.ModelAdmin):
    list_display = ("title", "category", "is_published", "created_by", "created_at")
    list_filter = ("is_published", "category", "created_at")
    search_fields = ("title", "content")


@admin.register(ServiceLevelPolicy)
class ServiceLevelPolicyAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "priority",
        "target_first_response_minutes",
        "target_resolution_minutes",
        "is_active",
        "created_at",
    )
    list_filter = ("priority", "is_active", "created_at")
    search_fields = ("name", "description")


@admin.register(SupportChannel)
class SupportChannelAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "slug")


@admin.register(IntegrationConfig)
class IntegrationConfigAdmin(admin.ModelAdmin):
    list_display = ("name", "provider", "is_enabled", "created_at")
    list_filter = ("provider", "is_enabled", "created_at")
    search_fields = ("name",)

