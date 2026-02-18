def build_conditions(conditions):
    result = []

    for i, c in enumerate(conditions):
        result.append({
        	"fullUrl": f"urn:uuid:condition-{i+1}",
            "resource": {
				"resourceType": "Condition",
				"subject": {
					"reference": "urn:uuid:patient",
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