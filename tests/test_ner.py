import requests
import json
import os

url = "http://localhost:8000/graph/extract-entities-from-file"

# Create a temporary test file
test_file = "test_ner.txt"
with open(test_file, "w", encoding="utf-8") as f:
    f.write("The threat actor APT28 (Fancy Bear) has been targeting governmental organizations in Europe using the malware X-Agent. They exploited the vulnerability CVE-2026-1234 to gain initial access.")

files = {
    "file": (test_file, open(test_file, "rb"), "text/plain")
}
data = {
    "language": "english",
    "entity_types": "threat-actor,malware,vulnerability,location,organization"
}

try:
    response = requests.post(url, files=files, data=data)
    result = response.json()
    # Print results
    print(json.dumps(result, indent=2, ensure_ascii=False))
finally:
    # Cleanup
    if os.path.exists(test_file):
        os.remove(test_file)
