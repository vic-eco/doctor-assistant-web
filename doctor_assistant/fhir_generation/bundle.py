def build_bundle(resources):
    return {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": [
            r for r in resources
        ]
    }

