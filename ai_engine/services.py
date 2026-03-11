from __future__ import annotations

from dataclasses import dataclass

from textblob import TextBlob


@dataclass
class TicketAnalysisResult:
    sentiment: str
    category: str
    priority: str


def analyze_ticket(text: str) -> TicketAnalysisResult:
    """
    Very lightweight ticket analysis:
    - sentiment via TextBlob polarity
    - category via simple keyword rules
    - priority via simple urgency keywords
    """
    text = text or ""
    blob = TextBlob(text)
    polarity = blob.sentiment.polarity
    if polarity > 0.15:
        sentiment = "positive"
    elif polarity < -0.15:
        sentiment = "negative"
    else:
        sentiment = "neutral"

    lowered = text.lower()
    if any(k in lowered for k in ["invoice", "billing", "charge", "payment", "refund"]):
        category = "billing"
    elif any(k in lowered for k in ["error", "bug", "crash", "fail", "issue"]):
        category = "technical"
    elif any(k in lowered for k in ["login", "password", "account", "profile", "signup"]):
        category = "account"
    else:
        category = "general"

    if any(k in lowered for k in ["urgent", "asap", "immediately", "down", "outage"]):
        priority = "high"
    elif any(k in lowered for k in ["cannot", "can't", "unable", "blocked"]):
        priority = "high"
    elif any(k in lowered for k in ["slow", "delay", "confusing", "question", "help"]):
        priority = "medium"
    else:
        priority = "low"

    return TicketAnalysisResult(sentiment=sentiment, category=category, priority=priority)

