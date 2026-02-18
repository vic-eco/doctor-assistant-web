def build_allergies(allergies):
    result = []

    for i, a in enumerate(allergies):
        result.append({
        	"fullUrl": f"urn:uuid:allergy-{i+1}",
            "resource": {
				"resourceType": "AllergyIntolerance",
				"patient": {
					"reference": "urn:uuid:patient"
				},
				"code": {
					"text": a["text"]
				},
				"reaction": [
					{
						"manifestation": [
							{
								"text": a.get("reaction")
							}
						]
					}
				]
			},
			"request": {
            	"method": "POST",
            	"url": "AllergyIntolerance"
        	}
        })

    return result