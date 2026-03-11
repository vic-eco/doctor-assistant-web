def build_conditions(conditions, patient_reference):
    result = []

    for i, c in enumerate(conditions):
        result.append({
        	"fullUrl": f"urn:uuid:condition-{i+1}",
            "resource": {
				"resourceType": "Condition",
				"subject": {
					"reference": patient_reference,
				},
				"code": {
					"text": c["text"]
				},
				"clinicalStatus": {
					"text": "active"
				}
			},
			"request": {
				"method": "POST",
				"url": "Condition"
        	}
        })

    return result