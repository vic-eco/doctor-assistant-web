def build_encounter(encounter, patient_reference):
    return {
		"fullUrl": "urn:uuid:encounter",
		"resource": {
			"resourceType": "Encounter",
			"status": "finished",
			"subject": {
				"reference": patient_reference
			},
			"reasonCode": [
				{
					"text": encounter.get("reason")
				}
			]
		},
		"request": {
            "method": "POST",
            "url": "Encounter"
        }
    }