import json
import logging
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.core.cache import cache

from .graph_rag import GraphRAGEngine, KnowledgeGraph

logger = logging.getLogger(__name__)

_engine: GraphRAGEngine = None

def get_engine() -> GraphRAGEngine:
    global _engine
    if _engine is None:
        _engine = GraphRAGEngine()
    return _engine

@login_required
def analytics_home(request):
    """Render the analytics chat interface."""
    engine = get_engine()
    patient_count = len(engine.graph.patients) if engine.graph else 0
    return render(request, "analytics.html", {
        "patient_count": patient_count,
    })


@login_required
@require_http_methods(["POST"])
@csrf_exempt  # Use proper CSRF in production; add X-CSRFToken header from JS
def query_endpoint(request):
    """
    POST /analytics/query/
    Body: {"question": "show me patterns for patient 132"}
    Returns: {"answer": "...", "intent": "...", "patient_ids": [...], "patient_count": N}
    """
    try:
        body = json.loads(request.body)
        question = body.get("question", "").strip()
        if not question:
            return JsonResponse({"error": "No question provided."}, status=400)

        engine = get_engine()
        result = engine.query(question)
        return JsonResponse(result)

    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON."}, status=400)
    except Exception as e:
        logger.exception("Error in query endpoint")
        return JsonResponse({"error": str(e)}, status=500)


@login_required
@require_http_methods(["POST"])
@csrf_exempt
def refresh_graph(request):
    """
    POST /analytics/refresh/
    Forces a re-fetch of all data from the HAPI FHIR server.
    """
    try:
        engine = get_engine()
        graph = engine.refresh_graph()
        return JsonResponse({
            "status": "ok",
            "patient_count": len(graph.patients),
            "encounter_count": len(graph.encounters),
            "observation_count": len(graph.observations),
            "condition_count": len(graph.conditions),
        })
    except Exception as e:
        logger.exception("Error refreshing graph")
        return JsonResponse({"error": str(e)}, status=500)


@login_required
def graph_stats(request):
    """
    GET /analytics/stats/
    Returns summary statistics about the current knowledge graph.
    """
    engine = get_engine()
    if not engine.graph:
        return JsonResponse({"loaded": False, "patient_count": 0})

    g = engine.graph
    symptom_map = g.get_all_symptoms_and_conditions()

    # Top 10 most common clinical features
    top_features = sorted(
        [(k, len(v)) for k, v in symptom_map.items()],
        key=lambda x: -x[1]
    )[:10]

    return JsonResponse({
        "loaded": True,
        "patient_count": len(g.patients),
        "encounter_count": len(g.encounters),
        "observation_count": len(g.observations),
        "condition_count": len(g.conditions),
        "medication_count": len(g.medications),
        "allergy_count": len(g.allergies),
        "top_clinical_features": [
            {"feature": f, "patient_count": c} for f, c in top_features
        ],
        "patients": [
            {
                "id": p.id,
                "name": p.name,
                "gender": p.gender,
                "national_id": p.national_id,
            }
            for p in g.patients.values()
        ],
    })
