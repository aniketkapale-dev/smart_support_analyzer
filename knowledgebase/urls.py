from django.urls import path
from . import views

app_name = "knowledgebase"

urlpatterns = [
    path("", views.article_list, name="list"),
    path("<int:pk>/", views.article_detail, name="detail"),
]

