from llama_cpp import Llama
import json
from typing import List, Dict, Any
from django.conf import settings

from .llm_loader import get_llm


# ---------------------------------------------------------
# JSON REPAIR (fixes truncated JSON)
# ---------------------------------------------------------

def repair_json(text: str) -> str:
    """Fix incomplete JSON by closing braces/brackets."""
    text = text.replace("<end_of_turn>", "").strip()

    # Fix braces
    open_b = text.count("{")
    close_b = text.count("}")
    if close_b < open_b:
        text += "}" * (open_b - close_b)

    # Fix brackets
    open_br = text.count("[")
    close_br = text.count("]")
    if close_br < open_br:
        text += "]" * (open_br - close_br)

    return text


# ---------------------------------------------------------
# JSON EXTRACTION
# ---------------------------------------------------------

def extract_json_from_response(text: str) -> Dict[str, Any]:
    try:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1:
            return json.loads(text[start:end+1])
        return json.loads(text)
    except Exception as e:
        print("JSON parse error:", e)
        print("Raw output:", text[:300])
        return None


# ---------------------------------------------------------
# MERGING
# ---------------------------------------------------------

def smart_merge_extractions(extractions: List[Dict[str, Any]]) -> Dict[str, Any]:
    merged = {
        "patient": {"name": None, "age": None, "gender": None},
        "encounter": {"reason": None},
        "symptoms": [],
        "conditions": [],
        "medications": [],
        "allergies": []
    }

    seen = {
        "symptoms": set(),
        "conditions": set(),
        "medications": set(),
        "allergies": set()
    }

    for ext in extractions:
        if not ext:
            continue

        # Patient
        if "patient" in ext:
            for k in ["name", "age", "gender"]:
                if ext["patient"].get(k) and not merged["patient"][k]:
                    merged["patient"][k] = ext["patient"][k]

        # Encounter
        if ext.get("encounter", {}).get("reason") and not merged["encounter"]["reason"]:
            merged["encounter"]["reason"] = ext["encounter"]["reason"]

        # Lists
        for field in ["symptoms", "conditions", "medications", "allergies"]:
            for item in ext.get(field, []):
                key = item.get("text", "").lower().strip()
                if key and key not in seen[field]:
                    seen[field].add(key)
                    merged[field].append(item)

    return merged


# ---------------------------------------------------------
# CHUNKING
# ---------------------------------------------------------

def semantic_chunking(transcript: str, max_exchanges: int = 6) -> List[str]:
    lines = [l.strip() for l in transcript.split("\n") if l.strip()]
    chunks = []
    current = []
    exchanges = 0

    for line in lines:
        current.append(line)
        if line.startswith("Patient:"):
            exchanges += 1

        if exchanges >= max_exchanges:
            chunks.append("\n".join(current))
            current = current[-2:]
            exchanges = 1

    if current:
        chunks.append("\n".join(current))

    return chunks


# ---------------------------------------------------------
# GENERATION (correct for MedGemma)
# ---------------------------------------------------------

def generate_text(prompt: str, llm: Llama, max_tokens: int = 1024) -> str:
    response = llm.create_chat_completion(
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a clinical information extraction system. "
                    "Always output complete JSON. Never stop early. "
                    "Do not include <end_of_turn>."
                )
            },
            {"role": "user", "content": prompt}
        ],
        max_tokens=max_tokens,
        temperature=0.0,
        top_p=1.0,
    )

    text = response["choices"][0]["message"]["content"]
    return repair_json(text)


# ---------------------------------------------------------
# MAIN EXTRACTION PIPELINE
# ---------------------------------------------------------

def process_transcript(transcript: str, llm: Llama, use_chunking: bool = False) -> Dict[str, Any]:

    base_prompt = """Extract only explicitly stated facts from the text.
Do not infer diagnoses.
Do not add medical knowledge.
If patient states that they do not have a specific symptom include it with a false present value.
Return ONLY valid JSON.

Schema:
{{
  "patient": {{
    "name": string or null,
    "age": number or null,
    "gender": string or null
  }},
  "encounter": {{
    "reason": string or null
  }},
  "symptoms": [
    {{
      "text": string,
      "present": boolean,
      "duration": string or null,
      "severity": string or null
    }}
  ],
  "conditions": [
    {{
      "text": string (condition_name)
    }}
  ],
  "medications": [
    {{
      "text": string,
      "status": "active" | "stopped" | null
    }}
  ],
  "allergies": [
    {{
      "text": string,
      "reaction": string or null
    }}
  ]
}}

Text:
{text}

JSON:
(Respond with complete JSON. Do not stop early. The JSON format must match exactly)
"""

    if use_chunking:
        chunks = semantic_chunking(transcript)
        extractions = []

        for chunk in chunks:
            prompt = base_prompt.format(text=chunk)
            raw = generate_text(prompt, llm)
            extraction = extract_json_from_response(raw)
            if extraction:
                extractions.append(extraction)

        return smart_merge_extractions(extractions)

    else:
        prompt = base_prompt.format(text=transcript)
        raw = generate_text(prompt, llm)
        return extract_json_from_response(raw)


# ---------------------------------------------------------
# MAIN
# ---------------------------------------------------------

def run_model(transcript):
    
    print("RUN MODEL")
    llm = get_llm()
    print("GOT LLM, CONTINUING")

#     transcript = """
# Hello, I'm Dr. Brown. Can you confirm your name and age?
# Yes, my name is John Miller. I'm 54 years old.
# And your gender?
# Male.
# What brings you in today?
# I've been having chest pain since this morning, about two hours now.
# Can you describe the pain?
# It feels tight, maybe moderate. It gets worse when I walk.
# Any shortness of breath?
# No, no shortness of breath.
# Fever or cough?
# No fever and no cough.
# Do you have any medical conditions?
# I have high blood pressure.
# Are you taking any medications?
# Yes, I take amlodipine every day.
# Any allergies?
# I'm allergic to penicillin. I once had a rash from it.
# Alright, we'll take a closer look today.
# """

    use_chunking = len(transcript.split()) > 500

    print("GENERATING")
    result = process_transcript(transcript, llm, use_chunking)
    print("GENERATED")
    print("\nFINAL EXTRACTED INFORMATION:")
    print(json.dumps(result, indent=2))

    return result

if __name__ == "__main__":
    run_model()
