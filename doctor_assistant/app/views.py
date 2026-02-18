from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, JsonResponse
from django.conf import settings
from django.core.files.storage import default_storage
from django.urls import reverse


import uuid
import paramiko
import time
import re
import json
from pprint import pprint
import ast


from fhir_generation.allergy import build_allergies
from fhir_generation.bundle import build_bundle
from fhir_generation.condition import build_conditions
from fhir_generation.encounter import build_encounter
from fhir_generation.medication import build_medications
from fhir_generation.observation import build_observations
from fhir_generation.patient import build_patient

from medgemma_local import run_model

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
        patient_id = request.POST.get("patient_id")

        #TODO Send audio to HPC and retrieve transcript, then pass transcript through model
        
        # result = _hpc_call(audio_file)
        #result = run_model()

        data = """{'allergies': [{'reaction': 'rash', 'text': 'penicillin'}],
 'conditions': [{'text': 'high blood pressure'}],
 'encounter': {'reason': 'chest pain since this morning'},
 'medications': [{'status': 'active', 'text': 'amlodipine'}],
 'patient': {'age': 54, 'gender': 'Male', 'name': 'John Miller'},
 'symptoms': [{'duration': 'since this morning',
               'present': True,
               'severity': 'moderate',
               'text': 'chest pain'},
              {'duration': None,
               'present': False,
               'severity': None,
               'text': 'shortness of breath'},
              {'duration': None,
               'present': False,
               'severity': None,
               'text': 'fever'},
              {'duration': None,
               'present': False,
               'severity': None,
               'text': 'cough'}]}"""
        
        result = ast.literal_eval(data)

        print("converted Result")
        
        patient = build_patient(result["patient"], patient_id)
        encounter = build_encounter(result["encounter"])
        observations = build_observations(result["symptoms"])
        conditions = build_conditions(result["conditions"])
        meds = build_medications(result["medications"])
        allergies = build_allergies(result["allergies"])

        bundle = build_bundle(
            [patient, encounter] +
            observations +
            conditions +
            meds +
            allergies
        )

        # print("RESULT:\n")
        # pprint(result)
        # print()
        print("BUNDLE:\n")
        pprint(bundle)

        request.session["bundle"] = bundle 
        print("Moving to results")
        return JsonResponse({
            "success": True,
            "redirect_url": reverse("results")
        })        # return render(request, "results.html", {"bundle": bundle})
        # return JsonResponse({"json_res": result, "bundle": bundle})
    
    return JsonResponse({"status": "error", "message": "Invalid request"}, status=400)

def results(request):
    """Display the FHIR bundle for editing"""
    print("DEBUG: Results view called")
    
    bundle = request.session.get("bundle")
    print(f"DEBUG: Bundle from session: {bundle is not None}")
    
    if not bundle:
        print("DEBUG: No bundle found, redirecting to home")
        return redirect("home")  # Or wherever your main page is
    
    # Parse the bundle if it's a string
    if isinstance(bundle, str):
        print("DEBUG: Bundle is string, parsing JSON")
        bundle = json.loads(bundle)
    
    # Extract resources for easier template rendering
    context = {
        "bundle": bundle,
        "bundle_json": json.dumps(bundle),  # JSON string for JavaScript
        "patient": None,
        "encounter": None,
        "observations": [],
        "conditions": [],
        "medications": [],
        "allergies": []
    }
    
    # Organize resources by type
    for entry in bundle.get("entry", []):
        resource = entry.get("resource", {})
        resource_type = resource.get("resourceType")
        
        if resource_type == "Patient":
            context["patient"] = resource
        elif resource_type == "Encounter":
            context["encounter"] = resource
        elif resource_type == "Observation":
            context["observations"].append(resource)
        elif resource_type == "Condition":
            context["conditions"].append(resource)
        elif resource_type == "MedicationStatement":
            context["medications"].append(resource)
        elif resource_type == "AllergyIntolerance":
            context["allergies"].append(resource)
    
    print(f"DEBUG: Rendering template with {len(context['observations'])} observations, "
          f"{len(context['conditions'])} conditions, "
          f"{len(context['medications'])} medications, "
          f"{len(context['allergies'])} allergies")
    
    return render(request, "results.html", context)


def update_bundle(request):
    """Update the FHIR bundle with edited values"""
    bundle = request.session.get("bundle")
    
    if not bundle:
        return redirect("home")
    
    # Parse the bundle if it's a string
    if isinstance(bundle, str):
        bundle = json.loads(bundle)
    
    # Clear existing entries and rebuild from form data
    new_entries = []
    
    # Helper function to generate UUID
    def generate_uuid(resource_type, index):
        return f"urn:uuid:{resource_type.lower()}-{index}"
    
    # 1. UPDATE PATIENT
    patient_name = request.POST.get("patient_name_patient")
    patient_gender = request.POST.get("patient_gender_patient")
    patient_identifier = request.POST.get("patient_identifier_patient")
    
    if patient_name:
        new_entries.append({
            "fullUrl": "urn:uuid:patient",
            "resource": {
                "resourceType": "Patient",
                "identifier": [
                    {
                        "system": "http://national-id",
                        "value": patient_identifier or ""
                    }
                ],
                "name": [
                    {
                        "text": patient_name
                    }
                ],
                "gender": patient_gender
            },
            "request": {
                "method": "POST",
                "url": "Patient"
            }
        })
    
    # 2. UPDATE ENCOUNTER
    encounter_reason = request.POST.get("encounter_reason_encounter")
    
    if encounter_reason:
        new_entries.append({
            "fullUrl": "urn:uuid:encounter",
            "resource": {
                "resourceType": "Encounter",
                "status": "finished",
                "subject": {
                    "reference": "urn:uuid:patient"
                },
                "reasonCode": [
                    {
                        "text": encounter_reason
                    }
                ]
            },
            "request": {
                "method": "POST",
                "url": "Encounter"
            }
        })
    
    # 3. BUILD OBSERVATIONS (dynamic - handle adds/removes)
    obs_index = 1
    while True:
        obs_code_key = f"observation_code_obs-{obs_index}"
        obs_present_key = f"observation_present_obs-{obs_index}"
        obs_value_key = f"observation_value_obs-{obs_index}"
        
        # Check if this observation exists in form data
        if obs_code_key not in request.POST:
            obs_index += 1
            # Stop if we've checked 100 indices without finding anything
            if obs_index > 100:
                break
            continue
        
        obs_code = request.POST.get(obs_code_key, "").strip()
        obs_present = request.POST.get(obs_present_key, "false")
        obs_value = request.POST.get(obs_value_key, "").strip()
        
        # Skip if observation code is empty
        if not obs_code:
            obs_index += 1
            continue
        
        # Create observation resource
        observation_resource = {
            "resourceType": "Observation",
            "status": "final",
            "code": {
                "text": obs_code
            },
            "subject": {
                "reference": "urn:uuid:patient"
            },
            "encounter": {
                "reference": "urn:uuid:encounter"
            }
        }
        
        # Handle value based on present/not present
        if obs_present == "true" and obs_value:
            # Present with details - use valueString
            observation_resource["valueString"] = obs_value
        elif obs_present == "true":
            # Present without details - use valueBoolean True
            observation_resource["valueBoolean"] = True
        else:
            # Not present - use valueBoolean False
            observation_resource["valueBoolean"] = False
        
        new_entries.append({
            "fullUrl": generate_uuid("obs", obs_index),
            "resource": observation_resource,
            "request": {
                "method": "POST",
                "url": "Observation"
            }
        })
        
        obs_index += 1
    
    # 4. BUILD CONDITIONS (dynamic - handle adds/removes)
    cond_index = 1
    while True:
        cond_code_key = f"condition_code_condition-{cond_index}"
        cond_status_key = f"condition_status_condition-{cond_index}"
        
        if cond_code_key not in request.POST:
            cond_index += 1
            if cond_index > 100:
                break
            continue
        
        cond_code = request.POST.get(cond_code_key, "").strip()
        cond_status = request.POST.get(cond_status_key, "active")
        
        if not cond_code:
            cond_index += 1
            continue
        
        new_entries.append({
            "fullUrl": generate_uuid("condition", cond_index),
            "resource": {
                "resourceType": "Condition",
                "subject": {
                    "reference": "urn:uuid:patient"
                },
                "code": {
                    "text": cond_code
                },
                "clinicalStatus": {
                    "text": cond_status
                }
            },
            "request": {
                "method": "POST",
                "url": "Condition"
            }
        })
        
        cond_index += 1
    
    # 5. BUILD MEDICATIONS (dynamic - handle adds/removes)
    med_index = 1
    while True:
        med_name_key = f"medication_name_medication-{med_index}"
        med_status_key = f"medication_status_medication-{med_index}"
        
        if med_name_key not in request.POST:
            med_index += 1
            if med_index > 100:
                break
            continue
        
        med_name = request.POST.get(med_name_key, "").strip()
        med_status = request.POST.get(med_status_key, "active")
        
        if not med_name:
            med_index += 1
            continue
        
        new_entries.append({
            "fullUrl": generate_uuid("medication", med_index),
            "resource": {
                "resourceType": "MedicationStatement",
                "status": med_status,
                "subject": {
                    "reference": "urn:uuid:patient"
                },
                "medicationCodeableConcept": {
                    "text": med_name
                }
            },
            "request": {
                "method": "POST",
                "url": "MedicationStatement"
            }
        })
        
        med_index += 1
    
    # 6. BUILD ALLERGIES (dynamic - handle adds/removes)
    allergy_index = 1
    while True:
        allergy_code_key = f"allergy_code_allergy-{allergy_index}"
        allergy_reaction_key = f"allergy_reaction_allergy-{allergy_index}"
        
        if allergy_code_key not in request.POST:
            allergy_index += 1
            if allergy_index > 100:
                break
            continue
        
        allergy_code = request.POST.get(allergy_code_key, "").strip()
        allergy_reaction = request.POST.get(allergy_reaction_key, "").strip()
        
        if not allergy_code:
            allergy_index += 1
            continue
        
        new_entries.append({
            "fullUrl": generate_uuid("allergy", allergy_index),
            "resource": {
                "resourceType": "AllergyIntolerance",
                "patient": {
                    "reference": "urn:uuid:patient"
                },
                "code": {
                    "text": allergy_code
                },
                "reaction": [
                    {
                        "manifestation": [
                            {
                                "text": allergy_reaction
                            }
                        ]
                    }
                ] if allergy_reaction else []
            },
            "request": {
                "method": "POST",
                "url": "AllergyIntolerance"
            }
        })
        
        allergy_index += 1
    
    # Replace bundle entries with new entries
    bundle["entry"] = new_entries
    
    # Save updated bundle back to session
    request.session["bundle"] = bundle
    request.session.modified = True
    
    # Save to database
    print("Updated Bundle")
    pprint(bundle)    
    return redirect("bundle_saved")  # Or wherever you want to redirect after saving



def bundle_saved(request):
    """Confirmation page after bundle is saved"""
    return render(request, "bundle_saved.html")

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
