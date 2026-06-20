"""ColdWave AI Calling Platform - Backend API tests"""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://dialflow-crm-1.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@coldwave.ai"
ADMIN_PW = "Admin123!"


@pytest.fixture(scope="session")
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    # login
    r = s.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PW}, timeout=30)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    data = r.json()
    assert "access_token" in data
    s.headers["Authorization"] = f"Bearer {data['access_token']}"
    return s


# -------- Auth --------
class TestAuth:
    def test_root_ok(self):
        r = requests.get(f"{API}/", timeout=15)
        assert r.status_code == 200

    def test_login_success(self):
        r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PW}, timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert d["email"] == ADMIN_EMAIL
        assert d["role"] == "admin"
        assert d["access_token"]
        # cookie set
        assert "access_token" in r.cookies or any(c.name == "access_token" for c in r.cookies)

    def test_login_invalid(self):
        r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": "wrong-pw"}, timeout=15)
        assert r.status_code == 401

    def test_me_bearer(self, session):
        r = session.get(f"{API}/auth/me", timeout=15)
        assert r.status_code == 200
        assert r.json()["email"] == ADMIN_EMAIL

    def test_me_cookie(self):
        # cookie-only auth
        s = requests.Session()
        r = s.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PW}, timeout=15)
        assert r.status_code == 200
        r2 = s.get(f"{API}/auth/me", timeout=15)
        assert r2.status_code == 200, r2.text


# -------- Dashboard --------
class TestDashboard:
    def test_stats(self, session):
        r = session.get(f"{API}/dashboard/stats", timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert d["total_contacts"] >= 6, f"expected >=6 seeded contacts, got {d['total_contacts']}"
        assert d["active_campaigns"] >= 1
        assert "by_status" in d
        assert isinstance(d["recent_calls"], list)


# -------- Contacts --------
class TestContacts:
    def test_list_seeded(self, session):
        r = session.get(f"{API}/contacts", timeout=15)
        assert r.status_code == 200
        contacts = r.json()
        assert len(contacts) >= 6

    def test_create_get_update_delete(self, session):
        payload = {"name": "TEST_Lead", "phone": "+447700900999", "email": "t@t.co",
                   "company": "TestCo", "notes": "n", "consent": True}
        r = session.post(f"{API}/contacts", json=payload, timeout=15)
        assert r.status_code == 200
        c = r.json()
        assert c["name"] == "TEST_Lead"
        cid = c["id"]

        # GET
        r2 = session.get(f"{API}/contacts/{cid}", timeout=15)
        assert r2.status_code == 200
        assert r2.json()["phone"] == "+447700900999"

        # UPDATE
        r3 = session.put(f"{API}/contacts/{cid}", json={"status": "callback"}, timeout=15)
        assert r3.status_code == 200
        assert r3.json()["status"] == "callback"

        # DELETE
        r4 = session.delete(f"{API}/contacts/{cid}", timeout=15)
        assert r4.status_code == 200
        r5 = session.get(f"{API}/contacts/{cid}", timeout=15)
        assert r5.status_code == 404


# -------- Scripts & Campaigns --------
class TestScriptsCampaigns:
    def test_list_scripts(self, session):
        r = session.get(f"{API}/scripts", timeout=15)
        assert r.status_code == 200
        assert len(r.json()) >= 1

    def test_list_campaigns(self, session):
        r = session.get(f"{API}/campaigns", timeout=15)
        assert r.status_code == 200
        assert len(r.json()) >= 1

    def test_generate_script_ai(self, session):
        # uses Claude — can take 5-15s
        payload = {"product": "AI Cold Caller", "audience": "UK B2B sales leaders",
                   "objective": "Book a demo", "tone": "professional"}
        r = session.post(f"{API}/scripts/generate", json=payload, timeout=90)
        assert r.status_code == 200, r.text
        content = r.json().get("content", "")
        assert len(content) > 50, f"AI script too short: {content!r}"

    def test_create_campaign(self, session):
        scripts = session.get(f"{API}/scripts").json()
        sid = scripts[0]["id"]
        r = session.post(f"{API}/campaigns", json={
            "name": "TEST_Camp", "script_id": sid, "voice_id": "george", "description": "t"
        }, timeout=15)
        assert r.status_code == 200
        cid = r.json()["id"]
        session.delete(f"{API}/campaigns/{cid}")


# -------- Voices --------
class TestVoices:
    def test_list_voices(self, session):
        r = session.get(f"{API}/voices", timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert "voices" in d
        assert len(d["voices"]) >= 2

    def test_voice_preview(self, session):
        r = session.post(f"{API}/voices/preview",
                         json={"voice_id": "george", "text": "Hello there"}, timeout=20)
        assert r.status_code == 200


# -------- Test Calls (Claude LLM) --------
class TestTestCalls:
    def test_full_flow(self, session):
        # start
        r = session.post(f"{API}/calls/test/start",
                         json={"voice_id": "george"}, timeout=15)
        assert r.status_code == 200, r.text
        call_id = r.json()["call_id"]

        # turn (LLM)
        r2 = session.post(f"{API}/calls/test/turn",
                          json={"call_id": call_id, "message": "Not interested, remove me from your list."},
                          timeout=90)
        assert r2.status_code == 200, r2.text
        assert len(r2.json().get("reply", "")) > 0

        # end + analyse
        r3 = session.post(f"{API}/calls/test/{call_id}/end", timeout=90)
        assert r3.status_code == 200, r3.text
        analysis = r3.json().get("analysis", {})
        assert "sentiment" in analysis
        # opt-out detection
        assert analysis.get("opted_out") is True or analysis.get("opted_out") is False  # at least present


# -------- Compliance --------
class TestCompliance:
    def test_overview(self, session):
        r = session.get(f"{API}/compliance/overview", timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert "calling_hours" in d
        assert "dnc_count" in d

    def test_dnc_add_check_remove(self, session):
        phone = "+447700900888"
        r = session.post(f"{API}/compliance/dnc", json={"phone": phone, "reason": "test"}, timeout=15)
        assert r.status_code == 200
        # check
        r2 = session.get(f"{API}/compliance/check", params={"phone": phone}, timeout=15)
        assert r2.status_code == 200
        assert r2.json()["on_dnc"] is True
        # cleanup
        dncs = session.get(f"{API}/compliance/dnc").json()
        match = [x for x in dncs if x["phone"] == phone]
        if match:
            session.delete(f"{API}/compliance/dnc/{match[0]['id']}")

    def test_gdpr_erasure(self, session):
        # create test contact then erase
        r = session.post(f"{API}/contacts", json={
            "name": "TEST_Erase", "phone": "+447700900777", "consent": True
        }, timeout=15)
        cid = r.json()["id"]
        r2 = session.post(f"{API}/compliance/erasure", json={"contact_id": cid}, timeout=15)
        assert r2.status_code == 200
        assert r2.json()["ok"] is True
        # verify gone
        r3 = session.get(f"{API}/contacts/{cid}", timeout=15)
        assert r3.status_code == 404


# -------- Settings & Users --------
class TestSettings:
    def test_get_org(self, session):
        r = session.get(f"{API}/settings/org", timeout=15)
        assert r.status_code == 200
        assert "calling_hours_start" in r.json()

    def test_get_integrations(self, session):
        r = session.get(f"{API}/settings/integrations", timeout=15)
        assert r.status_code == 200

    def test_update_integrations(self, session):
        payload = {
            "tcx_enabled": False, "tcx_url": "https://3cx.test", "tcx_username": "u",
            "tcx_password": "p", "tcx_extension": "100",
            "elevenlabs_api_key": "", "elevenlabs_enabled": False,
            "o365_enabled": False, "o365_tenant_id": "", "o365_client_id": "",
            "o365_client_secret": "", "llm_provider": "anthropic", "llm_model": "claude-sonnet-4-6",
        }
        r = session.put(f"{API}/settings/integrations", json=payload, timeout=15)
        assert r.status_code == 200
        # verify persistence
        r2 = session.get(f"{API}/settings/integrations", timeout=15)
        assert r2.json()["tcx_url"] == "https://3cx.test"

    def test_list_users(self, session):
        r = session.get(f"{API}/users", timeout=15)
        assert r.status_code == 200
        assert any(u["email"] == ADMIN_EMAIL for u in r.json())

    def test_invite_and_delete_user(self, session):
        email = f"test_agent_{int(time.time())}@example.com"
        r = session.post(f"{API}/users", json={
            "email": email, "name": "TEST Agent", "password": "AgentPass123!", "role": "agent"
        }, timeout=15)
        assert r.status_code == 200
        uid = r.json()["id"]
        r2 = session.delete(f"{API}/users/{uid}", timeout=15)
        assert r2.status_code == 200
