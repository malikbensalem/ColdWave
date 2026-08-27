import json, os, requests
from dotenv import dotenv_values
B = (os.environ.get("REACT_APP_BACKEND_URL") or dotenv_values("/app/frontend/.env")["REACT_APP_BACKEND_URL"]).rstrip("/")
s = requests.Session()
s.headers["Content-Type"] = "application/json"
t = s.post(f"{B}/api/auth/login", json={"email": "admin@coldwave.ai", "password": "Admin123!"}, timeout=30).json()["access_token"]
s.headers["Authorization"] = f"Bearer {t}"
integ = s.get(f"{B}/api/settings/integrations", timeout=30).json()
print("provider keys:", {k: (bool(v) if "key" in k or "token" in k else v) for k, v in integ.items() if any(x in k for x in ("telnyx", "inworld", "elevenlabs", "twilio", "provider"))})
print("balances:", json.dumps(s.get(f"{B}/api/settings/integrations/balances", timeout=60).json(), indent=1)[:1500])
v = s.get(f"{B}/api/voices", timeout=60).json()
print("voices provider:", v.get("provider"), "count:", len(v.get("voices", [])), "first:", v["voices"][0])
print("inworld preview:", str(s.post(f"{B}/api/inworld/preview", json={"voice_id": "Ashley"}, timeout=90).json())[:300])
print("voices preview:", str(s.post(f"{B}/api/voices/preview", json={"voice_id": "george", "text": "hello"}, timeout=90).json())[:300])
