import json, os, subprocess, time, urllib.error, urllib.request
_tok = None
def project():
    p = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("VERTEX_PROJECT")
    if not p: raise SystemExit("Set GOOGLE_CLOUD_PROJECT (or VERTEX_PROJECT) to the Google Cloud project to call Vertex AI in.")
    return p
def endpoint(model):
    return f"https://aiplatform.googleapis.com/v1/projects/{project()}/locations/global/publishers/google/models/{model}:generateContent"
def token():
    global _tok
    if not _tok: _tok = subprocess.check_output(["gcloud", "auth", "print-access-token"], text=True).strip()
    return _tok
def gemini(prompt, model="gemini-2.5-pro", json_out=True):
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0, "maxOutputTokens": 32000, **({"responseMimeType": "application/json"} if json_out else {})}}
    req = urllib.request.Request(endpoint(model),
        data=json.dumps(body).encode(), headers={"Authorization": f"Bearer {token()}", "Content-Type": "application/json"})
    for attempt in range(8):  # Vertex answers 429 under load: back off rather than fail the run
        try:
            j = json.load(urllib.request.urlopen(req, timeout=300)); break
        except urllib.error.HTTPError as e:
            if e.code not in (429, 503) or attempt == 7: raise
            time.sleep(15 * (attempt + 1))
    t = "".join(p.get("text", "") for p in j["candidates"][0]["content"]["parts"])
    return json.loads(t) if json_out else t
