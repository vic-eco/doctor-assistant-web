import os
import json
import logging
import requests
import re
import json
from typing import Optional
from dataclasses import dataclass, field
from collections import defaultdict

import networkx as nx
from llama_cpp import Llama
from app.llm_loader import get_llm

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
        return f"Allergy: {self.substance} -> {self.reaction}"


@dataclass
class KnowledgeGraph:
    """
    In-memory knowledge graph built on NetworkX.

    Node IDs use namespaced prefixes: "patient:ID", "encounter:ID",
    "observation:ID", "condition:ID", "medication:ID", "allergy:ID".

    Edges carry a 'rel' attribute describing the relationship type.
    """

    patients:     dict[str, PatientNode]     = field(default_factory=dict)
    encounters:   dict[str, EncounterNode]   = field(default_factory=dict)
    observations: dict[str, ObservationNode] = field(default_factory=dict)
    conditions:   dict[str, ConditionNode]   = field(default_factory=dict)
    medications:  dict[str, MedicationNode]  = field(default_factory=dict)
    allergies:    dict[str, AllergyNode]     = field(default_factory=dict)

    # NetworkX directed multigraph - the real graph used for traversal
    G: nx.MultiDiGraph = field(default_factory=nx.MultiDiGraph)

    # Reverse index: feature_code (lower) -> {patient_id, ...}
    _feature_index: dict[str, set[str]] = field(
        default_factory=lambda: defaultdict(set)
    )

    @staticmethod
    def _nid(type_: str, id_: str) -> str:
        return f"{type_}:{id_}"

    def _index_feature(self, code: str, patient_id: str):
        if code:
            self._feature_index[code.lower()].add(patient_id)


    # Add to nodes

    def add_patient(self, node: PatientNode):
        self.patients[node.id] = node
        nid = self._nid("patient", node.id)
        self.G.add_node(nid, type="patient", obj=node)

    def add_encounter(self, node: EncounterNode):
        self.encounters[node.id] = node
        nid = self._nid("encounter", node.id)
        self.G.add_node(nid, type="encounter", obj=node)
        self.G.add_edge(
            self._nid("patient", node.patient_id), nid, rel="has_encounter"
        )

    def add_observation(self, node: ObservationNode):
        self.observations[node.id] = node
        nid = self._nid("observation", node.id)
        self.G.add_node(nid, type="observation", obj=node)
        # patient -> observation
        self.G.add_edge(
            self._nid("patient", node.patient_id), nid, rel="has_observation"
        )
        # encounter -> observation
        if node.encounter_id:
            enc_nid = self._nid("encounter", node.encounter_id)
            if self.G.has_node(enc_nid):
                self.G.add_edge(enc_nid, nid, rel="recorded_in")
        self._index_feature(node.code, node.patient_id)

    def add_condition(self, node: ConditionNode):
        self.conditions[node.id] = node
        nid = self._nid("condition", node.id)
        self.G.add_node(nid, type="condition", obj=node)
        self.G.add_edge(
            self._nid("patient", node.patient_id), nid, rel="has_condition"
        )
        self._index_feature(node.code, node.patient_id)

    def add_medication(self, node: MedicationNode):
        self.medications[node.id] = node
        nid = self._nid("medication", node.id)
        self.G.add_node(nid, type="medication", obj=node)
        self.G.add_edge(
            self._nid("patient", node.patient_id), nid, rel="has_medication"
        )
        self._index_feature(node.medication, node.patient_id)

    def add_allergy(self, node: AllergyNode):
        self.allergies[node.id] = node
        nid = self._nid("allergy", node.id)
        self.G.add_node(nid, type="allergy", obj=node)
        self.G.add_edge(
            self._nid("patient", node.patient_id), nid, rel="has_allergy"
        )
        self._index_feature(node.substance, node.patient_id)


    # Traversal methods
    
    def get_patient_features(self, patient_id: str) -> set[str]:
        """ patient -> all directly linked feature nodes. """
        pnid = self._nid("patient", patient_id)
        features: set[str] = set()
        for _, neighbor, data in self.G.out_edges(pnid, data=True):
            obj = self.G.nodes[neighbor].get("obj")
            if obj is None:
                continue
            if isinstance(obj, ConditionNode):
                features.add(obj.code.lower())
            elif isinstance(obj, ObservationNode):
                if obj.value.lower() not in ("absent", "false", "no"):
                    features.add(obj.code.lower())
        return features

    def get_patients_by_feature(self, feature: str) -> list[str]:
        """ feature name -> list of patient IDs."""
        feature_lower = feature.lower()
        matched: set[str] = set()
        for code, pids in self._feature_index.items():
            if feature_lower in code or code in feature_lower:
                matched.update(pids)
        return list(matched)

    def find_similar_patients(self, patient_id: str, top_n: int = 5) -> list[tuple[str, list[str]]]:
        """
        2-hop traversal:
          hop-1  patient -> features  (get_patient_features)
          hop-2  feature -> patients  (_feature_index)
        """
        target_features = self.get_patient_features(patient_id)
        if not target_features:
            return []

        overlap: dict[str, set[str]] = defaultdict(set)
        for feat in target_features:
            for pid in self._feature_index.get(feat, set()):
                if pid != patient_id:
                    overlap[pid].add(feat)

        ranked = sorted(overlap.items(), key=lambda x: len(x[1]), reverse=True)
        return [(pid, sorted(feats)) for pid, feats in ranked[:top_n]]


    # Context building methods

    def get_patient_context(self, patient_id: str) -> str:
        """Full context for a single patient, structured from graph edges."""
        patient = self.patients.get(patient_id)
        if not patient:
            return f"No data found for patient {patient_id}."

        pnid = self._nid("patient", patient_id)
        lines = [f"=== {patient.summary()} ==="]

        enc_obs: dict[str, list[ObservationNode]] = defaultdict(list)
        standalone_obs: list[ObservationNode] = []
        conditions: list[ConditionNode] = []
        medications: list[MedicationNode] = []
        allergies: list[AllergyNode] = []

        for _, neighbor, data in self.G.out_edges(pnid, data=True):
            obj = self.G.nodes[neighbor].get("obj")
            rel = data.get("rel", "")
            if rel == "has_encounter" and isinstance(obj, EncounterNode):
                # Collect observations hanging off this encounter
                enc_nid = self._nid("encounter", obj.id)
                obs_nodes = [
                    self.G.nodes[n]["obj"]
                    for _, n, d in self.G.out_edges(enc_nid, data=True)
                    if d.get("rel") == "recorded_in"
                    and isinstance(self.G.nodes[n].get("obj"), ObservationNode)
                ]
                lines.append(f"\nEncounter: {obj.reason} [{obj.status}]")
                for o in obs_nodes:
                    lines.append(f"  -> {o.code}: {o.value}")
            elif rel == "has_observation" and isinstance(obj, ObservationNode):
                standalone_obs.append(obj)
            elif rel == "has_condition" and isinstance(obj, ConditionNode):
                conditions.append(obj)
            elif rel == "has_medication" and isinstance(obj, MedicationNode):
                medications.append(obj)
            elif rel == "has_allergy" and isinstance(obj, AllergyNode):
                allergies.append(obj)

        if standalone_obs:
            lines.append("\nObservations (unlinked to encounter):")
            for o in standalone_obs:
                lines.append(f"  • {o.code}: {o.value}")
        if conditions:
            lines.append("\nConditions:")
            for c in conditions:
                lines.append(f"  • {c.code} [{c.status}]")
        if medications:
            lines.append("\nMedications:")
            for m in medications:
                lines.append(f"  • {m.medication} [{m.status}]")
        if allergies:
            lines.append("\nAllergies:")
            for a in allergies:
                lines.append(f"  • {a.substance} -> {a.reaction}")

        return "\n".join(lines)

    def get_similar_patients_subgraph(self, patient_id: str, top_n: int = 5) -> str:
        """
        Focused context for similarity queries.
        Only includes data relevant to the shared features - not full histories.
        """
        target_features = self.get_patient_features(patient_id)
        similar = self.find_similar_patients(patient_id, top_n=top_n)

        if not similar:
            return (
                self.get_patient_context(patient_id)
                + "\n\nNo patients found with overlapping features."
            )

        lines = ["=== BASE PATIENT ===", self.get_patient_context(patient_id)]
        lines.append("\n=== SIMILAR PATIENTS (ranked by shared features) ===")

        for pid, shared_features in similar:
            patient = self.patients.get(pid)
            if not patient:
                continue
            lines.append(f"\n--- {patient.summary()} ---")
            lines.append(f"Shared features ({len(shared_features)}): {', '.join(shared_features)}")

            # Only pull the matching nodes from the graph — not the full record
            pnid = self._nid("patient", pid)
            for _, neighbor, data in self.G.out_edges(pnid, data=True):
                obj = self.G.nodes[neighbor].get("obj")
                if isinstance(obj, ConditionNode) and obj.code.lower() in target_features:
                    lines.append(f"  • Condition: {obj.code} [{obj.status}]")
                elif (
                    isinstance(obj, ObservationNode)
                    and obj.code.lower() in target_features
                    and obj.value.lower() not in ("absent", "false", "no")
                ):
                    lines.append(f"  • Observation: {obj.code}: {obj.value}")

        return "\n".join(lines)

    def get_cross_patient_context(self, patient_ids: list[str]) -> str:
        return "\n\n".join(self.get_patient_context(pid) for pid in patient_ids)

    def get_population_summary(self, top_n: int = 20) -> str:
        """top features across all patients."""
        lines = ["=== POPULATION SUMMARY ==="]
        ranked = sorted(
            self._feature_index.items(), key=lambda x: len(x[1]), reverse=True
        )
        for code, pids in ranked[:top_n]:
            lines.append(f"{code}: {len(pids)} patient(s) — {', '.join(sorted(pids))}")
        return "\n".join(lines)


class FHIRClient:
    """Client for HAPI FHIR REST API."""

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

        for cond in self.client.get_conditions(pid):
            cid = cond.get("id", "")
            code = cond.get("code", {}).get("text", "Unknown")
            status = cond.get("clinicalStatus", {}).get("text", "unknown")
            graph.add_condition(ConditionNode(id=cid, patient_id=pid, code=code, status=status))

        for med in self.client.get_medications(pid):
            mid = med.get("id", "")
            medication = med.get("medicationCodeableConcept", {}).get("text", "Unknown")
            status = med.get("status", "unknown")
            graph.add_medication(MedicationNode(id=mid, patient_id=pid, medication=medication, status=status))

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


# Query planner

PLANNER_PROMPT = """You are a medical query parser. Extract a structured graph traversal plan from the doctor's question.

Return ONLY a valid JSON object.
DO NOT include explanations, markdown, or any text before or after the JSON.
DO NOT wrap the JSON in code fences

Traversal goal guide:
- find_similar: "patients like X", "similar symptoms", "who else has this"
- get_history: "history of patient X", "what does patient X have", "show me patient X"
- compare: "compare patient A and B", "differences between X and Y"
- find_by_symptom: "who has diabetes", "patients with fever", no specific patient anchor
- population_stats: "common conditions", "most frequent", "across all patients"


Return ONLY a valid JSON object with exactly these fields:

If more than one patient IDs are present:
- Put the FIRST patient ID in "anchor_value"
- Put ALL remaining patient IDs in "extra_patient_ids"

Schema
{{
  "traversal_goal": one of ["find_similar", "get_history", "compare", "find_by_symptom", "population_stats"],
  "anchor_type": one of ["patient_id", "national_id", "symptom", "condition", "medication", "population", "allergy", null],
  "anchor_value": the specific value (patient ID, symptom name, etc.) or null if not applicable,
  "extra_patient_ids": list of additional patient IDs for comparison queries (may be empty),
  "filters": list of any extra constraints mentioned (e.g. ["active conditions only", "female patients"])
}}


(Respond with complete JSON. Do not stop early. The JSON format must match exactly)"""


def plan_query(llm: Llama, question: str) -> dict:
    """
    Extract a structured traversal plan from a natural language query.
    Falls back to a safe default if parsing fails.
    """
    try:
        response = llm.create_chat_completion(
            messages=[
                {"role": "system", "content": PLANNER_PROMPT},
                {"role": "user", "content": question},
            ],
            max_tokens=1024,
            temperature=0.0,
        )
        raw = response["choices"][0]["message"]["content"].strip()
        print("RAW LLM OUTPUT:", repr(raw))
        data = extract_json(raw)
        print("EXTRACTED DATA", data)
        return data
    except Exception as e:
        logger.warning(f"Query planner failed ({e}), falling back to population_stats")
        return {
            "traversal_goal": "population_stats",
            "anchor_type": None,
            "anchor_value": None,
            "extra_patient_ids": [],
            "filters": [],
        }


class GraphRAGEngine:

    SYSTEM_PROMPT = """You are a clinical decision support assistant helping doctors analyze patient data.
You have access to structured medical records including encounters, observations, conditions, medications, and allergies.

When analyzing patient data:
- Identify clinically significant patterns (symptom clusters, medication interactions, risk factors)
- Compare patients objectively when asked
- Highlight any red flags or notable correlations
- Be concise but thorough — doctors need actionable insights, not lengthy prose
- Always clarify that you are providing decision support, not a diagnosis
- Use medical terminology appropriately
- If no patients match the doctor's query, say so clearly

Format your response with clear sections when appropriate. Be specific and cite the data provided."""

    def __init__(self, graph: Optional[KnowledgeGraph] = None):
        self.graph = graph
        self._llm = get_llm()


    def refresh_graph(self) -> KnowledgeGraph:
        """Rebuild the knowledge graph from HAPI FHIR."""
        client = FHIRClient()
        builder = GraphBuilder(client)
        self.graph = builder.build_full_graph()
        logger.info(f"Graph refreshed: {len(self.graph.patients)} patients")
        return self.graph


    def _resolve_patient(self, value: str) -> Optional[str]:
        """Resolve a patient by FHIR ID or national ID. Returns FHIR patient ID or None."""
        if not value or not self.graph:
            return None
        value = str(value).strip()
        if value in self.graph.patients:
            return value
        for pid, patient in self.graph.patients.items():
            if patient.national_id == value:
                return pid
        return None

    def _build_context(self, plan: dict) -> str:
        if not self.graph:
            return "No patient data available. Please refresh the knowledge graph."

        goal       = plan.get("traversal_goal", "population_stats")
        anchor_val = plan.get("anchor_value")
        extra_ids  = plan.get("extra_patient_ids", []) or []

        if goal == "find_similar":
            pid = self._resolve_patient(anchor_val)
            if not pid:
                return self._no_patient_error(anchor_val)
            return self.graph.get_similar_patients_subgraph(pid)

        elif goal == "get_history":
            pid = self._resolve_patient(anchor_val)
            if not pid:
                return self._no_patient_error(anchor_val)
            return self.graph.get_patient_context(pid)

        elif goal == "compare":
            ids_to_compare = []
            for v in [anchor_val] + extra_ids:
                pid = self._resolve_patient(str(v)) if v else None
                if pid:
                    ids_to_compare.append(pid)
            if len(ids_to_compare) < 2:
                return (
                    "Could not resolve enough patients for comparison. "
                    f"Resolved: {ids_to_compare}. "
                    f"Available: {self._available_patients_hint()}"
                )
            
            # full record of each patient
            ctx = self.graph.get_cross_patient_context(ids_to_compare)

            # find similar patients to anchor patient
            similar = self.graph.find_similar_patients(ids_to_compare[0])
            
            # extract only relevant features from comparison patients
            relevant = [(pid, feats) for pid, feats in similar if pid in ids_to_compare[1:]]
            if relevant:
                ctx += "\n\n=== SHARED FEATURES ==="
                for pid, feats in relevant:
                    ctx += f"\nShared with {pid}: {', '.join(feats)}"
            return ctx

        elif goal == "find_by_symptom":
            if not anchor_val:
                return "No symptom or condition specified. Please name the symptom to search for."
            pids = self.graph.get_patients_by_feature(anchor_val)
            if not pids:
                return f"No patients found with a feature matching '{anchor_val}'."
            # Return focused context: only the matching feature data per patient
            lines = [f"=== PATIENTS WITH FEATURE MATCHING '{anchor_val}' ===\n"]
            for pid in pids[:10]:
                patient = self.graph.patients.get(pid)
                if not patient:
                    continue
                lines.append(f"--- {patient.summary()} ---")
                pnid = self.graph._nid("patient", pid)
                for _, neighbor, data in self.graph.G.out_edges(pnid, data=True):
                    obj = self.graph.G.nodes[neighbor].get("obj")
                    if isinstance(obj, ConditionNode) and anchor_val.lower() in obj.code.lower():
                        lines.append(f"  • Condition: {obj.code} [{obj.status}]")
                    elif isinstance(obj, ObservationNode) and anchor_val.lower() in obj.code.lower():
                        lines.append(f"  • Observation: {obj.code}: {obj.value}")
                lines.append("")
            return "\n".join(lines)

        elif goal == "population_stats":
            return self.graph.get_population_summary()

        else:
            logger.warning(f"Unknown traversal goal '{goal}', returning population summary.")
            return self.graph.get_population_summary()

    def _no_patient_error(self, anchor_val) -> str:
        return (
            f"Could not find a patient matching '{anchor_val}'.\n"
            f"Available patients: {self._available_patients_hint()}"
        )

    def _available_patients_hint(self) -> str:
        if not self.graph:
            return "(graph not loaded)"
        return ", ".join(
            f"{p.id} ({p.name}, natID:{p.national_id})"
            for p in list(self.graph.patients.values())[:20]
        )


    def query(self, question: str) -> dict:

        if not self.graph:
            try:
                self.refresh_graph()
            except Exception as e:
                return {
                    "answer": f"Could not connect to FHIR server: {e}",
                    "context_used": "",
                    "plan": {},
                    "intent": "error",
                }

        # plan the traversal
        plan = plan_query(self._llm, question)
        logger.info(f"Traversal plan: {plan}")

        # execute traversal -> focused context
        context = self._build_context(plan)

        # call LLM with the focused context
        user_message = (
            f"Here is the relevant patient data retrieved from the medical records system:\n\n"
            f"{context}\n\n"
            f"---\n\n"
            f"Doctor's question: {question}\n\n"
            f"Please analyze the data and provide a clinical assessment."
        )

        try:
            response = self._llm.create_chat_completion(
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user",   "content": user_message},
                ],
                max_tokens=1500,
                temperature=0.3,
            )
            answer = response["choices"][0]["message"]["content"]
        except Exception as e:
            answer = f"Error calling AI model: {e}"

        return {
            "answer": answer,
            "context_used": context,
            "plan": plan,
            "patient_count": len(self.graph.patients),
        }

def extract_json(raw: str) -> dict:
    # Remove markdown fences
    cleaned = re.sub(r"```json|```", "", raw)

    # Find all JSON-like objects
    matches = re.findall(r"\{[\s\S]*?\}", cleaned)

    for m in matches:
        try:
            return json.loads(m)
        except json.JSONDecodeError:
            continue

    raise ValueError("No valid JSON found")