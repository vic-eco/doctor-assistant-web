from django.urls import path
from . import views

urlpatterns = [
	path("", views.home, name="home"),
	path("start/<str:type>/", views.start_interview, name="start_interview"),
	path("start/existing/<str:patient_id>/", views.start_interview_existing, name="start_interview_existing"),

	path("enter-id/<int:interview_id>/", views.enter_patient_id, name="enter_patient_id"),
	path("record/<int:interview_id>/", views.record_interview, name="record_interview"),

	path("existing_patients/", views.view_existing_patients, name="view_existing_patients"),
	path("patient/<int:patient_id>/", views.view_patient_details, name="view_patient_details"),

	path("record_interview/", views.record_interview, name="record_interview"),
	path("save_audio/", views.save_audio, name="save_audio"),
    path('results/', views.results, name='results'),
    path('update-bundle/', views.update_bundle, name='update_bundle'),
    path('bundle-saved/', views.bundle_saved, name='bundle_saved'),
	path('bundle-failed/', views.bundle_failed, name='bundle_failed'),
]