from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, render

from tickets.models import KnowledgeBaseArticle

# Common words to ignore when searching (improves matches for "How to reset my password?" etc.)
SEARCH_STOPWORDS = frozenset(
    {"how", "to", "my", "the", "a", "an", "is", "are", "can", "do", "does", "i", "me", "we", "what", "why", "when", "where", "which", "and", "or", "but", "if", "then", "that", "this", "it", "its", "in", "on", "at", "for", "with", "of", "as"}
)


def _search_articles(queryset, query: str):
    """Match articles by splitting query into keywords and matching any in title, content, category, or tags."""
    query = (query or "").strip()
    if not query:
        return queryset
    # Also match the full query as-is for exact phrases
    words = [w.lower() for w in query.split() if len(w) >= 2 and w.lower() not in SEARCH_STOPWORDS]
    if not words:
        words = [query.lower()]
    q = Q()
    for word in words:
        q |= (
            Q(title__icontains=word)
            | Q(content__icontains=word)
            | Q(category__name__icontains=word)
            | Q(tags__name__icontains=word)
        )
    # Include full phrase for "reset password" etc.
    if len(query) >= 2:
        q |= (
            Q(title__icontains=query)
            | Q(content__icontains=query)
            | Q(category__name__icontains=query)
        )
    return queryset.filter(q).distinct()


@login_required
def article_list(request):
    query = (request.GET.get("q") or "").strip()
    articles = KnowledgeBaseArticle.objects.filter(is_published=True)
    if query:
        articles = _search_articles(articles, query)
    articles = articles.select_related("category").prefetch_related("tags").order_by("-created_at")

    context = {
        "query": query,
        "articles": articles,
    }
    return render(request, "knowledgebase/list.html", context)


@login_required
def article_detail(request, pk: int):
    article = get_object_or_404(
        KnowledgeBaseArticle.objects.select_related("category").prefetch_related("tags"),
        pk=pk,
        is_published=True,
    )

    related_articles = (
        KnowledgeBaseArticle.objects.filter(
            is_published=True,
            category=article.category,
        )
        .exclude(pk=article.pk)
        .order_by("-created_at")[:5]
    )

    context = {
        "article": article,
        "related_articles": related_articles,
    }
    return render(request, "knowledgebase/detail.html", context)

