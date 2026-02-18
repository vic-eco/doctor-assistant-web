def build_encounter(encounter):
    return {
		"fullUrl": "urn:uuid:encounter",
		"resource": {
			"resourceType": "Encounter",
			"status": "finished",
			"subject": {
				"reference": "urn:uuid:patient"
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