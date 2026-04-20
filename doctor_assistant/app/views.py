from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, JsonResponse
from django.conf import settings
from django.core.files.storage import default_storage
from django.urls import reverse
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator


import uuid
import paramiko
import time
import re
import json
from pprint import pprint
import ast
import requests
import sys
import re


from fhir_generation.allergy import build_allergies
from fhir_generation.bundle import build_bundle
from fhir_generation.condition import build_conditions
from fhir_generation.encounter import build_encounter
from fhir_generation.medication import build_medications
from fhir_generation.observation import build_observations
from fhir_generation.patient import build_patient

from .medgemma_local import run_model
from .asr import transcribe_audio

from app.models import Interview


@login_required
def home(request):
	return render(request, "home.html")

@login_required
def view_existing_patients(request):
    search_type = request.GET.get("search_type") or ""
    query = request.GET.get("query") or ""
    page_url = request.GET.get("page_url")

    patients, next_url, prev_url = _get_patients(
        search_type=search_type,
        query=query,
        page_url=page_url
    )

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({
            "patients": patients,
            "next_url": next_url
        })

    return render(
        request,
        "existing_patients.html",
        {
            "patients": patients,
            "next_url": next_url,
            "search_type": search_type,
            "query": query,
        }
    )

@login_required
def view_patient_details(request, patient_id):

    details = _get_patient_details(patient_id)
    print(details)
    
    return render(request, "patient_details.html", details)

@login_required
def start_interview(request, type):
    interview = Interview.objects.create(
        doctor=request.user,
        interview_type=type
    )

    return redirect("enter_patient_id", interview_id=interview.id)

@login_required
def start_interview_existing(request, patient_id):
    interview = Interview.objects.create(
        doctor=request.user,
        interview_type=Interview.EXISTING,
        patient_id=patient_id
    )

    return redirect("record_interview", interview_id=interview.id)

@login_required
def enter_patient_id(request, interview_id):
    interview = Interview.objects.get(id=interview_id)

    if request.method == "POST":
        interview.patient_id = request.POST["patient_id"]
        interview.save()
        return redirect("record_interview", interview_id=interview.id)

    return render(request, "identification.html", {"interview": interview})

@login_required
def record_interview(request, interview_id):
    interview = get_object_or_404(Interview, id=interview_id)

    patient = {}
    if interview.interview_type == Interview.EXISTING:
        patient = _get_patient_by_identifier(interview.patient_id)

    context = {
        "interview": interview,
        "patient": patient
    }

    return render(request, "interview.html", context)

@login_required
def save_audio(request):
    if request.method == "POST" and request.FILES.get("audio_file"):
        audio_file = request.FILES["audio_file"]
        patient_identifier = request.POST.get("patient_identifier")
        interview_type = request.POST.get("interview_type")

        transcript = transcribe_audio(audio_file)
        result = run_model(transcript)
    
        if interview_type == Interview.NEW:
            patient_reference = "urn:uuid:patient"
            patient = build_patient(result["patient"], patient_identifier)
        else:
            patient_resource_id = request.POST.get("patient_resource_id")
            request.session["patient_resource_id"] = patient_resource_id 
            request.session.modified = True
            patient_reference = f"Patient/{patient_resource_id}"
        
        encounter = build_encounter(result["encounter"], patient_reference)
        observations = build_observations(result["symptoms"], patient_reference)
        conditions = build_conditions(result["conditions"], patient_reference)
        meds = build_medications(result["medications"], patient_reference)
        allergies = build_allergies(result["allergies"], patient_reference)

        if interview_type == Interview.NEW:
            bundle = build_bundle(
                [patient, encounter] +
                observations +
                conditions +
                meds +
                allergies
            )
        else:
            bundle = build_bundle(
                [encounter] +
                observations +
                conditions +
                meds +
                allergies
            )

        print("BUNDLE")
        print(bundle)

        request.session["bundle"] = bundle 
        request.session.modified = True

        return JsonResponse({
            "success": True,
            "redirect_url": reverse("results")
        }) 
    
    return JsonResponse({"status": "error", "message": "Invalid request"}, status=400)

@login_required
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


@login_required
def update_bundle(request):
    bundle = request.session.get("bundle")
    
    if not bundle:
        return redirect("home")
    
    # Parse the bundle if it's a string
    if isinstance(bundle, str):
        bundle = json.loads(bundle)
    
    # Clear existing entries and rebuild from form data
    new_entries = []
    
    def generate_uuid(resource_type, index):
        return f"urn:uuid:{resource_type.lower()}-{index}"
    
    # Update Patient
    patient_name = request.POST.get("patient_name_patient")
    patient_gender = request.POST.get("patient_gender_patient")
    patient_identifier = request.POST.get("patient_identifier_patient")

    patient_resource_id = request.session.get("patient_resource_id")
    if isinstance(patient_resource_id, str) and patient_resource_id.isdigit():
        patient_reference = f"Patient/{patient_resource_id}"
    else:
        patient_reference = "urn:uuid:patient"
    
    if patient_name:
        new_entries.append({
            "fullUrl": patient_reference,
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
    
    # Update Encounter
    encounter_reason = request.POST.get("encounter_reason_encounter")
    
    if encounter_reason:
        new_entries.append({
            "fullUrl": "urn:uuid:encounter",
            "resource": {
                "resourceType": "Encounter",
                "status": "finished",
                "subject": {
                    "reference": patient_reference
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
    
    # Build Observations
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
                "reference": patient_reference
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
    
    # Build Conditions
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
                    "reference": patient_reference
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
    
    # Build Medications
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
                    "reference": patient_reference
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
    
    # Build allergies
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
                    "reference": patient_reference
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
    try:
        result = _save_bundle(bundle)
        print("Success!")
        print(result)

    except requests.exceptions.HTTPError as e:
        print("HTTP error occurred:")
        print(f"Status code: {e.response.status_code}")
        return redirect("bundle_failed", error_type=f"HTTP Error {e.response.status_code}")

    except requests.exceptions.ConnectionError:
        print("Connection error: Is the FHIR server running?")
        return redirect("bundle_failed", error_type=f"Connection Error")

    except requests.exceptions.Timeout:
        print("Request timed out")
        return redirect("bundle_failed", error_type=f"Request Time-Out")


    except requests.exceptions.RequestException as e:
        print("Unexpected error:", str(e))
        return redirect("bundle_failed", error_type=f"Unexpected error:")

    return redirect("bundle_saved")

@login_required
def bundle_saved(request):
    return render(request, "bundle_saved.html")

@login_required
def bundle_failed(request, err):
    context = {
        "error_type": err
    }
    return render(request, "bundle_failed.html", context)

def _save_bundle(data):
    url = settings.FHIR_URL
    
    headers = {
        "Content-Type": "application/fhir+json"
    }
    
    response = requests.post(url, headers=headers, json=data)
    
    response.raise_for_status()
    
    return response.json()

def _get_patient_by_identifier(identifier_value: str):
    url = f"{settings.FHIR_URL}/Patient"
    
    params = {
        "identifier": f"http://national-id|{identifier_value}"
    }

    headers = {
        "Accept": "application/fhir+json"
    }

    response = requests.get(
        url,
        headers=headers,
        params=params,
        timeout=10
    )

    response.raise_for_status()

    bundle = response.json()

    # FHIR search returns a Bundle
    entries = bundle.get("entry", [])

    if not entries:
        return None

    return entries[0]["resource"]

def _get_patients(search_type=None, query=None, page_url=None):
    headers = {
        "Accept": "application/fhir+json"
    }

    # If we already have a pagination URL → use it directly
    if page_url:
        url = page_url
        params = {}
    else:
        url = f"{settings.FHIR_URL}/Patient"
        params = {"_count": 5}  # match your UI page size

        if search_type and query:
            if search_type == "name":
                params["name:contains"] = query
            else:
                params[search_type] = query

    response = requests.get(
        url,
        headers=headers,
        params=params,
        timeout=10
    )
    response.raise_for_status()

    bundle = response.json()

    entries = bundle.get("entry", [])

    patients = []
    for entry in entries:
        resource = entry["resource"]

        patients.append({
            "patient_rec_id": resource["id"],
            "patient_identifier": resource["identifier"][0]["value"],
            "patient_name": resource["name"][0].get("text", ""),
            "gender": resource.get("gender", "")
        })

    # Extract pagination links
    next_url = None
    prev_url = None

    for link in bundle.get("link", []):
        if link["relation"] == "next":
            next_url = link["url"]
        elif link["relation"] == "previous":
            prev_url = link["url"]

    return patients, next_url, prev_url

def _get_patient_details(id: str):

    url = f"{settings.FHIR_URL}/Patient/{id}/$everything"

    headers = { 
        "Accept": "application/fhir+json"
    }

    response = requests.get(
        url,
        headers,
        timeout=10
    )

    response.raise_for_status()

    bundle = response.json()

    entries = bundle.get("entry", [])

    encounters = []
    observations = []
    conditions = []
    medications = []
    allergies = []

    patient_name = ""
    patient_identifier=""

    for entry in entries:
        match entry["resource"]["resourceType"]:
            case "Patient":
                patient_name = entry["resource"]["name"][0]["text"]
                patient_identifier = entry["resource"]["identifier"][0]["value"]
            case "Encounter":
                encounters.append(_build_encounter_obj(entry))
            case "Observation":
                observations.append(_build_observation_obj(entry))
            case "Condition":
                conditions.append(_build_condition_obj(entry))
            case "MedicationStatement":
                medications.append(_build_medication_obj(entry))
            case "AllergyIntolerance":
                allergies.append(_build_allergy_obj(entry))
    
    encounter_lookup = {e["url"]: e for e in encounters}
    for obs in observations:
        if obs["reference"] in encounter_lookup:
            encounter_lookup[obs["reference"]]["observations"].append(obs)

    return {
        "patient_name": patient_name,
        "patient_identifier": patient_identifier,
        "encounters": _sort_by_date(encounters),
        "conditions": _sort_by_date(conditions),
        "medications": _sort_by_date(medications),
        "allergies": _sort_by_date(allergies),
    }

def _build_encounter_obj(entry):
    url = re.search(r"Encounter/\d+", entry["fullUrl"])
    url = url.group()
    return{
        "url": url,
        "status": entry["resource"]["status"],
        "reason": entry["resource"]["reasonCode"][0]["text"],
        "last_updated": entry["resource"]["meta"]["lastUpdated"],
        "observations": []
    }

def _build_observation_obj(entry):
    resource = entry["resource"]
    return{
        "text": resource["code"]["text"],
        "notes_string": resource.get("valueString"),
        "notes_boolean": resource.get("valueBoolean"),
        "reference": resource["encounter"]["reference"]
    }

def _build_condition_obj(entry):
    return{
        "text": entry["resource"]["code"]["text"],
        "status": entry["resource"]["clinicalStatus"]["text"],
        "last_updated": entry["resource"]["meta"]["lastUpdated"]
    }

def _build_medication_obj(entry):
    return{
        "text": entry["resource"]["medicationCodeableConcept"]["text"],
        "status": entry["resource"]["status"],
        "last_updated": entry["resource"]["meta"]["lastUpdated"]
    }

def _build_allergy_obj(entry):
    return{
        "text": entry["resource"]["code"]["text"],
        "reaction": entry["resource"]["reaction"][0]["manifestation"][0]["text"],
        "last_updated": entry["resource"]["meta"]["lastUpdated"]
    }

def _sort_by_date(items):
    return sorted(items, key=lambda x: x.get("last_updated") or "", reverse=True)
