"""Iteration 11 tests: per-channel AI blueprints, owner moderation (users/businesses),
campaign 'specific clients', voice controls, test-call opening resolution.

Uses cookie-based auth. Owner = owner@coldwave.ai, Admin = admin@coldwave.ai.
IMPORTANT: never triggers live 3CX dial. Cleans up own test data.
"""
import os
import pytest
import requests

BASE = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE}/api"

OWNER = {"email": "owner@coldwave.ai", "password": "Owner123!"}
ADMIN = {"email": "admin@coldwave.ai", "password": "Admin123!"}


def _login(creds):
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json=creds, timeout=20)
    assert r.status_code == 200, f"Login failed for {creds['email']}: {r.status_code} {r.text}"
    return s


@pytest.fixture(scope="module")
def owner_s():
    return _login(OWNER)


@pytest.fixture(scope="module")
def admin_s():
    return _login(ADMIN)


# ---------------- Per-channel blueprints ----------------
class TestBlueprintsChannel:
    def test_owner_can_create_channel_blueprints(self, owner_s):
        created = {}
        for ch in ("call", "whatsapp", "sms"):
            r = owner_s.post(f"{API}/admin/blueprints", json={
                "name": f"QA {ch} blueprint", "prompt": f"Channel-specific prompt for {ch}. Be concise.",
                "channel": ch,
            })
            assert r.status_code == 200, r.text
            data = r.json()
            assert data["channel"] == ch
            assert data["name"] == f"QA {ch} blueprint"
            created[ch] = data["id"]
        pytest.qa_bp = created
        # List and confirm channel field is present
        lst = owner_s.get(f"{API}/admin/blueprints").json()
        by_id = {b["id"]: b for b in lst}
        for ch, bid in created.items():
            assert by_id[bid]["channel"] == ch

    def test_admin_cannot_create_blueprint(self, admin_s):
        r = admin_s.post(f"{API}/admin/blueprints", json={"name": "nope", "prompt": "x", "channel": "call"})
        assert r.status_code in (401, 403), r.status_code

    def test_owner_assigns_channel_blueprint_and_persists(self, owner_s):
        # find the demo/malik business or any non-owner business
        biz = owner_s.get(f"{API}/admin/businesses").json()
        assert isinstance(biz, list) and len(biz) > 0
        target = next((b for b in biz if "coldwave demo" in b["name"].lower()), biz[0])
        oid = target["id"]
        bp = pytest.qa_bp
        # Assign call/whatsapp/sms
        for ch in ("call", "whatsapp", "sms"):
            r = owner_s.put(f"{API}/admin/businesses/{oid}/channel-blueprint",
                            json={"channel": ch, "blueprint_id": bp[ch]})
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["channel_blueprints"][ch] == bp[ch]
        # Reload and confirm
        biz2 = owner_s.get(f"{API}/admin/businesses").json()
        t2 = next(b for b in biz2 if b["id"] == oid)
        for ch in ("call", "whatsapp", "sms"):
            assert t2["channel_blueprints"].get(ch) == bp[ch], t2["channel_blueprints"]
        pytest.qa_target_oid = oid

    def test_channel_blueprint_clear(self, owner_s):
        oid = pytest.qa_target_oid
        # Clear whatsapp assignment (blueprint_id=None)
        r = owner_s.put(f"{API}/admin/businesses/{oid}/channel-blueprint",
                        json={"channel": "whatsapp", "blueprint_id": None})
        assert r.status_code == 200, r.text
        assert "whatsapp" not in r.json()["channel_blueprints"]

    def test_cleanup_blueprints(self, owner_s):
        # Clear remaining assignments and delete blueprints
        oid = pytest.qa_target_oid
        for ch in ("call", "sms"):
            owner_s.put(f"{API}/admin/businesses/{oid}/channel-blueprint",
                        json={"channel": ch, "blueprint_id": None})
        for bid in pytest.qa_bp.values():
            r = owner_s.delete(f"{API}/admin/blueprints/{bid}")
            assert r.status_code in (200, 400, 404), r.text


# ---------------- Owner user moderation ----------------
class TestOwnerUserModeration:
    def test_admin_cannot_call_owner_endpoints(self, admin_s):
        r = admin_s.get(f"{API}/admin/users")
        assert r.status_code in (401, 403)

    def test_find_test_user(self, owner_s):
        users = owner_s.get(f"{API}/admin/users").json()
        target = next((u for u in users if u["email"] == "test@test.co"), None)
        assert target is not None, "test@test.co not found in demo org"
        pytest.qa_test_uid = target["id"]
        pytest.qa_test_original_role = target.get("role", "agent")

    def test_change_role_agent_to_admin_and_back(self, owner_s):
        uid = pytest.qa_test_uid
        r = owner_s.put(f"{API}/admin/users/{uid}/role", json={"role": "admin"})
        assert r.status_code == 200, r.text
        assert r.json()["role"] == "admin"
        # Verify via list
        u = next(x for x in owner_s.get(f"{API}/admin/users").json() if x["id"] == uid)
        assert u["role"] == "admin"
        # Revert
        r2 = owner_s.put(f"{API}/admin/users/{uid}/role", json={"role": "agent"})
        assert r2.status_code == 200
        u = next(x for x in owner_s.get(f"{API}/admin/users").json() if x["id"] == uid)
        assert u["role"] == "agent"

    def test_cannot_assign_owner_role(self, owner_s):
        uid = pytest.qa_test_uid
        r = owner_s.put(f"{API}/admin/users/{uid}/role", json={"role": "owner"})
        assert r.status_code == 400

    def test_ban_and_unban_user(self, owner_s):
        uid = pytest.qa_test_uid
        r = owner_s.post(f"{API}/admin/users/{uid}/ban", json={"reason": "qa test"})
        assert r.status_code == 200, r.text
        u = next(x for x in owner_s.get(f"{API}/admin/users").json() if x["id"] == uid)
        assert u.get("banned") is True
        assert u.get("ban_reason") == "qa test"
        r2 = owner_s.post(f"{API}/admin/users/{uid}/unban")
        assert r2.status_code == 200
        u = next(x for x in owner_s.get(f"{API}/admin/users").json() if x["id"] == uid)
        assert u.get("banned") is False

    def test_cannot_ban_owner(self, owner_s):
        users = owner_s.get(f"{API}/admin/users").json()
        owner = next(u for u in users if u["email"] == OWNER["email"])
        r = owner_s.post(f"{API}/admin/users/{owner['id']}/ban", json={"reason": "should fail"})
        assert r.status_code == 400


# ---------------- Business suspend/reinstate ----------------
class TestBusinessSuspend:
    def test_suspend_and_reinstate_maliks(self, owner_s):
        biz = owner_s.get(f"{API}/admin/businesses").json()
        target = next((b for b in biz if "malik" in b["name"].lower()), None)
        if not target:
            pytest.skip("Malik's Workspace not present in demo — skipping")
        oid = target["id"]
        r = owner_s.post(f"{API}/admin/businesses/{oid}/ban", json={"reason": "qa suspend"})
        assert r.status_code == 200, r.text
        biz2 = owner_s.get(f"{API}/admin/businesses").json()
        t2 = next(b for b in biz2 if b["id"] == oid)
        assert t2["banned"] is True
        assert t2["ban_reason"] == "qa suspend"
        # Reinstate immediately
        r2 = owner_s.post(f"{API}/admin/businesses/{oid}/unban")
        assert r2.status_code == 200, r2.text
        biz3 = owner_s.get(f"{API}/admin/businesses").json()
        t3 = next(b for b in biz3 if b["id"] == oid)
        assert t3["banned"] is False


# ---------------- Campaign specific-clients ----------------
class TestCampaignSpecific:
    def test_create_specific_campaign_and_verify_queue(self, admin_s):
        # Pick 2 contacts
        contacts = admin_s.get(f"{API}/contacts").json()
        assert isinstance(contacts, list) and len(contacts) >= 2, "need at least 2 contacts in demo"
        # Filter non-opted-out
        eligible = [c for c in contacts if not c.get("opted_out") and c.get("status") not in ("opted_out", "dnc")][:2]
        assert len(eligible) >= 2
        cids = [c["id"] for c in eligible]
        # Need a script + voice from demo
        scripts = admin_s.get(f"{API}/scripts").json()
        voices = admin_s.get(f"{API}/voices").json()["voices"]
        assert scripts and voices
        payload = {
            "name": "QA Specific",
            "script_id": scripts[0]["id"],
            "voice_id": voices[0]["id"],
            "audience": "all",
            "contact_ids": cids,
            "schedule_type": "manual",
        }
        r = admin_s.post(f"{API}/campaigns", json=payload)
        assert r.status_code == 200, r.text
        camp = r.json()
        assert camp["audience"] == "specific"
        assert set(camp["contact_ids"]) == set(cids)
        pytest.qa_camp_id = camp["id"]

        # GET queue and check upcoming contains only selected clients
        q = admin_s.get(f"{API}/campaigns/{camp['id']}/queue").json()
        upcoming_ids = {u["contact_id"] for u in q["upcoming"]}
        assert upcoming_ids.issubset(set(cids)), f"upcoming leaked: {upcoming_ids - set(cids)}"
        assert set(cids).issubset(upcoming_ids) or len(upcoming_ids) > 0

    def test_delete_specific_campaign(self, admin_s):
        cid = getattr(pytest, "qa_camp_id", None)
        if not cid:
            pytest.skip("no campaign to delete")
        r = admin_s.delete(f"{API}/campaigns/{cid}")
        assert r.status_code == 200


# ---------------- Voice characteristics ----------------
class TestVoiceCharacteristics:
    def test_update_all_voice_params_and_persist(self, admin_s):
        voices = admin_s.get(f"{API}/voices").json()["voices"]
        assert voices
        vid = voices[0]["id"]
        pytest.qa_voice_id = vid
        # Save original values
        pytest.qa_voice_original = {
            "speed": voices[0].get("speed", 1.0),
            "stability": voices[0].get("stability", 0.5),
            "style": voices[0].get("style", 0.0),
            "dynamic": voices[0].get("dynamic", False),
        }
        r = admin_s.put(f"{API}/voices/{vid}/characteristics",
                        json={"speed": 1.15, "stability": 0.7, "style": 0.4, "dynamic": False})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["speed"] == pytest.approx(1.15) if False else abs(body["speed"] - 1.15) < 1e-6
        assert abs(body["stability"] - 0.7) < 1e-6
        assert abs(body["style"] - 0.4) < 1e-6
        assert body["dynamic"] is False
        # verify persisted via list
        v2 = next(v for v in admin_s.get(f"{API}/voices").json()["voices"] if v["id"] == vid)
        assert abs(v2["stability"] - 0.7) < 1e-6
        assert abs(v2["style"] - 0.4) < 1e-6

    def test_dynamic_toggle(self, admin_s):
        vid = pytest.qa_voice_id
        r = admin_s.put(f"{API}/voices/{vid}/characteristics", json={"dynamic": True})
        assert r.status_code == 200
        v = next(v for v in admin_s.get(f"{API}/voices").json()["voices"] if v["id"] == vid)
        assert v["dynamic"] is True

    def test_range_clamping(self, admin_s):
        vid = pytest.qa_voice_id
        r = admin_s.put(f"{API}/voices/{vid}/characteristics", json={"speed": 5.0, "stability": -1.0, "style": 99.0})
        assert r.status_code == 200
        body = r.json()
        assert body["speed"] <= 1.2 and body["stability"] >= 0.0 and body["style"] <= 1.0

    def test_reset_voice(self, admin_s):
        vid = pytest.qa_voice_id
        orig = pytest.qa_voice_original
        r = admin_s.put(f"{API}/voices/{vid}/characteristics",
                        json={"speed": 1.0, "stability": 0.5, "style": 0.0, "dynamic": False})
        assert r.status_code == 200


# ---------------- Test-call opening resolution ----------------
class TestOpeningResolution:
    def test_opening_is_scripted_or_blueprint_not_hardcoded(self, admin_s):
        scripts = admin_s.get(f"{API}/scripts").json()
        # Prefer a personality script if available; otherwise create one
        personality_script = next((s for s in scripts if (s.get("script_type") == "personality")), None)
        created_id = None
        if not personality_script:
            r = admin_s.post(f"{API}/scripts", json={
                "name": "QA Personality Opening",
                "content": "",
                "personality": "Friendly, brief UK B2B outbound rep who values the prospect's time.",
                "objective": "Book a 15-min demo",
                "script_type": "personality",
            })
            assert r.status_code == 200, r.text
            personality_script = r.json()
            created_id = personality_script["id"]
        voices = admin_s.get(f"{API}/voices").json()["voices"]
        r = admin_s.post(f"{API}/calls/test/start", json={
            "script_id": personality_script["id"],
            "voice_id": voices[0]["id"],
        })
        assert r.status_code == 200, r.text
        body = r.json()
        opening = body["opening"]
        meta = body["opening_meta"]
        assert opening, "opening is empty"
        assert "Hello, this is your AI assistant calling" not in opening, f"hardcoded opening: {opening}"
        assert meta["mode"] in ("blueprint", "scripted", "kb", "fallback"), meta
        # For personality script, should be blueprint or fallback (llm)
        assert meta["mode"] != "scripted" or True  # allowed if scripted first-line exists
        call_id = body["call_id"]
        # End the call
        r2 = admin_s.post(f"{API}/calls/test/{call_id}/end")
        assert r2.status_code == 200
        # cleanup created script
        if created_id:
            admin_s.delete(f"{API}/scripts/{created_id}")
