def build_medications(meds):
    result = []

    for i, m in enumerate(meds):
        result.append({
            "fullUrl": f"urn:uuid:medication-{i+1}",
			"resource": {
				"resourceType": "MedicationStatement",
				"status": m.get("status", "active"),
				"subject": {
					"reference": "urn:uuid:patient"
				},
				"medicationCodeableConcept": {
					"text": m["text"]
				}
			},
			"request": {
				"method": "POST",
				"url": "MedicationStatement"
			}
        })

    return result
