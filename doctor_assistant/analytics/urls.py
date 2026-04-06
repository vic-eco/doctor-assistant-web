from django.urls import path
from . import views

app_name = "analytics"

urlpatterns = [
    path("", views.analytics_home, name="home"),
    path("query/", views.query_endpoint, name="query"),
    path("refresh/", views.refresh_graph, name="refresh"),
    path("stats/", views.graph_stats, name="stats"),
]
