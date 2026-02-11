from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, JsonResponse
from django.conf import settings
from django.core.files.storage import default_storage

import uuid
import paramiko
import time
import re
import json

from app.models import Interview


# Create your views here.
def home(request):
	return render(request, "home.html")

def start_interview(request, type):
    interview = Interview.objects.create(
        doctor=request.user,
        interview_type=type
    )

    return redirect("enter_patient_id", interview_id=interview.id)

def enter_patient_id(request, interview_id):
    interview = Interview.objects.get(id=interview_id)

    if request.method == "POST":
        interview.patient_id = request.POST["patient_id"]
        interview.save()
        return redirect("record_interview", interview_id=interview.id)

    return render(request, "identification.html", {"interview": interview})

def record_interview(request, interview_id):
    interview = get_object_or_404(Interview, id=interview_id)

    context = {
        "interview": interview,
    }

    return render(request, "interview.html", context)

def save_audio(request):
    if request.method == "POST" and request.FILES.get("audio_file"):
        audio_file = request.FILES["audio_file"]
				
        # Generate unique file name
        # filename = f"recordings/{uuid.uuid4()}.mp3"
        # saved_path = default_storage.save(filename, audio_file)

        result = _hpc_call(audio_file)
        return JsonResponse({"json_res": result})

        # return JsonResponse({"status": "success", "saved_as": saved_path})
    
    return JsonResponse({"status": "error", "message": "Invalid request"}, status=400)

def _hpc_call(audio_file):

    ssh = paramiko.SSHClient()

    # Trust remote host automatically
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    # private_key_path = r"C:\Users\Power\Documents\HPC_Keys\id_rsa.pem"
    key = paramiko.RSAKey.from_private_key_file(settings.SSH_KEY_PATH)

    ssh.connect(
        settings.SSH_HOST, 
        port=22, 
        username=settings.SSH_USER, 
        pkey=key, 
        timeout=10
    )

    # File transfer channel
    sftp = ssh.open_sftp()

    remote_audio_path = settings.REMOTE_INPUT_PATH
    sftp.putfo(audio_file, remote_audio_path)
    print("Uploaded audio:", remote_audio_path)

    cmd = "cd python/test && sbatch batch.sh"
    stdin, stdout, stderr = ssh.exec_command(cmd)

    result = stdout.read().decode()
    print("sbatch output:", result)

    # Extract job ID
    match = re.search(r"Submitted batch job (\d+)", result)
    if not match:
        raise RuntimeError("Could not get job ID from sbatch output")

    job_id = match.group(1)
    print("Job ID:", job_id)

    # Wait for job to finish
    def job_running(job_id):
        stdin, stdout, stderr = ssh.exec_command(f"squeue -j {job_id}")
        output = stdout.read().decode().strip()
        return len(output.split("\n")) > 1  # if more than header line -> job still running

    print("Waiting for job to finish...")

    while job_running(job_id):
        time.sleep(10)

    print("Job finished.")

    # Retrieve response
    # remote_output = "/home/vecono01/python/test/response.out"
    # local_output = "response.out"

    # sftp.get(remote_output, local_output)   # download file
    # print("Downloaded:", local_output)

    remote_output = settings.REMOTE_OUTPUT_PATH

    with sftp.file(remote_output, "r") as remote_file:
        file_content = remote_file.read().decode()   # read as string
        data = json.loads(file_content)

    sftp.close()
    ssh.close()

    return data

    # # Read and print output
    # with open(local_output, "r") as f:
    #     print(f.read())
