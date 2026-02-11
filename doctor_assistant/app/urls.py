from django.urls import path
from . import views

urlpatterns = [
	path("", views.home, name="home"),
	path("start/<str:type>/", views.start_interview, name="start_interview"),
	path("enter-id/<int:interview_id>/", views.enter_patient_id, name="enter_patient_id"),
	path("record/<int:interview_id>/", views.record_interview, name="record_interview"),

	path("record_interview/", views.record_interview, name="record_interview"),
	path("save_audio/", views.save_audio, name="save_audio"),
]