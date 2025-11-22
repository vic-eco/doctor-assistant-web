from django.urls import path
from . import views

urlpatterns = [
  path("", views.home, name="home"),
  path("interview/new_user", views.interview_new, name="new_user_interview"),
  path("interview/existing_user", views.interview_existing, name="existing_user_interview"),
  path("save_audio/", views.save_audio, name="save_audio"),
]