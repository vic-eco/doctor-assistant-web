import os
import json
import logging
import requests
from typing import Optional
from dataclasses import dataclass, field
from collections import defaultdict

from llama_cpp import Llama
from django.conf import settings

logger = logging.getLogger(__name__)

HAPI_BASE_URL = os.environ.get("FHIR_URL", "http://localhost:8080/fhir")


@dataclass
class PatientNode:
    id: str
    name: str
    gender: str
    national_id: str = ""

    def summary(self) -> str:
        return f"Patient {self.id} ({self.name}, {self.gender})"


@dataclass
class EncounterNode:
    id: str
    patient_id: str
    reason: str
    status: str

    def summary(self) -> str:
        return f"Encounter {self.id}: {self.reason} [{self.status}]"


@dataclass
class ObservationNode:
    id: str
    patient_id: str
    encounter_id: str
    code: str
    value: str

    def summary(self) -> str:
        return f"Observation '{self.code}': {self.value}"


@dataclass
class ConditionNode:
    id: str
    patient_id: str
    code: str
    status: str

    def summary(self) -> str:
        return f"Condition: {self.code} [{self.status}]"


@dataclass
class MedicationNode:
    id: str
    patient_id: str
    medication: str
    status: str

    def summary(self) -> str:
        return f"Medication: {self.medication} [{self.status}]"


@dataclass
class AllergyNode:
    id: str
    patient_id: str
    substance: str
    reaction: str

    def summary(self) -> str:
        return f"Allergy: {self.substance} → {self.reaction}"


@dataclass
class KnowledgeGraph:
    """
    In-memory knowledge graph.

    Nodes: patients, encounters, observations, conditions, medications, allergies
    Edges: patient→encounter, encounter→observation, patient→condition, etc.
    """
    patients: dict[str, PatientNode] = field(default_factory=dict)
    encounters: dict[str, EncounterNode] = field(default_factory=dict)
    observations: dict[str, ObservationNode] = field(default_factory=dict)
    conditions: dict[str, ConditionNode] = field(default_factory=dict)
    medications: dict[str, MedicationNode] = field(default_factory=dict)
    allergies: dict[str, AllergyNode] = field(default_factory=dict)

    # Adjacency: patient_id → list of connected node summaries
    patient_graph: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))

    def add_patient(self, node: PatientNode):
        self.patients[node.id] = node

    def add_encounter(self, node: EncounterNode):
        self.encounters[node.id] = node
        self.patient_graph[node.patient_id].append(node.summary())

    def add_observation(self, node: ObservationNode):
        self.observations[node.id] = node
        self.patient_graph[node.patient_id].append(
            f"  [{node.encounter_id}] {node.summary()}"
        )

    def add_condition(self, node: ConditionNode):
        self.conditions[node.id] = node
        self.patient_graph[node.patient_id].append(node.summary())

    def add_medication(self, node: MedicationNode):
        self.medications[node.id] = node
        self.patient_graph[node.patient_id].append(node.summary())

    def add_allergy(self, node: AllergyNode):
        self.allergies[node.id] = node
        self.patient_graph[node.patient_id].append(node.summary())

    def get_patient_context(self, patient_id: str) -> str:
        """Return full graph context for a patient as structured text."""
        patient = self.patients.get(patient_id)
        if not patient:
            return f"No data found for patient {patient_id}."

        lines = [f"=== {patient.summary()} ==="]

        # Encounters with their observations grouped
        patient_encounters = {
            eid: enc for eid, enc in self.encounters.items()
            if enc.patient_id == patient_id
        }
        for enc_id, enc in patient_encounters.items():
            lines.append(f"\nEncounter: {enc.reason} [{enc.status}]")
            enc_obs = [
                obs for obs in self.observations.values()
                if obs.patient_id == patient_id and obs.encounter_id == enc_id
            ]
            for obs in enc_obs:
                lines.append(f"  → {obs.code}: {obs.value}")

        # Conditions
        patient_conditions = [
            c for c in self.conditions.values() if c.patient_id == patient_id
        ]
        if patient_conditions:
            lines.append("\nConditions:")
            for c in patient_conditions:
                lines.append(f"  • {c.code} [{c.status}]")

        # Medications
        patient_meds = [
            m for m in self.medications.values() if m.patient_id == patient_id
        ]
        if patient_meds:
            lines.append("\nMedications:")
            for m in patient_meds:
                lines.append(f"  • {m.medication} [{m.status}]")

        # Allergies
        patient_allergies = [
            a for a in self.allergies.values() if a.patient_id == patient_id
        ]
        if patient_allergies:
            lines.append("\nAllergies:")
            for a in patient_allergies:
                lines.append(f"  • {a.substance} → {a.reaction}")

        return "\n".join(lines)

    def get_cross_patient_context(self, patient_ids: list[str]) -> str:
        """Return combined context for multiple patients for comparison."""
        sections = []
        for pid in patient_ids:
            sections.append(self.get_patient_context(pid))
        return "\n\n".join(sections)

    def find_similar_patients(self, patient_id: str) -> list[tuple[str, list[str]]]:
        """Find patients with overlapping conditions/symptoms."""
        target = self.patients.get(patient_id)
        if not target:
            return []

        target_conditions = {
            c.code.lower() for c in self.conditions.values()
            if c.patient_id == patient_id
        }
        target_obs = {
            o.code.lower() for o in self.observations.values()
            if o.patient_id == patient_id
        }
        target_features = target_conditions | target_obs

        similarities = []
        for pid, patient in self.patients.items():
            if pid == patient_id:
                continue
            other_conditions = {
                c.code.lower() for c in self.conditions.values()
                if c.patient_id == pid
            }
            other_obs = {
                o.code.lower() for o in self.observations.values()
                if o.patient_id == pid
            }
            other_features = other_conditions | other_obs
            shared = list(target_features & other_features)
            if shared:
                similarities.append((pid, shared))

        return sorted(similarities, key=lambda x: len(x[1]), reverse=True)

    def get_all_symptoms_and_conditions(self) -> dict[str, list[str]]:
        """Global view: symptom/condition → list of patient IDs."""
        mapping = defaultdict(list)
        for c in self.conditions.values():
            mapping[c.code.lower()].append(c.patient_id)
        for o in self.observations.values():
            if o.value not in ("false", "False", "no", "absent"):
                mapping[o.code.lower()].append(o.patient_id)
        return dict(mapping)



class FHIRClient:
    """Thin client for HAPI FHIR REST API."""

    def __init__(self, base_url: str = HAPI_BASE_URL):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers["Accept"] = "application/fhir+json"

    def _get(self, path: str, params: dict = None) -> dict:
        url = f"{self.base_url}/{path}"
        resp = self.session.get(url, params=params or {}, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def get_all_patients(self) -> list[dict]:
        data = self._get("Patient", {"_count": 200})
        return [e["resource"] for e in data.get("entry", [])]

    def get_patient(self, patient_id: str) -> dict:
        return self._get(f"Patient/{patient_id}")

    def get_encounters(self, patient_id: str) -> list[dict]:
        data = self._get("Encounter", {"subject": patient_id, "_count": 100})
        return [e["resource"] for e in data.get("entry", [])]

    def get_observations(self, patient_id: str) -> list[dict]:
        data = self._get("Observation", {"subject": patient_id, "_count": 200})
        return [e["resource"] for e in data.get("entry", [])]

    def get_conditions(self, patient_id: str) -> list[dict]:
        data = self._get("Condition", {"subject": patient_id, "_count": 100})
        return [e["resource"] for e in data.get("entry", [])]

    def get_medications(self, patient_id: str) -> list[dict]:
        data = self._get("MedicationStatement", {"subject": patient_id, "_count": 100})
        return [e["resource"] for e in data.get("entry", [])]

    def get_allergies(self, patient_id: str) -> list[dict]:
        data = self._get("AllergyIntolerance", {"patient": patient_id, "_count": 100})
        return [e["resource"] for e in data.get("entry", [])]


class GraphBuilder:
    """Converts raw FHIR resources into KnowledgeGraph nodes."""

    def __init__(self, fhir_client: FHIRClient):
        self.client = fhir_client

    def _patient_id(self, resource: dict) -> str:
        return resource.get("id", "unknown")

    def _resolve_ref(self, ref: str) -> str:
        """Extract ID from a FHIR reference like 'Patient/123' or 'urn:uuid:...'"""
        if not ref:
            return ""
        if "/" in ref:
            return ref.split("/")[-1]
        return ref.replace("urn:uuid:", "")

    def build_for_patient(self, graph: KnowledgeGraph, fhir_patient: dict):
        pid = self._patient_id(fhir_patient)
        name = fhir_patient.get("name", [{}])[0].get("text", "Unknown")
        gender = fhir_patient.get("gender", "unknown")
        nid = ""
        for ident in fhir_patient.get("identifier", []):
            nid = ident.get("value", "")
            break

        graph.add_patient(PatientNode(id=pid, name=name, gender=gender, national_id=nid))

        # Encounters
        for enc in self.client.get_encounters(pid):
            eid = enc.get("id", "")
            reason = ""
            for rc in enc.get("reasonCode", []):
                reason = rc.get("text", "")
                break
            graph.add_encounter(EncounterNode(
                id=eid, patient_id=pid,
                reason=reason or "Unknown",
                status=enc.get("status", "unknown")
            ))

        # Observations
        for obs in self.client.get_observations(pid):
            oid = obs.get("id", "")
            code = obs.get("code", {}).get("text", "Unknown")
            enc_ref = self._resolve_ref(obs.get("encounter", {}).get("reference", ""))

            if "valueString" in obs:
                value = obs["valueString"]
            elif "valueBoolean" in obs:
                value = "present" if obs["valueBoolean"] else "absent"
            elif "valueQuantity" in obs:
                vq = obs["valueQuantity"]
                value = f"{vq.get('value', '')} {vq.get('unit', '')}".strip()
            else:
                value = str(obs.get("valueCodeableConcept", {}).get("text", "recorded"))

            graph.add_observation(ObservationNode(
                id=oid, patient_id=pid, encounter_id=enc_ref,
                code=code, value=value
            ))

        # Conditions
        for cond in self.client.get_conditions(pid):
            cid = cond.get("id", "")
            code = cond.get("code", {}).get("text", "Unknown")
            status = cond.get("clinicalStatus", {}).get("text", "unknown")
            graph.add_condition(ConditionNode(id=cid, patient_id=pid, code=code, status=status))

        # Medications
        for med in self.client.get_medications(pid):
            mid = med.get("id", "")
            medication = med.get("medicationCodeableConcept", {}).get("text", "Unknown")
            status = med.get("status", "unknown")
            graph.add_medication(MedicationNode(id=mid, patient_id=pid, medication=medication, status=status))

        # Allergies
        for allergy in self.client.get_allergies(pid):
            aid = allergy.get("id", "")
            substance = allergy.get("code", {}).get("text", "Unknown")
            reactions = []
            for r in allergy.get("reaction", []):
                for m in r.get("manifestation", []):
                    reactions.append(m.get("text", ""))
            reaction_str = ", ".join(filter(None, reactions)) or "unspecified"
            graph.add_allergy(AllergyNode(
                id=aid, patient_id=pid,
                substance=substance, reaction=reaction_str
            ))

    def build_full_graph(self) -> KnowledgeGraph:
        graph = KnowledgeGraph()
        patients = self.client.get_all_patients()
        logger.info(f"Building graph for {len(patients)} patients")
        for fhir_patient in patients:
            try:
                self.build_for_patient(graph, fhir_patient)
            except Exception as e:
                logger.warning(f"Error building patient {fhir_patient.get('id')}: {e}")
        return graph


def classify_query(query: str) -> dict:
    """
    Simple heuristic to extract patient IDs and query intent from natural language.
    Returns: {intent, patient_ids, raw_query}
    """
    import re
    query_lower = query.lower()

    # Extract any numbers that look like patient IDs
    patient_ids = re.findall(r'\bpatient[s]?\s*#?(\d+)\b|\bid[:\s]*(\d+)', query_lower)
    flat_ids = [pid for group in patient_ids for pid in group if pid]

    # Also find bare numbers if "patient" appears nearby
    if not flat_ids:
        flat_ids = re.findall(r'\b(\d{1,6})\b', query)

    # Determine intent
    if any(w in query_lower for w in ["compar", "similar", "same", "both", "differ"]):
        intent = "comparison"
    elif any(w in query_lower for w in ["pattern", "trend", "history", "overview", "analysis"]):
        intent = "pattern_analysis"
    elif any(w in query_lower for w in ["all patients", "across", "population", "common"]):
        intent = "population"
    elif any(w in query_lower for w in ["drug", "medication", "allerg", "prescri"]):
        intent = "medication"
    else:
        intent = "general"

    return {
        "intent": intent,
        "patient_ids": flat_ids[:5],  # max 5 patients
        "raw_query": query,
    }


class GraphRAGEngine:
    """
    Main engine: retrieves graph context and calls Claude for analysis.
    """

    SYSTEM_PROMPT = """You are a clinical decision support assistant helping doctors analyze patient data.
You have access to structured medical records including encounters, observations, conditions, medications, and allergies.

When analyzing patient data:
- Identify clinically significant patterns (symptom clusters, medication interactions, risk factors)
- Compare patients objectively when asked
- Highlight any red flags or notable correlations
- Be concise but thorough — doctors need actionable insights, not lengthy prose
- Always clarify that you are providing decision support, not a diagnosis
- Use medical terminology appropriately

Format your response with clear sections when appropriate. Be specific and cite the data provided."""

    def __init__(self, graph=None):
        self.graph = graph
        model_path = settings.BASE_DIR / "model_files" / "medgemma-1.5-4b-it-Q4_K_M.gguf"
        self._llm = Llama(
            model_path=str(model_path),
            n_ctx=8192,      
            n_gpu_layers=0, 
            verbose=False,
        )

    def refresh_graph(self):
        """Rebuild the knowledge graph from HAPI FHIR."""
        client = FHIRClient()
        builder = GraphBuilder(client)
        self.graph = builder.build_full_graph()
        logger.info(f"Graph refreshed: {len(self.graph.patients)} patients")
        return self.graph

    def _build_context(self, classified: dict) -> str:
        """Build the graph context string for the query."""
        if not self.graph:
            return "No patient data available. Please refresh the knowledge graph."

        intent = classified["intent"]
        patient_ids = classified["patient_ids"]

        if intent == "population":
            # Aggregate across all patients
            symptom_map = self.graph.get_all_symptoms_and_conditions()
            lines = ["=== POPULATION-WIDE CLINICAL DATA ===\n"]
            for symptom, pids in sorted(symptom_map.items(), key=lambda x: -len(x[1])):
                if len(pids) > 1:
                    lines.append(f"'{symptom}' → {len(pids)} patients: {', '.join(pids)}")
            all_context = "\n".join(lines)
            # Also append all patient records for full context
            all_patient_ctx = self.graph.get_cross_patient_context(
                list(self.graph.patients.keys())
            )
            return all_context + "\n\n" + all_patient_ctx

        elif patient_ids:
            # Resolve patient IDs - HAPI assigns its own IDs
            # We try to match by ID or by national_id
            resolved = []
            for qid in patient_ids:
                # Direct match
                if qid in self.graph.patients:
                    resolved.append(qid)
                else:
                    # Match by national_id
                    for pid, patient in self.graph.patients.items():
                        if patient.national_id == qid:
                            resolved.append(pid)
                            break

            if not resolved:
                # Fall back to listing all patients
                available = ", ".join(
                    f"{p.id} ({p.name}, natID:{p.national_id})"
                    for p in self.graph.patients.values()
                )
                return (
                    f"Could not find patients with IDs {patient_ids}.\n"
                    f"Available patients: {available}"
                )

            if intent == "comparison" and len(resolved) >= 2:
                ctx = self.graph.get_cross_patient_context(resolved)
                # Add similarity analysis
                shared = self.graph.find_similar_patients(resolved[0])
                relevant = [(pid, features) for pid, features in shared if pid in resolved[1:]]
                if relevant:
                    ctx += "\n\n=== SHARED FEATURES ==="
                    for pid, features in relevant:
                        ctx += f"\nShared with {pid}: {', '.join(features)}"
                return ctx
            else:
                return self.graph.get_cross_patient_context(resolved)

        else:
            # No specific patients mentioned — use all data
            return self.graph.get_cross_patient_context(
                list(self.graph.patients.keys())
            )

    def query(self, question: str) -> dict:
        """
        Main entry point. Returns {answer, context_used, patient_ids, intent}
        """
        if not self.graph:
            try:
                self.refresh_graph()
            except Exception as e:
                return {
                    "answer": f"Could not connect to FHIR server: {e}",
                    "context_used": "",
                    "patient_ids": [],
                    "intent": "error",
                }

        classified = classify_query(question)
        context = self._build_context(classified)

        user_message = f"""Here is the patient data from the medical records system:

{context}

---

Doctor's question: {question}

Please analyze the data and provide a clinical assessment."""

        try:
            response = self._llm.create_chat_completion(
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user",   "content": user_message},
                ],
                max_tokens=1500,
                temperature=0.3,   # low temp = more consistent clinical answers
            )
            # response.raise_for_status()
            # data = response.json()
            answer = response["choices"][0]["message"]["content"]
        except Exception as e:
            answer = f"Error calling AI model: {e}"

        return {
            "answer": answer,
            "context_used": context,
            "patient_ids": classified["patient_ids"],
            "intent": classified["intent"],
            "patient_count": len(self.graph.patients),
        }
