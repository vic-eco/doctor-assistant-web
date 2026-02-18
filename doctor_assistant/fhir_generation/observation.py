def build_observations(symptoms):
    observations = []

    for i, s in enumerate(symptoms):
        obs = {
            "fullUrl": f"urn:uuid:obs-{i+1}",
            "resource": {
				"resourceType": "Observation",
				"status": "final",
				"code": {
					"text": s["text"]
				},
				"subject": {
					"reference": "urn:uuid:patient"
				},
				"encounter": {
					"reference": "urn:uuid:encounter"
				}
			},
            "request": {
				"method": "POST",
				"url": "Observation"
        	}
        }

        if s["present"] is False:
            obs["resource"]["valueBoolean"] = False
        else:
            value = "present"
            if s.get("duration"):
                value += f", duration: {s['duration']}"
            if s.get("severity"):
                value += f", severity: {s['severity']}"

            obs["resource"]["valueString"] = value

        observations.append(obs)

    return observations