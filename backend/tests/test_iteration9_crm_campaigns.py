"""Iteration 9 — CRM 2.0 & Campaigns 2.0 backend tests.

SAFETY: This suite MUST NOT hit POST /api/campaigns/{id}/dial-next or
POST /api/calls/dial — those trigger REAL 3CX outbound calls on the demo org.
"""
import os
import time
import pytest
import requests

BASE = os.environ.get("REACT_APP_BACKEND_URL", "https://dialflow-crm-1.preview.emergentagent.com").rstrip("/")
API = f"{BASE}/api"
ADMIN = ("admin@coldwave.ai", "Admin123!")


@pytest.fixture(scope="session")
def s():
    sess = requests.Session()
    sess.headers.update({"Content-Type": "application/json"})
    r = sess.post(f"{API}/auth/login", json={"email": ADMIN[0], "password": ADMIN[1]}, timeout=30)
    assert r.status_code == 200, r.text
    # cookie-based; also set bearer just in case
    tok = r.json().get("access_token")
    if tok:
        sess.headers["Authorization"] = f"Bearer {tok}"
    return sess


# ---------- CRM 2.0 ----------
class TestContactsEnrichment:
    def test_list_contacts_enriched_fields(self, s):
        r = s.get(f"{API}/contacts", timeout=20)
        assert r.status_code == 200, r.text
        rows = r.json()
        assert rows, "Expected at least one seeded contact"
        required = {"call_count", "last_call_rating", "last_call_summary",
                    "last_call_campaign", "last_call_date"}
        for row in rows:
            missing = required - set(row.keys())
            assert not missing, f"Contact {row.get('name')} missing keys: {missing}"
            assert isinstance(row["call_count"], int)

    def test_tom_obrien_has_call(self, s):
        r = s.get(f"{API}/contacts", timeout=20)
        assert r.status_code == 200
        tom = next((c for c in r.json() if "Tom" in c["name"] and "Brien" in c["name"]), None)
        assert tom, "Seeded contact 'Tom O'Brien' not found"
        assert tom["call_count"] >= 1, f"Tom should have >=1 call, got {tom['call_count']}"
        # Detail should include enriched calls array
        r2 = s.get(f"{API}/contacts/{tom['id']}", timeout=20)
        assert r2.status_code == 200
        detail = r2.json()
        assert "calls" in detail and isinstance(detail["calls"], list)
        assert len(detail["calls"]) >= 1
        c0 = detail["calls"][0]
        for k in ("campaign_name", "rating", "summary", "next_action"):
            assert k in c0, f"Enriched call missing key: {k}"


# ---------- Campaigns 2.0 ----------
class TestCampaignsAnalytics:
    def test_list_campaigns_analytics(self, s):
        r = s.get(f"{API}/campaigns", timeout=20)
        assert r.status_code == 200
        camps = r.json()
        assert camps, "Expected at least one seeded campaign"
        for c in camps:
            assert "analytics" in c, f"Campaign {c.get('name')} missing analytics"
            a = c["analytics"]
            for k in ("times_used", "avg_rating", "positive_rate", "sentiment"):
                assert k in a, f"analytics missing key: {k}"
            assert isinstance(a["positive_rate"], (int, float))

    def test_campaign_detail_analytics_endpoint(self, s):
        camps = s.get(f"{API}/campaigns").json()
        cid = camps[0]["id"]
        r = s.get(f"{API}/campaigns/{cid}/analytics", timeout=20)
        assert r.status_code == 200
        d = r.json()
        for k in ("times_used", "avg_rating", "positive_rate", "sentiment"):
            assert k in d

    def test_campaign_queue_shape(self, s):
        camps = s.get(f"{API}/campaigns").json()
        cid = camps[0]["id"]
        r = s.get(f"{API}/campaigns/{cid}/queue", timeout=20)
        assert r.status_code == 200
        q = r.json()
        for k in ("contacted", "upcoming", "contacted_count", "upcoming_count", "next", "audience"):
            assert k in q, f"queue missing key: {k}"
        assert isinstance(q["contacted"], list)
        assert isinstance(q["upcoming"], list)
        assert q["contacted_count"] == len(q["contacted"])

    def test_create_campaign_with_audience_and_schedule(self, s):
        scripts = s.get(f"{API}/scripts").json()
        sid = scripts[0]["id"]
        payload = {
            "name": f"TEST_Cmp_{int(time.time())}",
            "script_id": sid,
            "voice_id": "george",
            "description": "iter9",
            "audience": "positive",
            "schedule_type": "scheduled",
            "scheduled_at": "2026-02-01T10:00:00Z",
        }
        r = s.post(f"{API}/campaigns", json=payload, timeout=20)
        assert r.status_code == 200, r.text
        c = r.json()
        cid = c["id"]
        try:
            assert c["audience"] == "positive"
            assert c["schedule_type"] == "scheduled"
            assert c["scheduled_at"] == "2026-02-01T10:00:00Z"
            # verify persistence via list
            listed = s.get(f"{API}/campaigns").json()
            found = next((x for x in listed if x["id"] == cid), None)
            assert found and found["audience"] == "positive"
        finally:
            s.delete(f"{API}/campaigns/{cid}")
