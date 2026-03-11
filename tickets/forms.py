from django import forms

from .models import Ticket, TicketReply, TicketFeedback


class TicketFeedbackForm(forms.ModelForm):
    class Meta:
        model = TicketFeedback
        fields = ["rating", "comment"]
        widgets = {
            "rating": forms.RadioSelect(choices=[(i, str(i)) for i in range(1, 6)]),
            "comment": forms.Textarea(attrs={"rows": 3, "placeholder": "e.g. Great support!"}),
        }


class TicketCreateForm(forms.ModelForm):
    class Meta:
        model = Ticket
        fields = ["subject", "description", "category", "priority", "tags"]


class TicketReplyForm(forms.ModelForm):
    class Meta:
        model = TicketReply
        fields = ["message", "is_internal"]
        widgets = {
            "message": forms.Textarea(
                attrs={
                    "rows": 5,
                    "placeholder": "Hi John,\n\nThanks for contacting support.\nWe're checking the delivery status and will update you shortly.\n\n(You can also paste links here.)",
                }
            ),
        }

