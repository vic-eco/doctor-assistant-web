from django.shortcuts import render
from django.http import HttpResponse, JsonResponse
from django.conf import settings
from django.core.files.storage import default_storage

import uuid


# Create your views here.
def home(request):
	return render(request, "home.html")

def interview_new(request):
	return render(request, "interview.html", {"user_type": "new"})

def interview_existing(request):
	return render(request, "interview.html", {"user_type": "existing"})

def save_audio(request):
    if request.method == "POST" and request.FILES.get("audio_file"):
        audio_file = request.FILES["audio_file"]
				
        # Generate unique file name
        filename = f"recordings/{uuid.uuid4()}.mp3"
        saved_path = default_storage.save(filename, audio_file)
        return JsonResponse({"status": "success", "saved_as": saved_path})
    
    return JsonResponse({"status": "error", "message": "Invalid request"}, status=400)

