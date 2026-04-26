def build_medications(meds, patient_reference):
    result = []

    for i, m in enumerate(meds):
        result.append({
            "fullUrl": f"urn:uuid:medication-{i+1}",
			"resource": {
				"resourceType": "MedicationStatement",
				"status": m.get("status", "active"),
				"subject": {
					"reference": patient_reference
				},
				"medicationCodeableConcept": {
					"text": m["text"]
				},
                "dosage": [
                    {
						"text": m["dosage"]
					}
                ]
			},
			"request": {
				"method": "POST",
				"url": "MedicationStatement"
			}
        })

    return result
