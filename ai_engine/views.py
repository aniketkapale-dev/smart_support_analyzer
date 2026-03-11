from django.shortcuts import render

from .services import analyze_ticket


def analyze_sample(request):
    sample_text = "Customer reports intermittent login failures on mobile app."
    result = analyze_ticket(sample_text)
    context = {
        "sample_text": sample_text,
        "analysis": {
            "sentiment": result.sentiment,
            "category": result.category,
            "priority": result.priority,
        },
    }
    return render(request, "ai_engine/analyze_sample.html", context)
