def build_patient(patient, id):
    return {
        "fullUrl": "urn:uuid:patient",
        "resource": {
            "resourceType": "Patient",
            "identifier": [
                {
                    "system": "http://national-id",
                    "value": f"{id}"
                }
            ],
            "name": [
                {
                    "text": patient.get("name")
                }
            ],
            "gender": patient.get("gender", "").lower()
        },
        "request": {
            "method": "POST",
            "url": "Patient"
        }
    }